"""
古い実行履歴の料金を計算して更新し、アカウントの今月の集計を再計算するスクリプト
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app.database import SessionLocal
from app.models import Account, Execution
from app.utils.pricing import calculate_token_cost
from datetime import datetime

def fix_execution_costs():
    """古い実行履歴の料金を計算して更新"""
    db = SessionLocal()
    try:
        # costがNoneまたは0の実行履歴を取得
        executions = db.query(Execution).filter(
            (Execution.cost.is_(None)) | (Execution.cost == 0)
        ).filter(
            Execution.status == 'success',
            Execution.tokens_used.isnot(None),
            Execution.tokens_used > 0,
            Execution.model_used.isnot(None)
        ).all()
        
        print(f"料金が未設定の実行履歴: {len(executions)}件")
        
        updated_count = 0
        for execution in executions:
            if execution.tokens_used and execution.tokens_used > 0 and execution.model_used:
                cost = calculate_token_cost(execution.model_used, execution.tokens_used)
                execution.cost = cost
                updated_count += 1
                if updated_count % 10 == 0:
                    print(f"  {updated_count}件更新中...")
        
        db.commit()
        print(f"\n完了: {updated_count}件の実行履歴の料金を更新しました")
        
    except Exception as e:
        db.rollback()
        print(f"エラーが発生しました: {e}")
        raise
    finally:
        db.close()


def recalculate_account_totals():
    """全アカウントの今月と全期間の総計を再計算"""
    db = SessionLocal()
    try:
        accounts = db.query(Account).all()
        updated_count = 0
        
        # 今月の開始日時
        current_month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        for account in accounts:
            # 全実行履歴から総計を計算
            all_executions = db.query(Execution).filter(
                Execution.account_id == account.id,
                Execution.status == 'success',
                Execution.tokens_used.isnot(None),
                Execution.tokens_used > 0
            ).all()
            
            # 今月の実行履歴から今月の総計を計算
            month_executions = db.query(Execution).filter(
                Execution.account_id == account.id,
                Execution.executed_at >= current_month_start,
                Execution.status == 'success',
                Execution.tokens_used.isnot(None),
                Execution.tokens_used > 0
            ).all()
            
            # 全期間の総計を計算
            total_tokens = sum((execution.tokens_used or 0) for execution in all_executions)
            total_cost = sum(float(execution.cost or 0) for execution in all_executions)
            
            # 今月の総計を計算
            tokens_this_month = sum((execution.tokens_used or 0) for execution in month_executions)
            cost_this_month = sum(float(execution.cost or 0) for execution in month_executions)
            
            # アカウントの総計を更新
            account.total_tokens = total_tokens
            account.total_cost = total_cost
            account.tokens_this_month = tokens_this_month
            account.cost_this_month = cost_this_month
            account.last_month_reset = current_month_start
            
            updated_count += 1
            print(f"Updated account {account.id} ({account.username}):")
            print(f"  Total: tokens={total_tokens}, cost=${total_cost:.6f}")
            print(f"  This month: tokens={tokens_this_month}, cost=${cost_this_month:.6f}")
        
        db.commit()
        print(f"\n完了: {updated_count}件のアカウントを更新しました")
        
    except Exception as e:
        db.rollback()
        print(f"エラーが発生しました: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print("=" * 60)
    print("ステップ1: 古い実行履歴の料金を計算して更新")
    print("=" * 60)
    fix_execution_costs()
    
    print("\n" + "=" * 60)
    print("ステップ2: 全アカウントの総計を再計算")
    print("=" * 60)
    recalculate_account_totals()
    
    print("\n" + "=" * 60)
    print("完了しました！")
    print("=" * 60)

