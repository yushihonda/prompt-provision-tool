"""
アカウント月次統計のリセット処理

user.py / admin.py / completion_service.py の3箇所で重複していたロジックを共通化。
"""
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from app.models import Account

# JST タイムゾーン
JST = timezone(timedelta(hours=9))


def get_current_month_start() -> datetime:
    """JSTでの現在月の開始日時を取得"""
    return datetime.now(JST).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def check_and_reset_monthly_stats(account: Account, db: Session) -> bool:
    """
    月が変わっていたらアカウントの月次カウンターをリセットする。

    Returns:
        True: リセットした, False: リセット不要
    """
    current_month = get_current_month_start()

    should_reset = False
    if account.last_month_reset is None:
        should_reset = True
    else:
        last_reset = account.last_month_reset
        if last_reset.tzinfo is None:
            last_reset = last_reset.replace(tzinfo=JST)
        if last_reset < current_month:
            should_reset = True

    if should_reset:
        account.tokens_this_month = 0
        account.cost_this_month = 0.0
        account.executions_this_month = 0
        account.last_month_reset = current_month
        db.commit()
        db.refresh(account)
        return True

    return False
