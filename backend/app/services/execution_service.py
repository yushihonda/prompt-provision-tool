import time
import logging
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def save_cancelled_execution(execution, execution_id: int, db: Session, start_time: float = None):
    """
    停止状態として実行ログを保存する共通関数

    Args:
        execution: Executionオブジェクト
        execution_id: 実行ID
        db: データベースセッション
        start_time: 開始時刻（実行時間を計算するため、Noneの場合は0）
    """
    execution.status = "cancelled"
    execution.error_message = "ユーザーによりキャンセルされました"

    # 実行時間を記録
    if start_time is not None:
        execution.execution_time = int((time.time() - start_time) * 1000)
    else:
        execution.execution_time = 0

    execution.tokens_used = 0
    execution.cost = 0.0  # キャンセル時は料金0
    execution.output_data = ""  # 出力データは空
    db.commit()
    logger.info(f"Execution {execution_id} saved as cancelled")
