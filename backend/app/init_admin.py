"""
初期管理者アカウントを作成するスクリプト
"""
import sys
from app.database import SessionLocal, engine
from app.models import Base, Account, AccountType
from app.auth import get_password_hash


def create_admin():
    """初期管理者アカウントを作成"""
    # テーブルの作成
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    try:
        # 既に管理者が存在するかチェック
        existing_admin = db.query(Account).filter(
            Account.account_type == AccountType.PARENT
        ).first()
        
        if existing_admin:
            print("✓ 管理者アカウントは既に存在します")
            print(f"  ユーザー名: {existing_admin.username}")
            return
        
        # 管理者アカウントの作成
        print("初期管理者アカウントを作成します...")
        print()
        
        username = input("ユーザー名 [admin]: ").strip() or "admin"
        email = input("メールアドレス [admin@example.com]: ").strip() or "admin@example.com"
        password = input("パスワード [admin123]: ").strip() or "admin123"
        
        admin = Account(
            username=username,
            email=email,
            hashed_password=get_password_hash(password),
            account_type=AccountType.PARENT,
            is_active=True
        )
        
        db.add(admin)
        db.commit()
        
        print()
        print("✓ 管理者アカウントを作成しました")
        print(f"  ユーザー名: {username}")
        print(f"  メールアドレス: {email}")
        print()
        print("セキュリティのため、本番環境では必ずパスワードを変更してください！")
        
    except Exception as e:
        print(f"✗ エラーが発生しました: {str(e)}")
        db.rollback()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    create_admin()

