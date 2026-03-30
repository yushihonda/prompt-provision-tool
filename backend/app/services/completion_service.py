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

from app.models import Account, Execution, WorkflowExecution
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

    # 親スキルステップ（workflow_skill_id=None）→ ワークフロー全体完了
    if execution.workflow_skill_id is None:
        try:
            wf_exec = db.query(WorkflowExecution).filter(
                WorkflowExecution.id == execution.workflow_execution_id
            ).first()
            if wf_exec:
                jst = timezone(timedelta(hours=9))
                wf_exec.status = "success"
                wf_exec.completed_at = datetime.now(jst)
                db.commit()
                logger.info(
                    f"WorkflowExecution {execution.workflow_execution_id} completed (parent skill step)"
                )
        except Exception as e:
            logger.error(f"Failed to complete workflow execution: {e}")
        return

    # 通常ステップ → ワークフロー継続（直接呼び出し）
    try:
        from app.tasks.execution_tasks import continue_workflow_execution
        continue_workflow_execution(
            execution.workflow_execution_id, execution.skill_order
        )
    except Exception as e:
        logger.error(f"Failed to continue workflow execution: {e}")
