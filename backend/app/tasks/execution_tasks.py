"""
ワークフロー継続ロジック — 次世代AIオーケストレーション

Celery 廃止済み。通常関数として completion_service から直接呼ばれる。

オーケストレーション機能:
  - 楽観ロック (並列完了時のレース条件防止)
  - エラーリカバリ: retry / skip / stop
  - 構造化コンテキスト + input_mapping + スコープ分離
  - グループ条件分岐
  - 親スキルモード: required / optional / disabled

  [次世代]
  - Blackboard: 共有メモリ (Feature 2)
  - Reflection: 品質ゲート + 自己修正ループ (Feature 1)
  - Debate/Judge: 並列結果の合議 (Feature 5)
  - Supervisor: グループ間監視・ルーティング (Feature 3)
  - Dynamic Decomposition: 動的タスク分解 (Feature 4)
"""
import copy
import json
import logging
import re
from datetime import datetime, timezone, timedelta

from sqlalchemy import update

from app.models import (
    Execution, Skill, Workflow, WorkflowSkill, WorkflowExecution, WorkflowGroup,
)
from app.database import SessionLocal
from app.encryption import encryption_service
from app.services.agent_profiles import (
    DEFAULT_READONLY_CONSTRAINTS,
    DEFAULT_VERIFICATION_CONTRACT,
    build_blackboard_summary,
    normalize_agent_profile,
    READONLY_PROFILES,
    VERDICT_REQUIRED_PROFILES,
)
from app.services.auto_orchestration import (
    compute_orchestration_overrides,
    get_effective,
)

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

# execution_role 定数
ROLE_QUALITY_GATE = "quality_gate"
ROLE_SUPERVISOR = "supervisor"
ROLE_DEBATE_JUDGE = "debate_judge"


def _parse_json_text(value, default=None):
    if value is None:
        return {} if default is None else default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {} if default is None else default


def _resolve_agent_profile(ws, skill) -> str:
    return normalize_agent_profile(getattr(ws, "agent_profile", None) or getattr(skill, "default_agent_profile", None))


def _collect_handoff_refs(ws) -> list[str]:
    refs = []
    output_key = getattr(ws, "output_key", None)
    if output_key:
        refs.append(str(output_key))
    return refs


def _build_step_metadata(ws, skill, agent_profile: str) -> dict:
    return {
        "workflow_skill_id": getattr(ws, "id", None),
        "skill_order": getattr(ws, "skill_order", None),
        "skill_name": getattr(ws, "skill_name", None) or getattr(skill, "name", None),
        "skill_id": getattr(skill, "id", None),
        "model_type": getattr(skill, "model_type", None),
        "agent_profile": agent_profile,
        "readonly": agent_profile in READONLY_PROFILES,
        "verdict_required": agent_profile in VERDICT_REQUIRED_PROFILES,
        "output_key": getattr(ws, "output_key", None),
        "handoff_refs": _collect_handoff_refs(ws),
    }


def _augment_skill_input_with_profile(skill_input, wf_exec, workflow, ws, skill, structured_context):
    agent_profile = _resolve_agent_profile(ws, skill)
    blackboard = structured_context.get("blackboard", {}) if isinstance(structured_context, dict) else {}
    skill_input["_ppt_agent_profile"] = agent_profile
    skill_input["_ppt_workflow_name"] = getattr(workflow, "name", "") or ""
    skill_input["_ppt_workflow_goal"] = getattr(workflow, "description", "") or ""
    skill_input["_ppt_handoff_context"] = _parse_json_text(getattr(wf_exec, "handoff_summary", None), {})
    skill_input["_ppt_blackboard_summary"] = {
        "keys": list(blackboard.keys()) if isinstance(blackboard, dict) else [],
        "count": len(blackboard) if isinstance(blackboard, dict) else 0,
    }
    step_metadata = _build_step_metadata(ws, skill, agent_profile)
    skill_input["_ppt_step_metadata"] = step_metadata
    skill_input["_ppt_handoff_refs"] = step_metadata.get("handoff_refs", [])
    if agent_profile in READONLY_PROFILES:
        skill_input["_ppt_readonly_constraints"] = DEFAULT_READONLY_CONSTRAINTS
    if agent_profile in VERDICT_REQUIRED_PROFILES:
        skill_input["_ppt_verification_contract"] = DEFAULT_VERIFICATION_CONTRACT
    return agent_profile


def _set_handoff_target_profile(wf_exec, agent_profile: str):
    payload = _parse_json_text(getattr(wf_exec, "handoff_summary", None), {})
    if not isinstance(payload, dict) or not payload:
        return
    # handoff_summary は実行契約の正本ではなく派生メタデータなので、
    # 次 step が実際に launch されたタイミングで only-if-known で to_profile を補完する。
    payload["to_profile"] = normalize_agent_profile(agent_profile)
    wf_exec.handoff_summary = json.dumps(payload, ensure_ascii=False)


# ===========================================================================
# ヘルパー: ドット記法パス解決
# ===========================================================================

def _resolve_path(context: dict, path: str):
    parts = path.split(".")
    current = context
    for part in parts:
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, (list, tuple)):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return current


# ===========================================================================
# ヘルパー: 条件式評価
# ===========================================================================

def _evaluate_condition(condition_json, context: dict) -> bool:
    if not condition_json:
        return True
    try:
        cond = json.loads(condition_json) if isinstance(condition_json, str) else condition_json
    except (json.JSONDecodeError, TypeError):
        return True
    return _eval_cond(cond, context)


def _eval_cond(cond: dict, context: dict) -> bool:
    if not isinstance(cond, dict):
        return True
    op = cond.get("operator", "")
    if op == "and":
        return all(_eval_cond(c, context) for c in cond.get("conditions", []))
    if op == "or":
        return any(_eval_cond(c, context) for c in cond.get("conditions", []))
    actual = _resolve_path(context, cond.get("field", ""))
    expected = cond.get("value")
    if op == "equals":
        return str(actual) == str(expected)
    if op == "not_equals":
        return str(actual) != str(expected)
    if op == "contains":
        return str(expected) in str(actual) if actual else False
    if op == "not_contains":
        return str(expected) not in str(actual) if actual else True
    if op == "gt":
        try: return float(actual) > float(expected)
        except (TypeError, ValueError): return False
    if op == "gte":
        try: return float(actual) >= float(expected)
        except (TypeError, ValueError): return False
    if op == "lt":
        try: return float(actual) < float(expected)
        except (TypeError, ValueError): return False
    if op == "lte":
        try: return float(actual) <= float(expected)
        except (TypeError, ValueError): return False
    if op == "is_empty":
        return not actual
    if op == "is_not_empty":
        return bool(actual)
    if op == "regex_match":
        try: return bool(re.search(str(expected), str(actual)))
        except re.error: return False
    return True


# ===========================================================================
# ヘルパー: 構造化コンテキスト構築 + Blackboard (Feature 2)
# ===========================================================================

def _build_structured_context(db, wf_exec, global_input, completed_executions, overrides=None):
    steps = {}
    all_step_results = []

    for ex in completed_executions:
        if ex.status != "success" or not ex.workflow_skill_id:
            continue
        if ex.execution_role:
            continue  # 品質ゲート/ジャッジ/スーパーバイザーの結果はstepsに含めない

        raw = ex.output_data
        parsed = raw
        if raw:
            try:
                parsed = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                pass

        step_data = {
            "output": parsed,
            "status": ex.status,
            "skill_id": ex.skill_id,
            "skill_order": ex.skill_order,
            "workflow_skill_id": ex.workflow_skill_id,
        }
        steps[str(ex.workflow_skill_id)] = step_data

        ws = db.query(WorkflowSkill).filter(WorkflowSkill.id == ex.workflow_skill_id).first()
        if ws:
            output_key = get_effective(ws, "output_key", overrides or {}, ws.id, "workflow_skills")
            if output_key:
                steps[output_key] = step_data

        all_step_results.append({
            "skill_order": ex.skill_order,
            "workflow_skill_id": ex.workflow_skill_id,
            "skill_id": ex.skill_id,
            "output": parsed,
        })

    # Blackboard 読み込み
    blackboard = {}
    if wf_exec.blackboard_data:
        try:
            blackboard = json.loads(wf_exec.blackboard_data)
        except (json.JSONDecodeError, TypeError):
            pass

    return {
        "global": global_input,
        "steps": steps,
        "all_step_results": all_step_results,
        "blackboard": blackboard,
    }


def _build_skill_input(ws, structured_context, global_input, previous_output,
                       per_skill_input, all_step_results):
    input_mapping = None
    if ws.input_mapping:
        try:
            input_mapping = json.loads(ws.input_mapping) if isinstance(ws.input_mapping, str) else ws.input_mapping
        except (json.JSONDecodeError, TypeError):
            pass

    if input_mapping:
        skill_input = dict(global_input)
        for target_field, source_path in input_mapping.items():
            resolved = _resolve_path(structured_context, source_path)
            if resolved is not None:
                skill_input[target_field] = resolved
        skill_input["all_step_results"] = all_step_results
        skill_input["global_input_data"] = global_input
    else:
        skill_input = dict(global_input)
        if previous_output:
            skill_input["previous_output"] = previous_output
            skill_input["previous_step_result"] = previous_output
            if "research_data" not in skill_input:
                skill_input["research_data"] = previous_output
            if "analysis_result" not in skill_input:
                skill_input["analysis_result"] = previous_output
        skill_input["all_step_results"] = all_step_results
        skill_input.setdefault("global_input_data", global_input)

    # Blackboard を常に注入
    skill_input["blackboard"] = structured_context.get("blackboard", {})

    skill_overrides = per_skill_input.get(str(ws.id), {})
    if skill_overrides:
        skill_input.update(skill_overrides)
    return skill_input


# ===========================================================================
# Blackboard 書き込み (Feature 2)
# ===========================================================================

def _merge_blackboard(db, wf_exec, key: str, value):
    """Blackboard にキーを書き込む"""
    bb = {}
    if wf_exec.blackboard_data:
        try:
            bb = json.loads(wf_exec.blackboard_data)
        except (json.JSONDecodeError, TypeError):
            pass
    bb[key] = value
    wf_exec.blackboard_data = json.dumps(bb, ensure_ascii=False)


def _auto_write_blackboard(db, wf_exec, execution, overrides=None):
    """output_key があるスキルの出力を自動でBlackboardに書き込む（オーバーライド対応）"""
    if not execution.workflow_skill_id or not execution.output_data:
        return
    ws = db.query(WorkflowSkill).filter(WorkflowSkill.id == execution.workflow_skill_id).first()
    if not ws:
        return
    output_key = get_effective(ws, "output_key", overrides or {}, ws.id, "workflow_skills")
    if output_key:
        parsed = execution.output_data
        try:
            parsed = json.loads(execution.output_data)
        except (json.JSONDecodeError, TypeError):
            pass
        _merge_blackboard(db, wf_exec, output_key, parsed)


# ===========================================================================
# 品質ゲート / Reflection (Feature 1)
# ===========================================================================

def _check_quality_gate_inline(ws, output_text: str, overrides=None) -> dict:
    """
    inline品質ゲート(regex/json_schema)。LLM不要。自動オーバーライド対応。
    Returns: {"pass": bool, "critique": str}
    """
    gate_type = get_effective(ws, "quality_gate_type", overrides or {}, ws.id, "workflow_skills") or "disabled"
    gate_prompt = get_effective(ws, "quality_gate_prompt", overrides or {}, ws.id, "workflow_skills")
    if gate_type == "disabled" or not gate_prompt:
        return {"pass": True, "critique": ""}

    # プロンプトが暗号化されている場合は復号（自動生成の場合はそのまま）
    raw_prompt = gate_prompt
    try:
        raw_prompt = encryption_service.decrypt(raw_prompt)
    except Exception:
        pass  # 暗号化されていない場合はそのまま使う

    if gate_type == "regex":
        pattern = raw_prompt
        try:
            if re.search(pattern, output_text):
                return {"pass": True, "critique": ""}
            return {"pass": False, "critique": f"正規表現パターン '{pattern}' にマッチしませんでした"}
        except re.error as e:
            return {"pass": True, "critique": f"正規表現エラー: {e}"}

    if gate_type == "json_schema":
        try:
            parsed = json.loads(output_text)
            schema = json.loads(raw_prompt)
            missing = [k for k in schema.get("required", []) if k not in parsed]
            if missing:
                return {"pass": False, "critique": f"必須フィールドが不足: {', '.join(missing)}"}
            return {"pass": True, "critique": ""}
        except json.JSONDecodeError:
            return {"pass": False, "critique": "出力がJSON形式ではありません"}

    return {"pass": True, "critique": ""}


def _launch_quality_gate_llm(db, wf_exec, ws, execution):
    """LLMベース品質ゲートを起動"""
    gate_prompt_raw = ws.quality_gate_prompt
    if not gate_prompt_raw:
        return

    # プロンプト復号
    try:
        decrypted_prompt = encryption_service.decrypt(gate_prompt_raw)
    except Exception:
        decrypted_prompt = gate_prompt_raw

    # ゲートプロンプトにスキル出力を注入
    gate_input = {
        "skill_output": execution.output_data or "",
        "skill_name": ws.skill_name or "",
        "reflection_loop": execution.reflection_loop,
        "validation_instructions": decrypted_prompt,
    }

    gate_model = ws.quality_gate_model or execution.model_used or "gpt-5.4"

    gate_exec = Execution(
        account_id=wf_exec.account_id,
        skill_id=None,
        workflow_execution_id=wf_exec.id,
        workflow_skill_id=ws.id,
        skill_order=execution.skill_order,
        input_data=json.dumps(gate_input, ensure_ascii=False),
        status="pending_local",
        dispatch_mode="local",
        model_used=gate_model,
        enable_deep_think=False,
        output_format="txt",
        execution_role=ROLE_QUALITY_GATE,
        reflection_loop=execution.reflection_loop,
        executed_at=datetime.now(JST),
    )
    db.add(gate_exec)
    db.flush()
    db.commit()
    logger.info(f"WF {wf_exec.id}: quality gate launched for ws={ws.id} (loop={execution.reflection_loop})")


def _handle_quality_gate_result(db, wf_exec, gate_execution):
    """品質ゲート完了時の処理。passならWF継続、failならリフレクション再実行"""
    ws = db.query(WorkflowSkill).filter(WorkflowSkill.id == gate_execution.workflow_skill_id).first()
    if not ws:
        return

    # ゲート出力をパース
    verdict = {"pass": True, "critique": ""}
    if gate_execution.output_data:
        try:
            verdict = json.loads(gate_execution.output_data)
        except (json.JSONDecodeError, TypeError):
            output_lower = gate_execution.output_data.lower()
            verdict["pass"] = "pass" in output_lower or "true" in output_lower
            verdict["critique"] = gate_execution.output_data

    if verdict.get("pass", True):
        logger.info(f"WF {wf_exec.id}: quality gate passed for ws={ws.id}")
        # 通常のWF継続
        from app.tasks.execution_tasks import continue_workflow_execution
        continue_workflow_execution(wf_exec.id, gate_execution.skill_order)
        return

    # 不合格 → リフレクション再実行
    current_loop = gate_execution.reflection_loop or 0
    if current_loop >= ws.max_reflection_loops:
        logger.info(f"WF {wf_exec.id}: reflection exhausted for ws={ws.id}, proceeding")
        continue_workflow_execution(wf_exec.id, gate_execution.skill_order)
        return

    # 元のスキルを再実行 (critique付き)
    skill = db.query(Skill).filter(Skill.id == ws.skill_id).first()
    if not skill:
        continue_workflow_execution(wf_exec.id, gate_execution.skill_order)
        return

    # 元のスキルの入力を取得して critique を追加
    original_exec = (
        db.query(Execution)
        .filter(
            Execution.workflow_execution_id == wf_exec.id,
            Execution.workflow_skill_id == ws.id,
            Execution.execution_role.is_(None),
            Execution.reflection_loop == current_loop,
            Execution.status == "success",
        )
        .order_by(Execution.id.desc())
        .first()
    )

    skill_input = {}
    if original_exec and original_exec.input_data:
        try:
            skill_input = json.loads(original_exec.input_data)
        except (json.JSONDecodeError, TypeError):
            pass

    skill_input["previous_attempt_output"] = original_exec.output_data if original_exec else ""
    skill_input["quality_critique"] = verdict.get("critique", "")
    skill_input["reflection_loop"] = current_loop + 1

    new_exec = Execution(
        account_id=wf_exec.account_id,
        skill_id=skill.id,
        workflow_execution_id=wf_exec.id,
        workflow_skill_id=ws.id,
        skill_order=ws.skill_order,
        input_data=json.dumps(skill_input, ensure_ascii=False),
        status="pending_local",
        dispatch_mode="local",
        model_used=skill.model_type,
        enable_deep_think=bool(getattr(skill, "enable_deep_think", True)),
        output_format=original_exec.output_format if original_exec else "txt",
        reflection_loop=current_loop + 1,
        executed_at=datetime.now(JST),
    )
    db.add(new_exec)
    db.flush()
    db.commit()
    logger.info(f"WF {wf_exec.id}: reflection retry ws={ws.id} loop={current_loop + 1}/{ws.max_reflection_loops}")


# ===========================================================================
# ジャッジ (Feature 5: Debate/Consensus)
# ===========================================================================

def _launch_judge(db, wf_exec, group, structured_context, global_input, overrides=None):
    """並列Group完了後にジャッジを起動（自動オーバーライド対応）"""
    judge_prompt_raw = get_effective(group, "judge_prompt", overrides or {}, group.id, "groups")
    if not judge_prompt_raw:
        return False

    # グループ内全スキルの出力を収集
    group_outputs = []
    group_skills = (
        db.query(WorkflowSkill)
        .filter(WorkflowSkill.group_id == group.id)
        .order_by(WorkflowSkill.order_in_group.asc())
        .all()
    )
    for ws in group_skills:
        step = structured_context["steps"].get(str(ws.id))
        if step:
            group_outputs.append({
                "skill_name": ws.skill_name or f"Step {ws.skill_order}",
                "output": step["output"],
            })

    # ジャッジプロンプト復号（自動生成の場合は暗号化されていないのでそのまま使う）
    try:
        decrypted_prompt = encryption_service.decrypt(judge_prompt_raw)
    except Exception:
        decrypted_prompt = judge_prompt_raw

    judge_input = dict(global_input)
    judge_input["group_outputs"] = group_outputs
    judge_input["group_name"] = group.group_name or f"Group {group.group_order}"
    judge_input["judge_instructions"] = decrypted_prompt
    judge_input["all_step_results"] = structured_context.get("all_step_results", [])
    judge_input["blackboard"] = structured_context.get("blackboard", {})

    judge_model = get_effective(group, "judge_model", overrides or {}, group.id, "groups") or "gpt-5.4"

    max_order = max((ws.skill_order for ws in group_skills), default=0)

    judge_exec = Execution(
        account_id=wf_exec.account_id,
        skill_id=None,
        workflow_execution_id=wf_exec.id,
        workflow_skill_id=None,
        skill_order=max_order,
        input_data=json.dumps(judge_input, ensure_ascii=False),
        status="pending_local",
        dispatch_mode="local",
        model_used=judge_model,
        enable_deep_think=True,
        output_format="txt",
        execution_role=ROLE_DEBATE_JUDGE,
        execution_group_id=group.id,
        executed_at=datetime.now(JST),
    )
    db.add(judge_exec)
    db.flush()
    db.commit()
    logger.info(f"WF {wf_exec.id}: judge launched for group {group.group_order}")
    return True


# ===========================================================================
# スーパーバイザー (Feature 3)
# ===========================================================================

def _launch_supervisor(db, wf_exec, group, workflow, structured_context, global_input):
    """グループ完了後にスーパーバイザーを起動"""
    supervisor_prompt_raw = group.supervisor_prompt
    if not supervisor_prompt_raw:
        return False

    sv_input = dict(global_input)
    sv_input["all_step_results"] = structured_context.get("all_step_results", [])
    sv_input["blackboard"] = structured_context.get("blackboard", {})
    sv_input["completed_group"] = group.group_name or f"Group {group.group_order}"
    sv_input["completed_group_order"] = group.group_order

    sv_model = group.supervisor_model or workflow.parent_model_type or "gpt-5.4"

    try:
        decrypted_prompt = encryption_service.decrypt(supervisor_prompt_raw)
    except Exception:
        decrypted_prompt = supervisor_prompt_raw

    group_skills = (
        db.query(WorkflowSkill)
        .filter(WorkflowSkill.group_id == group.id)
        .all()
    )
    max_order = max((ws.skill_order for ws in group_skills), default=0)

    sv_exec = Execution(
        account_id=wf_exec.account_id,
        skill_id=None,
        workflow_execution_id=wf_exec.id,
        workflow_skill_id=None,
        skill_order=max_order,
        input_data=json.dumps(sv_input, ensure_ascii=False),
        status="pending_local",
        dispatch_mode="local",
        model_used=sv_model,
        enable_deep_think=True,
        output_format="txt",
        execution_role=ROLE_SUPERVISOR,
        execution_group_id=group.id,
        executed_at=datetime.now(JST),
    )
    db.add(sv_exec)
    db.flush()
    db.commit()
    logger.info(f"WF {wf_exec.id}: supervisor launched for group {group.group_order}")
    return True


def _handle_supervisor_result(db, wf_exec, sv_execution):
    """スーパーバイザー完了時の処理。action に基づきルーティング"""
    action = {"action": "continue"}
    if sv_execution.output_data:
        try:
            action = json.loads(sv_execution.output_data)
        except (json.JSONDecodeError, TypeError):
            pass

    act = action.get("action", "continue")
    logger.info(f"WF {wf_exec.id}: supervisor action={act}")

    if act == "stop":
        wf_exec.status = "error"
        wf_exec.error_message = f"Supervisor stopped: {action.get('reason', '')}"
        wf_exec.completed_at = datetime.now(JST)
        db.commit()
        return

    if act == "repeat":
        # 対象グループの全Executionをリセット → continue_workflow_execution が再起動する
        group_id = sv_execution.execution_group_id
        if group_id:
            group_execs = (
                db.query(Execution)
                .filter(
                    Execution.workflow_execution_id == wf_exec.id,
                    Execution.execution_role.is_(None),
                )
                .all()
            )
            group_skills = db.query(WorkflowSkill).filter(WorkflowSkill.group_id == group_id).all()
            group_ws_ids = {ws.id for ws in group_skills}
            for ex in group_execs:
                if ex.workflow_skill_id in group_ws_ids and ex.status == "success":
                    ex.status = "cancelled"
            db.commit()

    # "continue" or "goto" → 通常のWF継続
    continue_workflow_execution(wf_exec.id, sv_execution.skill_order)


# ===========================================================================
# 動的タスク分解 (Feature 4)
# ===========================================================================

def _handle_dynamic_group(db, wf_exec, group, structured_context, global_input, per_skill_input):
    """動的グループ: プランナースキルの出力からスキルを動的起動"""
    group_skills = (
        db.query(WorkflowSkill)
        .filter(WorkflowSkill.group_id == group.id)
        .order_by(WorkflowSkill.order_in_group.asc())
        .all()
    )
    if not group_skills:
        return False

    planner_ws = group_skills[0]
    planner_output = structured_context["steps"].get(str(planner_ws.id), {}).get("output")
    if not planner_output:
        return False

    plan = planner_output
    if isinstance(plan, str):
        try:
            plan = json.loads(plan)
        except (json.JSONDecodeError, TypeError):
            return False

    if not isinstance(plan, dict) or "steps" not in plan:
        return False

    wf_exec.dynamic_plan_data = json.dumps(plan, ensure_ascii=False)

    dynamic_steps = plan["steps"]
    exec_type = plan.get("execution_type", "serial")

    # 既に動的スキルが起動済みかチェック
    existing_dynamic = [
        ex for ex in wf_exec.executions
        if ex.workflow_skill_id is None
        and ex.execution_role is None
        and ex.skill_order is not None
        and ex.skill_order > planner_ws.skill_order
        and ex.execution_group_id == group.id
    ]

    if existing_dynamic:
        # 動的スキルが既に起動済み → 完了チェック
        pending = [ex for ex in existing_dynamic if ex.status in ("pending", "pending_local", "processing")]
        if pending:
            return True  # まだ実行中

        if exec_type == "serial":
            # 直列: 完了した数を数えて次を起動
            completed_count = sum(1 for ex in existing_dynamic if ex.status == "success")
            if completed_count < len(dynamic_steps):
                _launch_dynamic_skill(db, wf_exec, group, dynamic_steps[completed_count],
                                      completed_count, planner_ws, global_input, structured_context)
                return True
        # 全完了
        return False

    # 初回起動
    if exec_type == "parallel":
        # 並列: 全スキル同時起動
        for i, step in enumerate(dynamic_steps):
            _launch_dynamic_skill(db, wf_exec, group, step, i, planner_ws,
                                  global_input, structured_context)
    else:
        # 直列: 最初の1つだけ起動
        if dynamic_steps:
            _launch_dynamic_skill(db, wf_exec, group, dynamic_steps[0], 0,
                                  planner_ws, global_input, structured_context)

    wf_exec.status = "processing"
    db.flush()
    db.commit()
    logger.info(f"WF {wf_exec.id}: dynamic group launched ({exec_type})")
    return True


def _launch_dynamic_skill(db, wf_exec, group, step, index, planner_ws,
                          global_input, structured_context):
    """動的スキル1つを起動"""
    skill_id = step.get("skill_id")
    if not skill_id:
        return
    skill = db.query(Skill).filter(Skill.id == skill_id).first()
    if not skill:
        logger.warning(f"WF {wf_exec.id}: dynamic skill_id={skill_id} not found")
        return

    step_input = dict(global_input)
    step_input.update(step.get("input_overrides", {}))
    step_input["all_step_results"] = structured_context.get("all_step_results", [])
    step_input["blackboard"] = structured_context.get("blackboard", {})

    first_exec = wf_exec.executions[0] if wf_exec.executions else None
    execution = Execution(
        account_id=wf_exec.account_id,
        skill_id=skill.id,
        workflow_execution_id=wf_exec.id,
        workflow_skill_id=None,  # 動的スキルはWorkflowSkillに紐付かない
        skill_order=planner_ws.skill_order + index + 1,
        input_data=json.dumps(step_input, ensure_ascii=False),
        status="pending_local",
        dispatch_mode="local",
        model_used=skill.model_type,
        enable_deep_think=bool(getattr(skill, "enable_deep_think", True)),
        output_format=first_exec.output_format if first_exec else "txt",
        execution_group_id=group.id,  # グループに紐付けて追跡
        executed_at=datetime.now(JST),
    )
    db.add(execution)
    db.flush()
    db.commit()


# ===========================================================================
# 楽観ロック
# ===========================================================================

def _acquire_continuation_lock(db, wf_exec_id: int, current_version: int) -> bool:
    result = db.execute(
        update(WorkflowExecution)
        .where(
            WorkflowExecution.id == wf_exec_id,
            WorkflowExecution.continuation_lock_version == current_version,
        )
        .values(continuation_lock_version=current_version + 1)
    )
    db.flush()
    return result.rowcount > 0


# ===========================================================================
# メインエントリ
# ===========================================================================

def continue_workflow_execution(
    workflow_execution_id: int,
    completed_skill_order: int,
):
    db = SessionLocal()
    wf_exec = None
    try:
        wf_exec = db.query(WorkflowExecution).filter(
            WorkflowExecution.id == workflow_execution_id
        ).first()
        if not wf_exec:
            return
        if wf_exec.status in ("cancelled", "success", "error"):
            return

        if not _acquire_continuation_lock(db, wf_exec.id, wf_exec.continuation_lock_version):
            logger.info(f"WF {workflow_execution_id}: lock conflict, skipping")
            return

        workflow = db.query(Workflow).filter(Workflow.id == wf_exec.workflow_id).first()
        if not workflow:
            return

        groups = (
            db.query(WorkflowGroup)
            .filter(WorkflowGroup.workflow_id == workflow.id)
            .order_by(WorkflowGroup.group_order.asc())
            .all()
        )

        # 自動オーケストレーション: 構造からオーバーライドを計算
        all_ws = []
        all_skills_map = {}
        for g in groups:
            g_skills = (
                db.query(WorkflowSkill)
                .filter(WorkflowSkill.group_id == g.id)
                .order_by(WorkflowSkill.order_in_group.asc())
                .all()
            )
            all_ws.extend(g_skills)
            for ws in g_skills:
                if ws.skill_id and ws.skill_id not in all_skills_map:
                    from app.models import Skill as SkillModel
                    sk = db.query(SkillModel).filter(SkillModel.id == ws.skill_id).first()
                    if sk:
                        all_skills_map[ws.skill_id] = sk
        orch_overrides = compute_orchestration_overrides(workflow, groups, all_ws, all_skills_map)

        # Execution 収集
        all_executions = wf_exec.executions
        completed_skill_ids = set()
        skipped_skill_ids = set()
        error_skill_ids = {}
        completed_groups = set()  # ジャッジ/スーパーバイザー完了済みグループ

        for ex in all_executions:
            # 特殊ロール完了チェック（成功 or エラーでも完了扱い — 無限ループ防止）
            if ex.execution_role == ROLE_DEBATE_JUDGE and ex.status in ("success", "error"):
                if ex.execution_group_id:
                    completed_groups.add(("judge", ex.execution_group_id))
                    if ex.status == "error":
                        logger.warning(f"WF {workflow_execution_id}: judge for group {ex.execution_group_id} failed, skipping")
            if ex.execution_role == ROLE_SUPERVISOR and ex.status in ("success", "error"):
                if ex.execution_group_id:
                    completed_groups.add(("supervisor", ex.execution_group_id))
                    if ex.status == "error":
                        logger.warning(f"WF {workflow_execution_id}: supervisor for group {ex.execution_group_id} failed, skipping")

            if not ex.workflow_skill_id:
                continue
            if ex.execution_role:
                continue  # 特殊ロールはスキル完了扱いしない

            if ex.status == "success":
                completed_skill_ids.add(ex.workflow_skill_id)
            elif ex.status == "error":
                existing = error_skill_ids.get(ex.workflow_skill_id)
                if not existing or ex.id > existing.id:
                    error_skill_ids[ex.workflow_skill_id] = ex

        in_progress_ids = {
            ex.workflow_skill_id for ex in all_executions
            if ex.status in ("pending", "pending_local", "processing") and ex.workflow_skill_id
        }
        # 特殊ロールの進行中もチェック
        special_in_progress = any(
            ex.status in ("pending", "pending_local", "processing") and ex.execution_role
            for ex in all_executions
        )

        if special_in_progress:
            logger.info(f"WF {workflow_execution_id}: special role execution in progress, waiting")
            db.commit()
            return

        # グローバル入力
        global_input = {}
        if wf_exec.global_input_data:
            try:
                global_input = json.loads(wf_exec.global_input_data)
            except (json.JSONDecodeError, TypeError):
                pass

        per_skill_input = {}
        if getattr(wf_exec, 'per_skill_input_data', None):
            try:
                per_skill_input = json.loads(wf_exec.per_skill_input_data)
            except (json.JSONDecodeError, TypeError):
                pass

        structured_context = _build_structured_context(db, wf_exec, global_input, all_executions, orch_overrides)

        previous_output = ""
        prev_exec = (
            db.query(Execution)
            .filter(
                Execution.workflow_execution_id == workflow_execution_id,
                Execution.skill_order == completed_skill_order,
                Execution.status == "success",
                Execution.execution_role.is_(None),
            )
            .first()
        )
        if prev_exec and prev_exec.output_data:
            previous_output = prev_exec.output_data

        # --- グループ順次処理 ---
        for group in groups:
            group_skills = (
                db.query(WorkflowSkill)
                .filter(WorkflowSkill.group_id == group.id)
                .order_by(WorkflowSkill.order_in_group.asc())
                .all()
            )
            group_skill_ids = {s.id for s in group_skills}
            all_skills_done = group_skill_ids.issubset(completed_skill_ids | skipped_skill_ids)
            group_has_pending = bool(group_skill_ids & in_progress_ids)

            # --- 全スキル完了後のポスト処理 (Judge → Supervisor) ---
            if all_skills_done:
                # Feature 5: ジャッジ未実行?（自動オーバーライド対応）
                effective_judge_prompt = get_effective(group, "judge_prompt", orch_overrides, group.id, "groups")
                if effective_judge_prompt and ("judge", group.id) not in completed_groups:
                    judge_in_progress = any(
                        ex.execution_role == ROLE_DEBATE_JUDGE
                        and ex.execution_group_id == group.id
                        and ex.status in ("pending", "pending_local", "processing")
                        for ex in all_executions
                    )
                    if not judge_in_progress:
                        _launch_judge(db, wf_exec, group, structured_context, global_input, orch_overrides)
                        return
                    db.commit()
                    return

                # Feature 3: スーパーバイザー未実行?
                sv_mode = getattr(workflow, 'supervisor_mode', 'disabled') or 'disabled'
                should_run_sv = (
                    group.supervisor_prompt
                    and ("supervisor", group.id) not in completed_groups
                    and (sv_mode == "after_each_group" or sv_mode == "after_marked_groups")
                )
                if should_run_sv:
                    sv_in_progress = any(
                        ex.execution_role == ROLE_SUPERVISOR
                        and ex.execution_group_id == group.id
                        and ex.status in ("pending", "pending_local", "processing")
                        for ex in all_executions
                    )
                    if not sv_in_progress:
                        _launch_supervisor(db, wf_exec, group, workflow, structured_context, global_input)
                        return
                    db.commit()
                    return

                continue  # 次のグループへ

            if group_has_pending:
                db.commit()
                return

            # --- エラーリカバリ（自動オーバーライド対応） ---
            group_has_error = bool(group_skill_ids & set(error_skill_ids.keys()))
            if group_has_error:
                should_wait = False
                for ws in group_skills:
                    if ws.id not in error_skill_ids or ws.id in completed_skill_ids:
                        continue
                    failed_ex = error_skill_ids[ws.id]
                    on_error = get_effective(ws, "on_error", orch_overrides, ws.id, "workflow_skills") or "stop"
                    max_retries = get_effective(ws, "max_retries", orch_overrides, ws.id, "workflow_skills") or 0
                    if on_error == "retry" and failed_ex.retry_count < max_retries:
                        _retry_skill(db, wf_exec, ws, failed_ex, per_skill_input,
                                     structured_context, global_input, previous_output)
                        should_wait = True
                    elif on_error == "skip":
                        skipped_skill_ids.add(ws.id)
                        completed_skill_ids.add(ws.id)
                    else:
                        wf_exec.status = "error"
                        wf_exec.error_message = f"Step {ws.skill_order} ({ws.skill_name}) failed: {failed_ex.error_message}"
                        wf_exec.completed_at = datetime.now(JST)
                        db.commit()
                        return
                if should_wait:
                    db.commit()
                    return
                all_skills_done = group_skill_ids.issubset(completed_skill_ids | skipped_skill_ids)
                if all_skills_done:
                    continue

            # --- 条件分岐 ---
            if group.condition_expression:
                if not _evaluate_condition(group.condition_expression, structured_context):
                    if group.skip_on_condition_fail:
                        for ws in group_skills:
                            skipped_skill_ids.add(ws.id)
                            completed_skill_ids.add(ws.id)
                        continue
                    else:
                        wf_exec.status = "error"
                        wf_exec.error_message = f"Group {group.group_order} condition not met"
                        wf_exec.completed_at = datetime.now(JST)
                        db.commit()
                        return

            # --- Feature 4: 動的グループ (プランナー完了後) ---
            if group.dynamic_mode == "dynamic":
                planner_ws = group_skills[0] if group_skills else None
                if planner_ws and planner_ws.id in completed_skill_ids:
                    # プランナー完了 → 動的スキル起動/進行管理
                    still_running = _handle_dynamic_group(db, wf_exec, group, structured_context, global_input, per_skill_input)
                    if still_running:
                        return  # 動的スキルがまだ実行中
                    continue  # 動的スキル全完了 → 次のグループへ
                elif planner_ws and planner_ws.id not in completed_skill_ids:
                    if planner_ws.id not in in_progress_ids:
                        # プランナー未実行 → 起動
                        _launch_skills(db, wf_exec, [planner_ws], structured_context,
                                       global_input, previous_output, per_skill_input)
                    return

            # --- 通常スキル起動 ---
            if group.execution_type == "parallel":
                skills_to_launch = [s for s in group_skills if s.id not in completed_skill_ids and s.id not in skipped_skill_ids]
            else:
                skills_to_launch = []
                for s in group_skills:
                    if s.id not in completed_skill_ids and s.id not in skipped_skill_ids:
                        skills_to_launch = [s]
                        break

            if skills_to_launch:
                _launch_skills(db, wf_exec, skills_to_launch, structured_context,
                               global_input, previous_output, per_skill_input)
                return

        # 全グループ完了
        if in_progress_ids:
            db.commit()
            return

        _handle_workflow_completion(
            db, wf_exec, workflow, structured_context,
            global_input, previous_output, per_skill_input,
            completed_skill_order,
        )

    except Exception as e:
        logger.error(f"continue_workflow_execution error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        try:
            if wf_exec:
                db.rollback()
                wf_exec = db.query(WorkflowExecution).filter(
                    WorkflowExecution.id == workflow_execution_id
                ).first()
                if wf_exec:
                    wf_exec.status = "error"
                    wf_exec.error_message = str(e)
                    db.commit()
        except Exception:
            pass
    finally:
        db.close()


# ===========================================================================
# スキル起動
# ===========================================================================

def _launch_skills(db, wf_exec, skills, structured_context,
                   global_input, previous_output, per_skill_input):
    workflow = db.query(Workflow).filter(Workflow.id == wf_exec.workflow_id).first()
    launched_profiles = []
    try:
        for ws in skills:
            skill = db.query(Skill).filter(Skill.id == ws.skill_id).first()
            if not skill:
                continue
            deep_think = getattr(skill, "enable_deep_think", True)
            if deep_think is None:
                deep_think = True

            skill_input = _build_skill_input(
                ws, structured_context, global_input, previous_output,
                per_skill_input, structured_context.get("all_step_results", []),
            )
            agent_profile = _augment_skill_input_with_profile(
                skill_input, wf_exec, workflow, ws, skill, structured_context
            )
            launched_profiles.append(agent_profile)

            first_exec = wf_exec.executions[0] if wf_exec.executions else None
            execution = Execution(
                account_id=wf_exec.account_id,
                skill_id=skill.id,
                workflow_execution_id=wf_exec.id,
                workflow_skill_id=ws.id,
                skill_order=ws.skill_order,
                input_data=json.dumps(skill_input, ensure_ascii=False),
                status="pending_local",
                dispatch_mode="local",
                model_used=skill.model_type,
                agent_profile=agent_profile,
                enable_deep_think=bool(deep_think),
                output_format=first_exec.output_format if first_exec else "txt",
                executed_at=datetime.now(JST),
            )
            db.add(execution)

        distinct_profiles = {profile for profile in launched_profiles if profile}
        if len(distinct_profiles) > 1:
            raise RuntimeError("Parallel launch with mixed agent_profile is not supported in MVP")

        wf_exec.status = "processing"
        if skills:
            wf_exec.current_step = min((s.skill_order or 0) for s in skills)
        if launched_profiles:
            wf_exec.current_stage = launched_profiles[0]
            _set_handoff_target_profile(wf_exec, launched_profiles[0])
        db.flush()
        db.commit()
        logger.info(f"WF {wf_exec.id}: launched {len(skills)} skills")
    except Exception as e:
        db.rollback()
        raise RuntimeError(f"Failed to launch skills: {e}") from e

    _notify_next_steps(db, wf_exec, skills)


def _retry_skill(db, wf_exec, ws, failed_ex, per_skill_input,
                 structured_context, global_input, previous_output):
    workflow = db.query(Workflow).filter(Workflow.id == wf_exec.workflow_id).first()
    skill = db.query(Skill).filter(Skill.id == ws.skill_id).first()
    if not skill:
        return
    skill_input = _build_skill_input(
        ws, structured_context, global_input, previous_output,
        per_skill_input, structured_context.get("all_step_results", []),
    )
    agent_profile = _augment_skill_input_with_profile(
        skill_input, wf_exec, workflow, ws, skill, structured_context
    )
    execution = Execution(
        account_id=wf_exec.account_id,
        skill_id=skill.id,
        workflow_execution_id=wf_exec.id,
        workflow_skill_id=ws.id,
        skill_order=ws.skill_order,
        input_data=json.dumps(skill_input, ensure_ascii=False),
        status="pending_local",
        dispatch_mode="local",
        model_used=skill.model_type,
        agent_profile=agent_profile,
        enable_deep_think=bool(getattr(skill, "enable_deep_think", True)),
        output_format=failed_ex.output_format or "txt",
        retry_count=failed_ex.retry_count + 1,
        executed_at=datetime.now(JST),
    )
    db.add(execution)
    wf_exec.current_step = ws.skill_order
    wf_exec.current_stage = agent_profile
    _set_handoff_target_profile(wf_exec, agent_profile)
    db.flush()
    db.commit()
    logger.info(f"WF {wf_exec.id}: retry ws={ws.id} (attempt {execution.retry_count}/{ws.max_retries})")
    _notify_next_steps(db, wf_exec, [ws])


# ===========================================================================
# 親スキル / ワークフロー完了
# ===========================================================================

def _handle_workflow_completion(db, wf_exec, workflow, structured_context,
                                global_input, previous_output, per_skill_input,
                                completed_skill_order):
    _start_parent_skill(db, wf_exec, workflow, structured_context,
                        global_input, previous_output, completed_skill_order)


def _start_parent_skill(db, wf_exec, workflow, structured_context,
                        global_input, previous_output, completed_skill_order):
    parent_model = workflow.parent_model_type or "gpt-5.1"
    skill_order = completed_skill_order + 1

    merged_input = dict(global_input)
    if previous_output:
        merged_input["previous_output"] = previous_output
        merged_input["previous_step_result"] = previous_output
    merged_input["all_step_results"] = structured_context.get("all_step_results", [])
    merged_input["global_input_data"] = global_input
    merged_input["steps"] = structured_context.get("steps", {})
    merged_input["blackboard"] = structured_context.get("blackboard", {})
    merged_input["_ppt_agent_profile"] = "default"
    merged_input["_ppt_workflow_name"] = workflow.name or ""
    merged_input["_ppt_workflow_goal"] = workflow.description or ""
    merged_input["_ppt_handoff_context"] = _parse_json_text(getattr(wf_exec, "handoff_summary", None), {})
    merged_input["_ppt_blackboard_summary"] = {
        "keys": list((structured_context.get("blackboard") or {}).keys()),
        "count": len(structured_context.get("blackboard") or {}),
    }
    merged_input["_ppt_step_metadata"] = {
        "skill_order": skill_order,
        "skill_name": "親スキル",
        "agent_profile": "default",
        "readonly": False,
        "verdict_required": False,
        "handoff_refs": [],
    }
    merged_input["_ppt_handoff_refs"] = []

    first_exec = wf_exec.executions[0] if wf_exec.executions else None
    try:
        execution = Execution(
            account_id=wf_exec.account_id,
            skill_id=None,
            workflow_execution_id=wf_exec.id,
            workflow_skill_id=None,
            skill_order=skill_order,
            input_data=json.dumps(merged_input, ensure_ascii=False),
            status="pending_local",
            dispatch_mode="local",
            model_used=parent_model,
            agent_profile="default",
            enable_deep_think=bool(workflow.parent_enable_deep_think),
            output_format=first_exec.output_format if first_exec else "txt",
            executed_at=datetime.now(JST),
        )
        db.add(execution)
        wf_exec.status = "processing"
        wf_exec.current_step = skill_order
        wf_exec.current_stage = "default"
        wf_exec.total_steps = max(wf_exec.total_steps or 0, skill_order)
        _set_handoff_target_profile(wf_exec, "default")
        db.flush()
        db.commit()
    except Exception as e:
        db.rollback()
        raise RuntimeError(f"Failed to start parent skill: {e}") from e

    logger.info(f"WF {wf_exec.id}: parent skill launched (step={skill_order})")

    try:
        from app.services.redis_service import publish_workflow_next_step
        if first_exec:
            db.refresh(execution)
            prev = wf_exec.executions[-2] if len(wf_exec.executions) > 1 else first_exec
            publish_workflow_next_step(prev.id, {
                "next_execution_id": execution.id,
                "next_skill_order": skill_order,
                "skill_name": "親スキル",
                "workflow_name": workflow.name,
            })
    except Exception as e:
        logger.warning(f"Failed to notify parent step: {e}")


# ===========================================================================
# SSE 通知
# ===========================================================================

def _notify_next_steps(db, wf_exec, skills):
    try:
        from app.services.redis_service import publish_workflow_next_step
        for ws in skills:
            if wf_exec.executions:
                prev = wf_exec.executions[-1]
                db.expire_all()
                new_exec = (
                    db.query(Execution)
                    .filter(
                        Execution.workflow_skill_id == ws.id,
                        Execution.workflow_execution_id == wf_exec.id,
                    )
                    .order_by(Execution.id.desc())
                    .first()
                )
                if new_exec and prev:
                    publish_workflow_next_step(prev.id, {
                        "next_execution_id": new_exec.id,
                        "next_skill_order": ws.skill_order,
                        "skill_name": ws.skill_name or f"Step {ws.skill_order}",
                        "workflow_name": wf_exec.workflow.name if wf_exec.workflow else None,
                    })
    except Exception as e:
        logger.warning(f"Failed to notify next step: {e}")
