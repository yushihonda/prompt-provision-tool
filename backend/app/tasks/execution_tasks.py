"""
ワークフロー継続ロジック

Celery 廃止済み。通常関数として completion_service から直接呼ばれる。
グループベースのワークフロー実行を管理する。
"""
import json
import logging
from datetime import datetime, timezone, timedelta

from app.models import (
    Execution, Skill, Workflow, WorkflowSkill, WorkflowExecution, WorkflowGroup,
)
from app.database import SessionLocal
from app.encryption import encryption_service

logger = logging.getLogger(__name__)


def continue_workflow_execution(
    workflow_execution_id: int,
    completed_skill_order: int,
):
    """
    ワークフロー実行の次のステップを起動（グループベース）

    ロジック:
      1. 完了したスキルがどのグループに属するか判定
      2. そのグループの全スキルが完了したか確認
      3. 完了 → 次のグループのスキルを pending_local で作成
      4. 全グループ完了 → 親スキルを pending_local で作成
      5. 親スキル完了 → ワークフロー全体を success に
    """
    db = SessionLocal()
    try:
        wf_exec = db.query(WorkflowExecution).filter(
            WorkflowExecution.id == workflow_execution_id
        ).first()
        if not wf_exec:
            logger.error(f"WorkflowExecution {workflow_execution_id} not found")
            return
        if wf_exec.status == "cancelled":
            return

        workflow = db.query(Workflow).filter(Workflow.id == wf_exec.workflow_id).first()
        if not workflow:
            logger.error(f"Workflow {wf_exec.workflow_id} not found")
            return

        # 全グループ取得
        groups = (
            db.query(WorkflowGroup)
            .filter(WorkflowGroup.workflow_id == workflow.id)
            .order_by(WorkflowGroup.group_order.asc())
            .all()
        )

        # 完了済み Execution を収集
        all_executions = wf_exec.executions
        completed_skill_ids = set()
        completed_outputs = {}  # skill_id → output

        for ex in all_executions:
            if ex.status == "success" and ex.workflow_skill_id:
                completed_skill_ids.add(ex.workflow_skill_id)
                completed_outputs[ex.workflow_skill_id] = ex.output_data or ""

        in_progress_skill_ids = {
            ex.workflow_skill_id for ex in all_executions
            if ex.status in ("pending", "pending_local", "processing") and ex.workflow_skill_id
        }

        # グローバル入力
        global_input = {}
        if wf_exec.global_input_data:
            try:
                global_input = json.loads(wf_exec.global_input_data)
            except (json.JSONDecodeError, TypeError):
                pass

        # スキル個別入力
        per_skill_input = {}
        if getattr(wf_exec, 'per_skill_input_data', None):
            try:
                per_skill_input = json.loads(wf_exec.per_skill_input_data)
            except (json.JSONDecodeError, TypeError):
                pass

        # 全ステップ結果を構築
        all_step_results = []
        for ex in all_executions:
            if ex.status == "success" and ex.workflow_skill_id:
                raw = ex.output_data
                parsed = raw
                if raw:
                    try:
                        parsed = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        pass
                all_step_results.append({
                    "skill_order": ex.skill_order,
                    "workflow_skill_id": ex.workflow_skill_id,
                    "skill_id": ex.skill_id,
                    "output": parsed,
                })

        # 前ステップの出力
        previous_output = ""
        prev_exec = (
            db.query(Execution)
            .filter(
                Execution.workflow_execution_id == workflow_execution_id,
                Execution.skill_order == completed_skill_order,
                Execution.status == "success",
            )
            .first()
        )
        if prev_exec and prev_exec.output_data:
            previous_output = prev_exec.output_data

        # マージ入力構築
        merged_input = dict(global_input)
        if previous_output:
            merged_input["previous_output"] = previous_output
            merged_input["previous_step_result"] = previous_output
            if "research_data" not in merged_input:
                merged_input["research_data"] = previous_output
            if "analysis_result" not in merged_input:
                merged_input["analysis_result"] = previous_output
        merged_input["all_step_results"] = all_step_results
        merged_input.setdefault("global_input_data", global_input)

        # --- グループベース次ステップ判定 ---
        jst = timezone(timedelta(hours=9))

        for group in groups:
            group_skills = (
                db.query(WorkflowSkill)
                .filter(WorkflowSkill.group_id == group.id)
                .order_by(WorkflowSkill.order_in_group.asc())
                .all()
            )

            # このグループの全スキルが完了しているか
            group_skill_ids = {s.id for s in group_skills}
            group_completed = group_skill_ids.issubset(completed_skill_ids)
            group_has_pending = bool(group_skill_ids & in_progress_skill_ids)

            if group_completed:
                continue  # 次のグループへ

            if group_has_pending:
                # このグループにまだ実行中のスキルがある → 待機
                logger.info(f"WF {workflow_execution_id}: Group {group.group_order} has pending skills, waiting")
                return

            # このグループに未起動のスキルがある → 起動
            if group.execution_type == "parallel":
                # 並列: グループ内の未完了スキルを全て起動
                skills_to_launch = [s for s in group_skills if s.id not in completed_skill_ids]
            else:
                # 直列: グループ内の次の1つだけ起動
                skills_to_launch = []
                for s in group_skills:
                    if s.id not in completed_skill_ids:
                        skills_to_launch = [s]
                        break

            if skills_to_launch:
                _launch_skills(db, wf_exec, skills_to_launch, merged_input, jst)
                return

        # 全グループ完了 → 親スキル起動
        if in_progress_skill_ids:
            logger.info(f"WF {workflow_execution_id}: waiting for {len(in_progress_skill_ids)} in-progress skills")
            return

        _start_parent_skill(db, wf_exec, workflow, merged_input, completed_skill_order, jst)

    except Exception as e:
        logger.error(f"continue_workflow_execution error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        try:
            if wf_exec:
                wf_exec.status = "error"
                wf_exec.error_message = str(e)
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


def _launch_skills(db, wf_exec, skills, merged_input, jst):
    """スキル群を pending_local で作成"""
    # スキル個別入力を取得
    per_skill_input = {}
    if getattr(wf_exec, 'per_skill_input_data', None):
        try:
            per_skill_input = json.loads(wf_exec.per_skill_input_data)
        except (json.JSONDecodeError, TypeError):
            pass

    for ws in skills:
        skill = db.query(Skill).filter(Skill.id == ws.skill_id).first()
        if not skill:
            continue

        deep_think = getattr(skill, "enable_deep_think", True)
        if deep_think is None:
            deep_think = True

        # スキル個別入力をマージ（個別入力が優先）
        skill_input = dict(merged_input)
        skill_overrides = per_skill_input.get(str(ws.id), {})
        if skill_overrides:
            skill_input.update(skill_overrides)

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
            enable_deep_think=bool(deep_think),
            output_format=first_exec.output_format if first_exec else "txt",
            executed_at=datetime.now(jst),
        )
        db.add(execution)

    wf_exec.status = "processing"
    db.commit()
    logger.info(f"WF {wf_exec.id}: launched {len(skills)} skills as pending_local")

    # SSE 通知
    try:
        from app.services.redis_service import publish_workflow_next_step
        for ws in skills:
            if wf_exec.executions:
                prev = wf_exec.executions[-1]
                # refreshして最新のexecutionを取得
                db.expire_all()
                new_exec = (
                    db.query(Execution)
                    .filter(Execution.workflow_skill_id == ws.id, Execution.workflow_execution_id == wf_exec.id)
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


def _start_parent_skill(db, wf_exec, workflow, merged_input, completed_skill_order, jst):
    """親スキルを pending_local で作成"""

    # 親スキルコンテンツ取得（ワークフローに埋め込まれたもの）
    if workflow.encrypted_parent_content:
        parent_model = workflow.parent_model_type or "gpt-5.1"
    else:
        wf_exec.status = "error"
        wf_exec.error_message = "親スキルが設定されていません"
        wf_exec.completed_at = datetime.now(jst)
        db.commit()
        return

    skill_order = completed_skill_order + 1
    first_exec = wf_exec.executions[0] if wf_exec.executions else None

    execution = Execution(
        account_id=wf_exec.account_id,
        skill_id=None,  # 親スキルはワークフロー埋め込みのためスキルIDなし
        workflow_execution_id=wf_exec.id,
        workflow_skill_id=None,  # 親スキルはワークフロースキルではない
        skill_order=skill_order,
        input_data=json.dumps(merged_input, ensure_ascii=False),
        status="pending_local",
        dispatch_mode="local",
        model_used=parent_model,
        enable_deep_think=bool(workflow.parent_enable_deep_think),
        output_format=first_exec.output_format if first_exec else "txt",
        executed_at=datetime.now(jst),
    )
    db.add(execution)

    wf_exec.status = "processing"
    wf_exec.current_step = skill_order
    wf_exec.total_steps = max(wf_exec.total_steps or 0, skill_order)
    db.commit()

    logger.info(f"WF {wf_exec.id}: parent skill created as pending_local (step={skill_order})")

    # SSE 通知
    try:
        from app.services.redis_service import publish_workflow_next_step
        if first_exec:
            db.refresh(execution)
            prev = wf_exec.executions[-2] if len(wf_exec.executions) > 1 else first_exec
            publish_workflow_next_step(prev.id, {
                "next_execution_id": execution.id,
                "next_skill_order": skill_order,
                "skill_name": "統合（親スキル）",
                "workflow_name": workflow.name,
                "skill_name": "親スキル",
            })
    except Exception as e:
        logger.warning(f"Failed to notify parent step: {e}")
