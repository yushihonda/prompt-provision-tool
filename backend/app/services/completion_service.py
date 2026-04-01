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

logger = logging.getLogger(__name__)


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
    # Blackboard自動書き込み (Feature 2: output_keyがあれば自動でBBに書く)
    try:
        wf_exec = db.query(WorkflowExecution).filter(
            WorkflowExecution.id == execution.workflow_execution_id
        ).first()
        if wf_exec and execution.status == "success":
            from app.tasks.execution_tasks import _auto_write_blackboard
            _auto_write_blackboard(db, wf_exec, execution)
            db.commit()
    except Exception as e:
        logger.warning(f"Blackboard auto-write failed: {e}")
        try:
            db.rollback()
        except Exception:
            pass

    # 品質ゲートチェック (Feature 1)
    if execution.status == "success" and execution.workflow_skill_id:
        try:
            from app.models import WorkflowSkill as WS
            ws = db.query(WS).filter(WS.id == execution.workflow_skill_id).first()
            if ws and ws.quality_gate_type and ws.quality_gate_type != "disabled":
                can_reflect = ws.max_reflection_loops > 0 and execution.reflection_loop < ws.max_reflection_loops

                if ws.quality_gate_type == "llm":
                    if can_reflect:
                        from app.tasks.execution_tasks import _launch_quality_gate_llm
                        _launch_quality_gate_llm(db, wf_exec, ws, execution)
                        return
                else:
                    # inline品質ゲート (regex/json_schema)
                    from app.tasks.execution_tasks import _check_quality_gate_inline
                    verdict = _check_quality_gate_inline(ws, execution.output_data or "")
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

    # 通常のWF継続
    try:
        from app.tasks.execution_tasks import continue_workflow_execution
        continue_workflow_execution(
            execution.workflow_execution_id, execution.skill_order
        )
    except Exception as e:
        logger.error(f"Failed to continue workflow execution: {e}")
