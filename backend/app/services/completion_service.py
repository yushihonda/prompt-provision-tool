"""
実行完了の共通処理

Celery タスクパス / ローカルワーカー complete POST の両方から呼ばれる。
二重実装を防ぐため、課金・サニタイズ・ワークフロー継続ロジックを 1 箇所にまとめる。
"""
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Account, DailyExecutionCount, Execution, WorkflowExecution, WorkflowGroup
from app.utils.pricing import calculate_token_cost
from app.config import settings
from app.services.agent_profiles import detect_readonly_violation, extract_verdict, normalize_agent_profile

logger = logging.getLogger(__name__)


def _compute_overrides_for_step(db, execution) -> dict:
    """completion_service 内で使う軽量オーバーライド計算"""
    try:
        if not execution.workflow_execution_id:
            return {}
        wf_exec = db.query(WorkflowExecution).filter(
            WorkflowExecution.id == execution.workflow_execution_id
        ).first()
        if not wf_exec:
            return {}
        from app.models import Workflow, WorkflowGroup, WorkflowSkill, Skill
        workflow = db.query(Workflow).filter(Workflow.id == wf_exec.workflow_id).first()
        if not workflow:
            return {}
        groups = db.query(WorkflowGroup).filter(
            WorkflowGroup.workflow_id == workflow.id
        ).order_by(WorkflowGroup.group_order.asc()).all()
        all_ws = []
        all_skills_map = {}
        for g in groups:
            g_skills = db.query(WorkflowSkill).filter(
                WorkflowSkill.group_id == g.id
            ).order_by(WorkflowSkill.order_in_group.asc()).all()
            all_ws.extend(g_skills)
            for ws in g_skills:
                if ws.skill_id and ws.skill_id not in all_skills_map:
                    sk = db.query(Skill).filter(Skill.id == ws.skill_id).first()
                    if sk:
                        all_skills_map[ws.skill_id] = sk
        from app.services.auto_orchestration import compute_orchestration_overrides
        return compute_orchestration_overrides(workflow, groups, all_ws, all_skills_map)
    except Exception as e:
        logger.warning(f"Failed to compute orchestration overrides: {e}")
        return {}


def append_synthesis_event(wf_exec, event: dict) -> None:
    """synthesis_log に1件のイベントを追記する。"""
    from datetime import datetime, timezone
    events = []
    if wf_exec.synthesis_log:
        try:
            events = json.loads(wf_exec.synthesis_log)
        except (json.JSONDecodeError, TypeError):
            events = []
    event["timestamp"] = datetime.now(timezone.utc).isoformat()
    events.append(event)
    # 最大100件に制限
    if len(events) > 100:
        events = events[-100:]
    wf_exec.synthesis_log = json.dumps(events, ensure_ascii=False)


def _safe_json_loads(value, default=None):
    if value is None:
        return {} if default is None else default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {} if default is None else default


def _extract_structured_envelope(output: Optional[str]) -> Optional[dict]:
    """出力からstructured result envelopeを抽出（任意対応）。
    出力末尾の ```json ブロックまたはトップレベルJSONからsummary/key_pointsを探す。
    見つからなければNoneを返す。"""
    if not output:
        return None
    # まずトップレベルJSON
    parsed = _safe_json_loads(output, None)
    if isinstance(parsed, dict) and "summary" in parsed:
        return parsed
    # 末尾の```json...```ブロックを探す
    import re
    match = re.search(r'```json\s*\n(\{.*?\})\s*\n```', output, re.DOTALL)
    if match:
        try:
            candidate = json.loads(match.group(1))
            if isinstance(candidate, dict) and "summary" in candidate:
                return candidate
        except (json.JSONDecodeError, TypeError):
            pass
    return None


def _summarize_output(output: Optional[str]) -> str:
    if not output:
        return ""
    # structured envelope があればそれを優先
    envelope = _extract_structured_envelope(output)
    if envelope and envelope.get("summary"):
        return str(envelope["summary"])[:300]
    # フォールバック
    parsed = _safe_json_loads(output, None)
    if isinstance(parsed, dict):
        keys = list(parsed.keys())
        if not keys:
            return ""
        return f"出力キー: {', '.join(keys[:5])}"
    if isinstance(parsed, list):
        return f"{len(parsed)}件の結果"
    compact = str(output).strip().replace("\n", " ")
    return compact[:200]


def _persist_workflow_metadata(db: Session, execution: Execution) -> None:
    if not execution.workflow_execution_id:
        return
    wf_exec = db.query(WorkflowExecution).filter(WorkflowExecution.id == execution.workflow_execution_id).first()
    if not wf_exec:
        return

    profile = normalize_agent_profile(getattr(execution, "agent_profile", None))
    wf_exec.current_stage = profile
    if profile == "verification":
        if execution.status == "success":
            verdict = extract_verdict(execution.output_data)
            wf_exec.final_verdict = verdict or "FAIL"
        else:
            wf_exec.final_verdict = "FAIL"

    handoff_refs = []
    parsed_input = _safe_json_loads(getattr(execution, "input_data", None), {})
    raw_refs = parsed_input.get("_nexmagi_handoff_refs") if isinstance(parsed_input, dict) else None
    if isinstance(raw_refs, list):
        handoff_refs = [str(ref) for ref in raw_refs if ref]

    blackboard = _safe_json_loads(getattr(wf_exec, "blackboard_data", None), {})
    summary_source = execution.output_data if execution.status == "success" else (execution.error_message or execution.output_data)
    envelope = _extract_structured_envelope(execution.output_data) if execution.status == "success" else None
    handoff_data = {
        "schema_version": 1,
        "from_profile": profile,
        # to_profile は次 step の launch 時に _set_handoff_target_profile() が補完する。
        "to_profile": None,
        "source_execution_id": execution.id,
        "summary": _summarize_output(summary_source),
        "blackboard_refs": handoff_refs,
        "important_counts": {
            "blackboard_keys": len(handoff_refs),
        },
        "display_verdict": getattr(wf_exec, "final_verdict", None),
    }
    # structured envelope があれば key_points と next_action_hint を含める
    if envelope:
        if envelope.get("key_points"):
            handoff_data["key_points"] = envelope["key_points"][:10]
        if envelope.get("next_action_hint"):
            handoff_data["next_action_hint"] = str(envelope["next_action_hint"])[:200]
    wf_exec.handoff_summary = json.dumps(handoff_data, ensure_ascii=False)

    # synthesis event をDBに記録
    role = getattr(execution, "execution_role", None)
    step_name = getattr(execution, "skill_name", None) or role or f"Step {execution.skill_order}"
    output_len = len(execution.output_data) if execution.output_data else 0
    event = {
        "execution_id": execution.id,
        "stage": profile,
        "step_name": step_name,
    }
    if execution.status == "success":
        if role == "debate_judge":
            event["event_type"] = "judge_complete"
            event["summary"] = "並列グループの結果を合議・統合完了"
        elif role == "supervisor":
            event["event_type"] = "supervisor_decision"
            event["summary"] = "スーパーバイザーが進行判断を完了"
        elif role == "quality_gate":
            event["event_type"] = "quality_gate_pass"
            event["summary"] = "品質ゲートを通過"
        elif not execution.workflow_skill_id:
            event["event_type"] = "leader_complete"
            event["summary"] = "全結果を統合して最終出力を生成"
        else:
            event["event_type"] = "step_complete"
            event["summary"] = f"{step_name}が完了（{output_len}文字）"
        if getattr(execution, "reflection_loop", 0) > 0:
            event["summary"] += f"（再実行{execution.reflection_loop}回目）"
    else:
        event["event_type"] = f"{role}_error" if role else "step_error"
        event["summary"] = execution.error_message or "エラーが発生"
    append_synthesis_event(wf_exec, event)

    # CoordinatorEvent 発火 (review / judge / completion を観測層に流す)
    try:
        from app.services.coordinator_service import (
            get_plan_by_workflow_execution,
            record_event,
            EVENT_JUDGE_DECISION_MADE,
            EVENT_REVIEW_REQUESTED,
            EVENT_TASK_FINISHED,
            EVENT_RUN_COMPLETED,
        )
        plan = get_plan_by_workflow_execution(db, wf_exec.id)
        if plan:
            etype = event.get("event_type", "")
            task_id = f"task_{execution.workflow_skill_id}" if execution.workflow_skill_id else f"exec_{execution.id}"
            payload = {
                "execution_id": execution.id,
                "stage": profile,
                "step_name": step_name,
                "summary": event.get("summary"),
            }
            if etype in ("judge_complete", "supervisor_decision"):
                record_event(db, plan.plan_id, EVENT_JUDGE_DECISION_MADE, task_id=task_id, payload=payload)
            elif etype == "quality_gate_pass":
                record_event(db, plan.plan_id, EVENT_REVIEW_REQUESTED, task_id=task_id, payload={**payload, "result": "pass"})
            elif etype == "leader_complete":
                record_event(db, plan.plan_id, EVENT_RUN_COMPLETED, payload=payload)
            elif etype.endswith("_error"):
                record_event(db, plan.plan_id, EVENT_TASK_FINISHED, task_id=task_id, payload={**payload, "status": "error"})
    except Exception as _e:
        logger.warning(f"CoordinatorEvent dispatch failed: {_e}")

    # 永続メモリ更新（成功時、通常スキルのみ）
    if execution.status == "success" and not role and execution.workflow_skill_id:
        try:
            from app.services.memory_service import update_memory
            summary_for_mem = _summarize_output(execution.output_data)
            if summary_for_mem:
                update_memory(db, wf_exec.workflow_id, profile, f"[{step_name}] {summary_for_mem}")
        except Exception as e:
            logger.warning(f"Failed to update memory: {e}")

    db.commit()


def build_external_cli_provenance(external_cli_meta: dict) -> dict:
    """Convert sidecar/Rust-side `external_cli_meta` into the artifact
    provenance shape persisted onto CoordinatorArtifact.extra_metadata.

    This is a pure function — exposed at module top level so it can be
    unit tested without spinning up an Execution / Workflow / Plan
    graph.
    """
    return {
        "step_execution_kind": "external_cli",  # Phase 4.5: unified base key
        "execution_kind": "external_cli",
        "adapter_type": "external_cli",
        "adapter_id": external_cli_meta.get("adapter_id"),
        "adapter_name": external_cli_meta.get("adapter_name"),
        "runtime": external_cli_meta.get("runtime"),
        "selection_reason": external_cli_meta.get("selection_reason"),
        "approval_policy": external_cli_meta.get("approval_policy"),
        "cwd": external_cli_meta.get("cwd"),
        "command": external_cli_meta.get("command"),
        "command_line_preview": external_cli_meta.get("command_line_preview"),
        "cli_status": external_cli_meta.get("status"),
        "exit_code": external_cli_meta.get("exit_code"),
        "duration_ms": external_cli_meta.get("duration_ms"),
        "stdout_truncated": external_cli_meta.get("stdout_truncated"),
        "stderr_truncated": external_cli_meta.get("stderr_truncated"),
        "changed_files": external_cli_meta.get("changed_files") or [],
        "changed_files_count": len(external_cli_meta.get("changed_files") or []),
        "capability_check_passed": external_cli_meta.get("capability_check_passed"),
        "allow_writes": external_cli_meta.get("allow_writes"),
        "allow_shell": external_cli_meta.get("allow_shell"),
        "required_capabilities": external_cli_meta.get("required_capabilities") or [],
        "workspace_id": external_cli_meta.get("workspace_id"),
        "workspace_mode": external_cli_meta.get("workspace_mode"),
        "workspace_path": external_cli_meta.get("workspace_path"),
    }


def build_http_provider_provenance(provider_meta: dict) -> dict:
    """Phase 4.5: complement to build_external_cli_provenance for the
    HTTP/internal provider path. Returns the unified base keys so a
    single artifact reader can render either runtime kind.

    `provider_meta` here is the existing dict produced by
    `_run_with_runtime_fallback` plus whatever the planner attached.
    """
    return {
        "step_execution_kind": "http_provider",
        "execution_kind": "http_provider",
        "adapter_type": "http_provider",
        "adapter_id": provider_meta.get("actual_adapter_id")
        or provider_meta.get("selected_adapter_id"),
        "adapter_name": provider_meta.get("actual_adapter_name")
        or provider_meta.get("selected_adapter_name"),
        "runtime": provider_meta.get("actual_provider_mode")
        or provider_meta.get("selected_provider_mode"),
        "selection_reason": provider_meta.get("provider_selection_reason"),
        "selected_provider_mode": provider_meta.get("selected_provider_mode"),
        "actual_provider_mode": provider_meta.get("actual_provider_mode"),
        "fallback_applied": provider_meta.get("fallback_applied", False),
        "fallback_from_adapter_id": provider_meta.get("fallback_from_adapter_id"),
        "fallback_to_adapter_id": provider_meta.get("fallback_to_adapter_id"),
        "fallback_reason": provider_meta.get("fallback_reason"),
        "provider_attempt_count": provider_meta.get("provider_attempt_count", 1),
        "preflight_status": provider_meta.get("preflight_status"),
        "local_error_reason": provider_meta.get("local_error_reason"),
        "local_model_requested": provider_meta.get("local_model_requested"),
    }


def finalize_execution(
    db: Session,
    execution: Execution,
    output: str,
    model_used: str,
    tokens_used: int,
    execution_time_ms: int,
    status_result: str = "success",
    error_message: Optional[str] = None,
    template_text: Optional[str] = None,
    provider_meta: Optional[dict] = None,
    external_cli_meta: Optional[dict] = None,
) -> None:
    """
    実行結果を DB に保存し、アカウント集計を更新する。

    Args:
        db: DB セッション
        execution: 対象の Execution レコード（refresh 済みを想定）
        output: AI 出力テキスト
        model_used: 使用モデル名
        tokens_used: 使用トークン数
        execution_time_ms: 実行時間（ミリ秒）
        status_result: ステータス (success / error)
        error_message: エラーメッセージ（error 時）
        template_text: サニタイズ用テンプレ（サーバー実行時のみ渡す）
    """
    from app.utils.skill_utils import sanitize_output

    # サニタイズ（テンプレートが渡された場合のみ）
    if status_result == "success" and template_text:
        try:
            output = sanitize_output(
                output_text=output,
                template_text=template_text,
                min_match_len=settings.SANITIZE_MIN_MATCH_LEN,
                similarity_threshold=settings.SANITIZE_SIMILARITY_THRESHOLD,
            )
        except Exception as e:
            logger.warning(f"Sanitize output failed for execution {execution.id}: {e}")

    profile = normalize_agent_profile(getattr(execution, "agent_profile", None))
    if status_result == "success" and profile in {"explore", "plan"}:
        violation = detect_readonly_violation(output)
        if violation:
            status_result = "error"
            error_message = violation
            logger.warning(f"Readonly enforcement rejected execution {execution.id}: {violation}")

    execution.output_data = output
    execution.model_used = model_used
    execution.tokens_used = tokens_used
    execution.execution_time = execution_time_ms
    execution.status = status_result
    execution.error_message = error_message

    # 料金計算
    if tokens_used and tokens_used > 0 and model_used:
        execution.cost = calculate_token_cost(model_used, tokens_used)
    else:
        execution.cost = 0.0

    # アカウント集計更新
    _update_account_stats(db, execution, status_result, tokens_used)

    db.commit()
    logger.info(
        f"Execution {execution.id} finalized: status={status_result}, "
        f"tokens={tokens_used}, cost={execution.cost}"
    )

    # CoordinatorArtifact 生成 (成功した execution の出力を構造化保存)
    if status_result == "success" and execution.workflow_execution_id:
        try:
            _record_coordinator_artifact(
                db, execution, output, model_used,
                provider_meta=provider_meta,
                external_cli_meta=external_cli_meta,
            )
        except Exception as e:
            logger.warning(f"CoordinatorArtifact recording failed for execution {execution.id}: {e}")


def _record_coordinator_artifact(
    db: Session,
    execution: Execution,
    output: str,
    model_used: str,
    *,
    provider_meta: Optional[dict] = None,
    external_cli_meta: Optional[dict] = None,
) -> None:
    """成功したExecutionに対応するCoordinatorArtifactを生成する.

    provider_meta が渡された場合 (sidecar 実行結果由来) はそれをそのまま記録する。
    渡されない場合は legacy 経路 — routing を再評価して selected 情報を埋める。
    legacy 経路は execution result から actual を取れない過渡期のためだけに残す。
    TODO: legacy 経路は将来的に削除する。
    """
    from app.services.coordinator_service import (
        get_plan_by_workflow_execution,
        record_artifact,
        record_event,
        map_profile_to_role,
        default_artifact_type_for_role,
        find_worker_for_task,
        update_worker_status,
        WORKER_DONE,
        EVENT_TASK_FINISHED,
    )
    plan = get_plan_by_workflow_execution(db, execution.workflow_execution_id)
    if not plan:
        return

    profile = (execution.agent_profile or "default").lower()
    role = map_profile_to_role(profile)
    artifact_type = default_artifact_type_for_role(role)
    task_id = f"task_{execution.workflow_skill_id}" if execution.workflow_skill_id else f"exec_{execution.id}"

    summary = (output or "")[:200] if output else None

    # Build provider provenance metadata. Prefer the actual provider info
    # returned by the execution result over re-running routing logic.
    provenance: dict = {}
    routing_provider_mode: Optional[str] = None
    if provider_meta:
        # Authoritative path: use what actually executed.
        provenance.update(
            {
                "selected_provider_mode": provider_meta.get("selected_provider_mode"),
                "selected_adapter_id": provider_meta.get("selected_adapter_id"),
                "selected_adapter_name": provider_meta.get("selected_adapter_name"),
                "selected_model": provider_meta.get("selected_model"),
                "selected_base_url": provider_meta.get("selected_base_url"),
                "provider_selection_reason": provider_meta.get("provider_selection_reason"),
                "actual_provider_mode": provider_meta.get("actual_provider_mode"),
                "actual_adapter_id": provider_meta.get("actual_adapter_id"),
                "actual_adapter_name": provider_meta.get("actual_adapter_name"),
                "actual_model": provider_meta.get("actual_model"),
                "actual_base_url": provider_meta.get("actual_base_url"),
                "actual_transport": provider_meta.get("actual_transport"),
                "fallback_applied": provider_meta.get("fallback_applied", False),
                "fallback_from_adapter_id": provider_meta.get("fallback_from_adapter_id"),
                "fallback_to_adapter_id": provider_meta.get("fallback_to_adapter_id"),
                "fallback_reason": provider_meta.get("fallback_reason"),
                "provider_attempt_count": provider_meta.get("provider_attempt_count", 1),
                "preflight_status": provider_meta.get("preflight_status"),
                "local_error_reason": provider_meta.get("local_error_reason"),
                "local_model_requested": provider_meta.get("local_model_requested"),
            }
        )
        routing_provider_mode = provider_meta.get("actual_provider_mode")
        logger.info(
            "artifact_recorded execution_id=%s actual_adapter=%s fallback_applied=%s",
            execution.id,
            provider_meta.get("actual_adapter_name"),
            provider_meta.get("fallback_applied"),
        )
    else:
        # Legacy path: no execution-result provenance available. Re-run routing
        # to at least populate selected_*. Marked legacy on purpose.
        # TODO: remove once all provider paths emit provider_meta.
        try:
            if execution.workflow_skill_id:
                from app.services.coordinator_service import resolve_execution_provider
                try:
                    plan_tasks = json.loads(plan.tasks or "[]")
                except (json.JSONDecodeError, TypeError):
                    plan_tasks = []
                matched_task = next(
                    (
                        t for t in plan_tasks
                        if t.get("workflow_skill_id") == execution.workflow_skill_id
                    ),
                    None,
                )
                if matched_task:
                    routing = resolve_execution_provider(
                        db, plan, matched_task,
                        retry_count=int(getattr(execution, "retry_count", 0) or 0),
                    )
                    routing_provider_mode = routing.get("provider_mode")
                    provenance.update(
                        {
                            "selected_provider_mode": routing.get("provider_mode"),
                            "selected_adapter_id": routing.get("adapter_id"),
                            "selected_adapter_name": routing.get("adapter_name"),
                            "provider_selection_reason": routing.get("selection_reason"),
                            "fallback_applied": routing.get("fallback_occurred", False),
                            "legacy_metadata_path": True,
                        }
                    )
                    payload = routing.get("provider_payload") or {}
                    if payload:
                        provenance["selected_base_url"] = payload.get("base_url")
                        provenance["selected_model"] = payload.get("model")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "legacy provider routing metadata skipped for execution %s: %s",
                execution.id, exc,
            )

    # Phase 3.6: external CLI provenance (Claude / Codex / Cursor / Generic).
    if external_cli_meta:
        provenance.update(build_external_cli_provenance(external_cli_meta))
        logger.info(
            "external_cli_artifact_recorded execution_id=%s adapter=%s runtime=%s status=%s",
            execution.id,
            external_cli_meta.get("adapter_name"),
            external_cli_meta.get("runtime"),
            external_cli_meta.get("status"),
        )

    # Task / workflow context for traceability (task_id was already computed above).
    extra_metadata = {
        "agent_profile": profile,
        "skill_order": execution.skill_order,
        "task_role": role,
        "task_id": task_id,
        "workflow_run_id": execution.workflow_execution_id,
    }
    extra_metadata.update(provenance)

    artifact = record_artifact(
        db, plan.plan_id, task_id, role, artifact_type,
        execution_id=execution.id,
        summary=summary,
        inline_content=output,
        provider_mode=routing_provider_mode,
        model_hint=model_used,
        extra_metadata=extra_metadata,
    )
    record_event(
        db, plan.plan_id, EVENT_TASK_FINISHED,
        task_id=task_id,
        payload={"status": "success", "execution_id": execution.id, "model": model_used},
    )

    # 担当 named worker の状態を done に遷移し、artifact_refs を追加
    try:
        worker = find_worker_for_task(db, plan.plan_id, task_id)
        if worker:
            update_worker_status(db, worker.worker_id, WORKER_DONE,
                                 current_task_id=task_id,
                                 artifact_id=artifact.artifact_id)
    except Exception as _e:
        logger.warning(f"Worker status update failed for task {task_id}: {_e}")


def _update_account_stats(
    db: Session,
    execution: Execution,
    status_result: str,
    tokens_used: int,
) -> None:
    """アカウントの集計情報を更新"""
    if status_result not in ("success", "error", "cancelled"):
        return

    account = db.query(Account).filter(Account.id == execution.account_id).first()
    if not account:
        return

    from app.services.account_stats import check_and_reset_monthly_stats
    if check_and_reset_monthly_stats(account, db):
        logger.info(f"Account {account.id}: Month changed, resetting monthly totals")

    # 実行回数
    account.executions_this_month = (account.executions_this_month or 0) + 1
    account.total_executions = (account.total_executions or 0) + 1

    # 日別実行回数（コントリビューショングラフ用）
    jst = timezone(timedelta(hours=9))
    today = datetime.now(jst).date()
    daily_count = db.query(DailyExecutionCount).filter(
        DailyExecutionCount.account_id == account.id,
        DailyExecutionCount.date == today,
    ).first()
    if daily_count:
        daily_count.count += 1
    else:
        daily_count = DailyExecutionCount(
            account_id=account.id,
            date=today,
            count=1,
        )
        db.add(daily_count)

    # トークン・料金（成功時のみ）
    if status_result == "success" and tokens_used and tokens_used > 0:
        old_total_cost = float(account.total_cost or 0.0)
        old_cost_this_month = float(account.cost_this_month or 0.0)
        account.total_tokens = (account.total_tokens or 0) + tokens_used
        account.total_cost = old_total_cost + float(execution.cost or 0.0)
        account.tokens_this_month = (account.tokens_this_month or 0) + tokens_used
        account.cost_this_month = old_cost_this_month + float(execution.cost or 0.0)


def trigger_workflow_continuation(
    execution: Execution,
    db: Session,
) -> None:
    """
    ワークフロー実行の場合、次ステップを起動する。
    Celery タスクとローカル完了の両方から呼ばれる。
    """
    if not execution.workflow_execution_id:
        return

    role = getattr(execution, 'execution_role', None)

    # --- 品質ゲート完了 (Feature 1) ---
    if role == "quality_gate":
        try:
            from app.tasks.execution_tasks import _handle_quality_gate_result
            wf_exec = db.query(WorkflowExecution).filter(
                WorkflowExecution.id == execution.workflow_execution_id
            ).first()
            if wf_exec:
                _handle_quality_gate_result(db, wf_exec, execution)
        except Exception as e:
            logger.error(f"Failed to handle quality gate result: {e}")
            try:
                db.rollback()
            except Exception:
                pass
        return

    # --- スーパーバイザー完了 (Feature 3) ---
    if role == "supervisor":
        try:
            from app.tasks.execution_tasks import _handle_supervisor_result
            wf_exec = db.query(WorkflowExecution).filter(
                WorkflowExecution.id == execution.workflow_execution_id
            ).first()
            if wf_exec:
                _handle_supervisor_result(db, wf_exec, execution)
        except Exception as e:
            logger.error(f"Failed to handle supervisor result: {e}")
            try:
                db.rollback()
            except Exception:
                pass
        return

    # --- ジャッジ完了 (Feature 5) → ジャッジ出力をBlackboardに保存して通常継続 ---
    if role == "debate_judge":
        try:
            wf_exec = db.query(WorkflowExecution).filter(
                WorkflowExecution.id == execution.workflow_execution_id
            ).first()
            if wf_exec and execution.status == "success" and execution.execution_group_id:
                from app.tasks.execution_tasks import _merge_blackboard
                group = db.query(WorkflowGroup).filter(WorkflowGroup.id == execution.execution_group_id).first()
                bb_key = f"judge_{group.group_name or group.group_order}" if group else "judge_result"
                parsed = execution.output_data
                try:
                    parsed = json.loads(execution.output_data)
                except (json.JSONDecodeError, TypeError):
                    pass
                _merge_blackboard(db, wf_exec, bb_key, parsed)
                db.commit()
        except Exception as e:
            logger.error(f"Failed to handle judge result: {e}")
            try:
                db.rollback()
            except Exception:
                pass
        # ジャッジ後は通常のWF継続
        try:
            from app.tasks.execution_tasks import continue_workflow_execution
            continue_workflow_execution(execution.workflow_execution_id, execution.skill_order)
        except Exception as e:
            logger.error(f"Failed to continue after judge: {e}")
        return

    # --- 親スキルステップ（workflow_skill_id=None, role=None）→ ワークフロー全体完了 ---
    if execution.workflow_skill_id is None:
        try:
            wf_exec = db.query(WorkflowExecution).filter(
                WorkflowExecution.id == execution.workflow_execution_id
            ).first()
            if wf_exec:
                jst = timezone(timedelta(hours=9))
                if execution.status == "success":
                    wf_exec.status = "success"
                else:
                    wf_exec.status = "error"
                    wf_exec.error_message = f"親スキル実行エラー: {execution.error_message or 'unknown'}"
                wf_exec.completed_at = datetime.now(jst)
                db.commit()
                logger.info(
                    f"WorkflowExecution {execution.workflow_execution_id} "
                    f"{'completed' if execution.status == 'success' else 'failed'} (parent skill step)"
                )
        except Exception as e:
            logger.error(f"Failed to complete workflow execution: {e}")
        return

    # --- 通常スキル完了 ---
    # 自動オーケストレーションのオーバーライドを計算
    orch_overrides = _compute_overrides_for_step(db, execution)

    # Blackboard自動書き込み (Feature 2: output_keyがあれば自動でBBに書く)
    try:
        wf_exec = db.query(WorkflowExecution).filter(
            WorkflowExecution.id == execution.workflow_execution_id
        ).first()
        if wf_exec and execution.status == "success":
            from app.tasks.execution_tasks import _auto_write_blackboard
            _auto_write_blackboard(db, wf_exec, execution, orch_overrides)
            db.commit()
    except Exception as e:
        logger.warning(f"Blackboard auto-write failed: {e}")
        try:
            db.rollback()
        except Exception:
            pass

    # 品質ゲートチェック (Feature 1 — 自動オーバーライド対応)
    if execution.status == "success" and execution.workflow_skill_id:
        try:
            from app.models import WorkflowSkill as WS
            from app.services.auto_orchestration import get_effective
            ws = db.query(WS).filter(WS.id == execution.workflow_skill_id).first()
            if ws:
                eff_gate_type = get_effective(ws, "quality_gate_type", orch_overrides, ws.id, "workflow_skills") or "disabled"
                eff_max_loops = get_effective(ws, "max_reflection_loops", orch_overrides, ws.id, "workflow_skills") or 0
                eff_gate_prompt = get_effective(ws, "quality_gate_prompt", orch_overrides, ws.id, "workflow_skills")

                if eff_gate_type != "disabled" and eff_gate_prompt:
                    can_reflect = eff_max_loops > 0 and execution.reflection_loop < eff_max_loops

                    if eff_gate_type == "llm":
                        if can_reflect:
                            from app.tasks.execution_tasks import _launch_quality_gate_llm
                            _launch_quality_gate_llm(db, wf_exec, ws, execution)
                            return
                    else:
                        # inline品質ゲート (regex/json_schema — 自動はregex)
                        from app.tasks.execution_tasks import _check_quality_gate_inline
                        verdict = _check_quality_gate_inline(ws, execution.output_data or "", orch_overrides)
                        if not verdict["pass"]:
                            if can_reflect:
                                from types import SimpleNamespace
                                from app.tasks.execution_tasks import _handle_quality_gate_result
                                gate_result_data = json.dumps(verdict, ensure_ascii=False)
                                gate_result = SimpleNamespace(
                                    output_data=gate_result_data,
                                    workflow_skill_id=ws.id,
                                    reflection_loop=execution.reflection_loop,
                                    skill_order=execution.skill_order,
                                )
                                _handle_quality_gate_result(db, wf_exec, gate_result)
                                return
                            else:
                                logger.warning(
                                    f"Quality gate failed for ws={ws.id} but max_reflection_loops=0, proceeding. "
                                    f"Critique: {verdict.get('critique', '')}"
                                )
        except Exception as e:
            logger.warning(f"Quality gate check failed: {e}")

    try:
        _persist_workflow_metadata(db, execution)
    except Exception as e:
        logger.warning(f"Workflow metadata persistence failed: {e}")
        try:
            db.rollback()
        except Exception:
            pass

    # 通常のWF継続
    try:
        from app.tasks.execution_tasks import continue_workflow_execution
        continue_workflow_execution(
            execution.workflow_execution_id, execution.skill_order
        )
    except Exception as e:
        logger.error(f"Failed to continue workflow execution: {e}")
