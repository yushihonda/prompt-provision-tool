"""
既存の実行履歴から各アカウントの総トークン数と総料金を計算して更新するスクリプト
マイグレーション後に一度実行してください。
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app.database import SessionLocal
from app.models import Account, Execution
from sqlalchemy import func

def update_account_totals():
    """全アカウントの総トークン数と総料金を更新"""
    db = SessionLocal()
    try:
        accounts = db.query(Account).all()
        updated_count = 0
        
        for account in accounts:
            # このアカウントの全実行履歴から総計を計算
            executions = db.query(Execution).filter(Execution.account_id == account.id).all()
            
            total_tokens = sum((execution.tokens_used or 0) for execution in executions)
            total_cost = sum(float(execution.cost or 0) for execution in executions)
            
            # アカウントの総計を更新
            account.total_tokens = total_tokens
            account.total_cost = total_cost
            
            updated_count += 1
            print(f"Updated account {account.id} ({account.username}): tokens={total_tokens}, cost=${total_cost:.2f}")
        
        db.commit()
        print(f"\n完了: {updated_count}件のアカウントを更新しました")
        
    except Exception as e:
        db.rollback()
        print(f"エラーが発生しました: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    print("アカウントの総トークン数と総料金を更新しています...")
    update_account_totals()

