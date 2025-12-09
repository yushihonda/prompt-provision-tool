#!/usr/bin/env python3
"""
子アカウント（ユーザー）を作成するスクリプト

ローカル開発環境・本番環境の両方で使用可能です。

使用方法:
    python create_user.py
"""

import sys
from app.database import SessionLocal
from app.models import Account, AccountType, APIConfig
from app.auth import get_password_hash


def create_child_account(username: str, email: str, password: str):
    """子アカウントを作成"""
    db = SessionLocal()

    try:
        # 既存チェック
        existing = db.query(Account).filter(Account.username == username).first()
        if existing:
            print(f"✗ ユーザー名 '{username}' は既に使用されています")
            return False

        existing_email = db.query(Account).filter(Account.email == email).first()
        if existing_email:
            print(f"✗ メールアドレス '{email}' は既に使用されています")
            return False

        # アカウント作成
        account = Account(
            username=username,
            email=email,
            hashed_password=get_password_hash(password),
            account_type=AccountType.CHILD,
            is_active=True
        )

        db.add(account)
        db.commit()
        db.refresh(account)

        # API設定も作成
        api_config = APIConfig(
            account_id=account.id,
            rate_limit_per_hour=100,
            rate_limit_per_day=1000,
            is_enabled=True
        )

        db.add(api_config)
        db.commit()

        print(f"✓ 子アカウントを作成しました")
        print(f"  ID: {account.id}")
        print(f"  ユーザー名: {account.username}")
        print(f"  メールアドレス: {account.email}")
        print(f"  アカウントタイプ: {account.account_type}")
        print()
        print("次のステップ:")
        print("1. 管理画面でこのアカウントにプロンプトを割り当ててください")
        print("2. ユーザーにログイン情報を伝えてください")
        print(f"   ログインURL: http://your-server-ip/static/user/login.html")
        print(f"   ユーザー名: {username}")
        print(f"   パスワード: {password}")

        return True

    except Exception as e:
        print(f"✗ エラーが発生しました: {str(e)}")
        db.rollback()
        return False
    finally:
        db.close()


def main():
    print("=" * 50)
    print("子アカウント（ユーザー）作成")
    print("=" * 50)
    print()

    # 入力
    username = input("ユーザー名: ").strip()
    if not username:
        print("✗ ユーザー名は必須です")
        sys.exit(1)

    email = input("メールアドレス: ").strip()
    if not email:
        print("✗ メールアドレスは必須です")
        sys.exit(1)

    password = input("パスワード: ").strip()
    if not password:
        print("✗ パスワードは必須です")
        sys.exit(1)

    print()

    # 確認
    print("以下の内容で子アカウントを作成します:")
    print(f"  ユーザー名: {username}")
    print(f"  メールアドレス: {email}")
    print(f"  パスワード: {password}")
    print()

    confirm = input("作成しますか？ (yes/no): ").strip().lower()
    if confirm not in ['yes', 'y']:
        print("キャンセルしました")
        sys.exit(0)

    print()

    # 作成
    success = create_child_account(username, email, password)

    if success:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
