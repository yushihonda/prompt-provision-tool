#!/usr/bin/env python3
"""
サーバー診断スクリプト
データベース接続、設定、テーブルの存在を確認します。
"""

import sys
import os

# プロジェクトルートをPythonパスに追加
sys.path.insert(0, os.path.dirname(__file__))

def check_env_file():
    """環境変数ファイルの存在確認"""
    print("=" * 60)
    print("📄 環境変数ファイルのチェック")
    print("=" * 60)
    
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        print(f"✅ .env ファイルが見つかりました: {env_path}")
        return True
    else:
        print(f"❌ .env ファイルが見つかりません: {env_path}")
        print("   .env ファイルを作成して必要な環境変数を設定してください。")
        return False


def check_config():
    """設定の確認"""
    print("\n" + "=" * 60)
    print("⚙️  設定の読み込みチェック")
    print("=" * 60)
    
    try:
        from app.config import settings
        
        # 必須設定のチェック
        required_settings = {
            'DB_HOST': settings.DB_HOST,
            'DB_PORT': settings.DB_PORT,
            'DB_USER': settings.DB_USER,
            'DB_NAME': settings.DB_NAME,
            'SECRET_KEY': '***' if settings.SECRET_KEY else None,
            'ENCRYPTION_KEY': '***' if settings.ENCRYPTION_KEY else None,
        }
        
        all_ok = True
        for key, value in required_settings.items():
            if value:
                print(f"✅ {key}: {value}")
            else:
                print(f"❌ {key}: 未設定")
                all_ok = False
        
        if all_ok:
            print("\n✅ すべての必須設定が読み込まれました")
        else:
            print("\n❌ 一部の必須設定が不足しています")
            
        return all_ok
    except Exception as e:
        print(f"❌ 設定の読み込みに失敗: {e}")
        return False


def check_database_connection():
    """データベース接続の確認"""
    print("\n" + "=" * 60)
    print("🗄️  データベース接続のチェック")
    print("=" * 60)
    
    try:
        from app.database import engine
        from sqlalchemy import text
        
        # 接続テスト
        with engine.connect() as connection:
            result = connection.execute(text("SELECT 1"))
            result.fetchone()
            
        print("✅ データベースへの接続に成功しました")
        return True
    except Exception as e:
        print(f"❌ データベース接続エラー: {e}")
        print("\n考えられる原因:")
        print("  - データベースサーバーが起動していない")
        print("  - データベースの接続情報が間違っている")
        print("  - データベースが存在しない")
        print("  - ファイアウォールで接続がブロックされている")
        return False


def check_tables():
    """テーブルの存在確認"""
    print("\n" + "=" * 60)
    print("📊 テーブルの存在チェック")
    print("=" * 60)
    
    try:
        from app.database import engine
        from sqlalchemy import inspect
        
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        
        required_tables = ['accounts', 'prompts', 'executions']
        
        if not tables:
            print("❌ テーブルが1つも見つかりません")
            print("\nマイグレーションを実行してください:")
            print("  cd backend")
            print("  alembic upgrade head")
            return False
        
        print(f"見つかったテーブル: {', '.join(tables)}")
        
        missing_tables = [t for t in required_tables if t not in tables]
        if missing_tables:
            print(f"\n❌ 以下のテーブルが見つかりません: {', '.join(missing_tables)}")
            print("\nマイグレーションを実行してください:")
            print("  cd backend")
            print("  alembic upgrade head")
            return False
        
        print("\n✅ すべての必須テーブルが存在します")
        return True
    except Exception as e:
        print(f"❌ テーブルチェックエラー: {e}")
        return False


def check_accounts():
    """アカウントの存在確認"""
    print("\n" + "=" * 60)
    print("👤 アカウントの存在チェック")
    print("=" * 60)
    
    try:
        from app.database import SessionLocal
        from app.models import Account
        
        db = SessionLocal()
        try:
            accounts = db.query(Account).all()
            
            if not accounts:
                print("⚠️  アカウントが1つも登録されていません")
                print("\n管理者アカウントを作成してください:")
                print("  cd backend")
                print("  python -m app.init_admin")
                return False
            
            print(f"✅ {len(accounts)} 個のアカウントが登録されています")
            for account in accounts:
                print(f"   - {account.username} ({account.account_type.value})")
            
            return True
        finally:
            db.close()
    except Exception as e:
        print(f"❌ アカウントチェックエラー: {e}")
        return False


def main():
    """メイン処理"""
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 15 + "サーバー診断ツール" + " " * 23 + "║")
    print("╚" + "=" * 58 + "╝")
    print()
    
    results = []
    
    # 各チェックを実行
    results.append(("環境変数ファイル", check_env_file()))
    
    if results[-1][1]:  # .envが存在する場合のみ続行
        results.append(("設定読み込み", check_config()))
        
        if results[-1][1]:  # 設定が正常な場合のみ続行
            results.append(("データベース接続", check_database_connection()))
            
            if results[-1][1]:  # DB接続が成功した場合のみ続行
                results.append(("テーブル存在確認", check_tables()))
                
                if results[-1][1]:  # テーブルが存在する場合のみ続行
                    results.append(("アカウント確認", check_accounts()))
    
    # サマリー
    print("\n" + "=" * 60)
    print("📋 診断結果サマリー")
    print("=" * 60)
    
    for name, result in results:
        status = "✅" if result else "❌"
        print(f"{status} {name}")
    
    all_ok = all(result for _, result in results)
    
    if all_ok:
        print("\n" + "=" * 60)
        print("🎉 すべてのチェックが成功しました！")
        print("=" * 60)
        print("\nサーバーを起動できます:")
        print("  cd backend")
        print("  uvicorn app.main:app --host 0.0.0.0 --port 8000")
    else:
        print("\n" + "=" * 60)
        print("⚠️  問題が見つかりました")
        print("=" * 60)
        print("\n上記のエラーを修正してから再度実行してください。")
        return 1
    
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n中断されました")
        sys.exit(1)
    except Exception as e:
        print(f"\n予期しないエラー: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

