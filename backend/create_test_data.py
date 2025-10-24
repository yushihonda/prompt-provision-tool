#!/usr/bin/env python3
"""
テストデータ作成スクリプト
開発・デモ用のサンプルアカウント、プロンプト、実行履歴を作成します。
"""

import sys
import os
import json

# プロジェクトルートをPythonパスに追加
sys.path.insert(0, os.path.dirname(__file__))

from app.database import SessionLocal
from app.models import Account, Prompt, AccountPrompt, Execution, APIConfig, AccountType, ModelType
from app.auth import get_password_hash
from app.encryption import encryption_service


def create_test_accounts(db):
    """テストアカウントを作成"""
    print("=" * 60)
    print("👤 テストアカウントを作成中...")
    print("=" * 60)
    
    accounts = []
    
    # 既存のadminアカウントを取得
    admin = db.query(Account).filter(Account.username == "admin").first()
    if admin:
        print(f"✅ 既存の管理者アカウント: {admin.username}")
        accounts.append(admin)
    else:
        # 親アカウント（管理者）
        admin = Account(
            username="admin",
            email="admin@example.com",
            hashed_password=get_password_hash("admin123"),
            account_type=AccountType.PARENT,
            is_active=True
        )
        db.add(admin)
        accounts.append(admin)
        print(f"✅ 管理者アカウント作成: admin / admin123")
    
    # 子アカウント（ユーザー）
    test_users = [
        {
            "username": "user1",
            "email": "user1@example.com",
            "password": "user123",
            "rate_limit_hour": 50,
            "rate_limit_day": 500
        },
        {
            "username": "user2",
            "email": "user2@example.com",
            "password": "user123",
            "rate_limit_hour": 100,
            "rate_limit_day": 1000
        },
        {
            "username": "demo",
            "email": "demo@example.com",
            "password": "demo123",
            "rate_limit_hour": 20,
            "rate_limit_day": 200
        }
    ]
    
    for user_data in test_users:
        existing = db.query(Account).filter(Account.username == user_data["username"]).first()
        if existing:
            print(f"⚠️  既に存在: {user_data['username']}")
            accounts.append(existing)
            continue
        
        user = Account(
            username=user_data["username"],
            email=user_data["email"],
            hashed_password=get_password_hash(user_data["password"]),
            account_type=AccountType.CHILD,
            is_active=True
        )
        db.add(user)
        db.flush()  # IDを取得するため
        
        # API設定を作成
        api_config = APIConfig(
            account_id=user.id,
            rate_limit_per_hour=user_data["rate_limit_hour"],
            rate_limit_per_day=user_data["rate_limit_day"],
            is_enabled=True
        )
        db.add(api_config)
        
        accounts.append(user)
        print(f"✅ ユーザーアカウント作成: {user_data['username']} / {user_data['password']}")
    
    db.commit()
    print()
    return accounts


def create_test_prompts(db, admin_account):
    """テストプロンプトを作成"""
    print("=" * 60)
    print("📝 テストプロンプトを作成中...")
    print("=" * 60)
    
    prompts_data = [
        {
            "name": "文章要約プロンプト",
            "description": "長い文章を簡潔に要約します",
            "content": """あなたは優秀な要約アシスタントです。
以下の文章を読んで、重要なポイントを3-5点にまとめて要約してください。

【文章】
{text}

【要約のポイント】
- 主要な情報を漏らさない
- 簡潔で分かりやすく
- 箇条書きで出力""",
            "model_type": "gpt-4",
            "input_schema": json.dumps({
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "title": "要約する文章",
                        "description": "要約したい長文を入力してください"
                    }
                },
                "required": ["text"]
            }, ensure_ascii=False)
        },
        {
            "name": "翻訳プロンプト（英→日）",
            "description": "英語を自然な日本語に翻訳します",
            "content": """あなたはプロの翻訳家です。
以下の英文を、自然で読みやすい日本語に翻訳してください。

【英文】
{english_text}

【翻訳のルール】
- 直訳ではなく、意訳で自然な日本語にする
- 専門用語は適切に訳す
- 文脈を考慮する""",
            "model_type": "gpt-4-turbo-preview",
            "input_schema": json.dumps({
                "type": "object",
                "properties": {
                    "english_text": {
                        "type": "string",
                        "title": "英文",
                        "description": "翻訳したい英文を入力してください"
                    }
                },
                "required": ["english_text"]
            }, ensure_ascii=False)
        },
        {
            "name": "コード説明プロンプト",
            "description": "プログラムコードを分かりやすく説明します",
            "content": """あなたは優秀なプログラミング講師です。
以下のコードを分析して、分かりやすく説明してください。

【コード】
```{language}
{code}
```

【説明してほしい内容】
1. このコードが何をしているか
2. 各部分の役割
3. 注意点やベストプラクティス
4. 改善案（あれば）""",
            "model_type": "gemini-pro",
            "input_schema": json.dumps({
                "type": "object",
                "properties": {
                    "language": {
                        "type": "string",
                        "title": "プログラミング言語",
                        "description": "例: Python, JavaScript, Java"
                    },
                    "code": {
                        "type": "string",
                        "title": "コード",
                        "description": "説明してほしいコードを入力してください"
                    }
                },
                "required": ["language", "code"]
            }, ensure_ascii=False)
        },
        {
            "name": "メール作成プロンプト",
            "description": "ビジネスメールを自動生成します",
            "content": """あなたはビジネスコミュニケーションの専門家です。
以下の情報をもとに、適切なビジネスメールを作成してください。

【送信先】{recipient}
【目的】{purpose}
【要点】{key_points}

【メールの要件】
- 適切な敬語を使用
- 簡潔で分かりやすく
- 丁寧だが堅苦しすぎない
- 件名も提案する""",
            "model_type": "gpt-4",
            "input_schema": json.dumps({
                "type": "object",
                "properties": {
                    "recipient": {
                        "type": "string",
                        "title": "送信先",
                        "description": "例: 取引先の担当者、上司"
                    },
                    "purpose": {
                        "type": "string",
                        "title": "目的",
                        "description": "例: 会議の日程調整、依頼の確認"
                    },
                    "key_points": {
                        "type": "string",
                        "title": "伝えたい要点",
                        "description": "メールで伝えたい内容を簡潔に"
                    }
                },
                "required": ["recipient", "purpose", "key_points"]
            }, ensure_ascii=False)
        },
        {
            "name": "アイデア発想プロンプト",
            "description": "創造的なアイデアを生成します",
            "content": """あなたは創造性豊かなブレインストーミングパートナーです。
以下のテーマについて、革新的で実用的なアイデアを5つ提案してください。

【テーマ】{theme}
【制約条件】{constraints}

【アイデアの条件】
- 実現可能性を考慮
- 独創的でユニークな視点
- 具体的な実施方法も含める
- それぞれのメリット・デメリットも記載""",
            "model_type": "gemini-2.5-pro",
            "input_schema": json.dumps({
                "type": "object",
                "properties": {
                    "theme": {
                        "type": "string",
                        "title": "テーマ",
                        "description": "アイデアを考えたいテーマ"
                    },
                    "constraints": {
                        "type": "string",
                        "title": "制約条件",
                        "description": "予算、時間、リソースなどの制約"
                    }
                },
                "required": ["theme"]
            }, ensure_ascii=False)
        }
    ]
    
    prompts = []
    for prompt_data in prompts_data:
        # 既存チェック
        existing = db.query(Prompt).filter(
            Prompt.name == prompt_data["name"],
            Prompt.created_by == admin_account.id
        ).first()
        
        if existing:
            print(f"⚠️  既に存在: {prompt_data['name']}")
            prompts.append(existing)
            continue
        
        # プロンプト内容を暗号化
        encrypted_content = encryption_service.encrypt(prompt_data["content"])
        
        prompt = Prompt(
            name=prompt_data["name"],
            description=prompt_data["description"],
            encrypted_content=encrypted_content,
            model_type=prompt_data["model_type"],
            input_schema=prompt_data["input_schema"],
            is_active=True,
            created_by=admin_account.id
        )
        db.add(prompt)
        prompts.append(prompt)
        print(f"✅ プロンプト作成: {prompt_data['name']} ({prompt_data['model_type']})")
    
    db.commit()
    print()
    return prompts


def assign_prompts_to_users(db, prompts, users):
    """プロンプトをユーザーに割り当て"""
    print("=" * 60)
    print("🔗 プロンプトをユーザーに割り当て中...")
    print("=" * 60)
    
    # 子アカウントのみをフィルタ
    child_users = [u for u in users if u.account_type == AccountType.CHILD]
    
    if not child_users:
        print("⚠️  子アカウントが見つかりません")
        return
    
    assignments = []
    
    # user1: すべてのプロンプトを割り当て
    user1 = next((u for u in child_users if u.username == "user1"), None)
    if user1:
        for prompt in prompts:
            existing = db.query(AccountPrompt).filter(
                AccountPrompt.account_id == user1.id,
                AccountPrompt.prompt_id == prompt.id
            ).first()
            
            if not existing:
                ap = AccountPrompt(account_id=user1.id, prompt_id=prompt.id)
                db.add(ap)
                assignments.append((user1.username, prompt.name))
        print(f"✅ user1: すべてのプロンプト ({len(prompts)}個) を割り当て")
    
    # user2: 最初の3つのプロンプトを割り当て
    user2 = next((u for u in child_users if u.username == "user2"), None)
    if user2:
        for prompt in prompts[:3]:
            existing = db.query(AccountPrompt).filter(
                AccountPrompt.account_id == user2.id,
                AccountPrompt.prompt_id == prompt.id
            ).first()
            
            if not existing:
                ap = AccountPrompt(account_id=user2.id, prompt_id=prompt.id)
                db.add(ap)
                assignments.append((user2.username, prompt.name))
        print(f"✅ user2: 3個のプロンプトを割り当て")
    
    # demo: 翻訳とメール作成のみ
    demo = next((u for u in child_users if u.username == "demo"), None)
    if demo:
        demo_prompts = [p for p in prompts if "翻訳" in p.name or "メール" in p.name]
        for prompt in demo_prompts:
            existing = db.query(AccountPrompt).filter(
                AccountPrompt.account_id == demo.id,
                AccountPrompt.prompt_id == prompt.id
            ).first()
            
            if not existing:
                ap = AccountPrompt(account_id=demo.id, prompt_id=prompt.id)
                db.add(ap)
                assignments.append((demo.username, prompt.name))
        print(f"✅ demo: {len(demo_prompts)}個のプロンプトを割り当て")
    
    db.commit()
    print()
    return assignments


def create_test_executions(db, prompts, users):
    """テスト実行履歴を作成"""
    print("=" * 60)
    print("📊 テスト実行履歴を作成中...")
    print("=" * 60)
    
    # 子アカウントのみをフィルタ
    child_users = [u for u in users if u.account_type == AccountType.CHILD]
    
    if not child_users or not prompts:
        print("⚠️  ユーザーまたはプロンプトが見つかりません")
        return
    
    # サンプル実行データ
    sample_executions = [
        {
            "user": "user1",
            "prompt": "文章要約プロンプト",
            "input_data": json.dumps({"text": "AI技術の発展により、様々な業界で自動化が進んでいます...（省略）"}, ensure_ascii=False),
            "output_data": "【要約】\n1. AI技術による業界の自動化進展\n2. 生産性向上と新たな雇用創出\n3. 倫理的課題への対応の必要性",
            "model_used": "gpt-4",
            "tokens_used": 850,
            "execution_time": 2300,
            "status": "success"
        },
        {
            "user": "user1",
            "prompt": "翻訳プロンプト（英→日）",
            "input_data": json.dumps({"english_text": "The quick brown fox jumps over the lazy dog."}, ensure_ascii=False),
            "output_data": "素早い茶色のキツネが怠け者の犬を飛び越えました。",
            "model_used": "gpt-4-turbo-preview",
            "tokens_used": 120,
            "execution_time": 1200,
            "status": "success"
        },
        {
            "user": "user2",
            "prompt": "メール作成プロンプト",
            "input_data": json.dumps({
                "recipient": "取引先担当者",
                "purpose": "次回打ち合わせの日程調整",
                "key_points": "来週の候補日を提示、所要時間は1時間程度"
            }, ensure_ascii=False),
            "output_data": "【件名】次回打ち合わせの日程調整について\n\nお世話になっております...",
            "model_used": "gpt-4",
            "tokens_used": 450,
            "execution_time": 1800,
            "status": "success"
        },
        {
            "user": "demo",
            "prompt": "翻訳プロンプト（英→日）",
            "input_data": json.dumps({"english_text": "Hello, World!"}, ensure_ascii=False),
            "output_data": "こんにちは、世界！",
            "model_used": "gpt-4-turbo-preview",
            "tokens_used": 45,
            "execution_time": 800,
            "status": "success"
        }
    ]
    
    created_count = 0
    for exec_data in sample_executions:
        user = next((u for u in child_users if u.username == exec_data["user"]), None)
        prompt = next((p for p in prompts if p.name == exec_data["prompt"]), None)
        
        if not user or not prompt:
            continue
        
        execution = Execution(
            account_id=user.id,
            prompt_id=prompt.id,
            input_data=exec_data["input_data"],
            output_data=exec_data["output_data"],
            model_used=exec_data["model_used"],
            tokens_used=exec_data["tokens_used"],
            execution_time=exec_data["execution_time"],
            status=exec_data["status"]
        )
        db.add(execution)
        created_count += 1
    
    db.commit()
    print(f"✅ {created_count}件の実行履歴を作成しました")
    print()


def print_summary(db):
    """作成されたデータのサマリーを表示"""
    print("=" * 60)
    print("📋 作成されたテストデータのサマリー")
    print("=" * 60)
    
    # アカウント数
    total_accounts = db.query(Account).count()
    parent_accounts = db.query(Account).filter(Account.account_type == AccountType.PARENT).count()
    child_accounts = db.query(Account).filter(Account.account_type == AccountType.CHILD).count()
    
    print(f"👤 アカウント: {total_accounts}個 (管理者: {parent_accounts}, ユーザー: {child_accounts})")
    
    # プロンプト数
    total_prompts = db.query(Prompt).count()
    print(f"📝 プロンプト: {total_prompts}個")
    
    # 割り当て数
    total_assignments = db.query(AccountPrompt).count()
    print(f"🔗 プロンプト割り当て: {total_assignments}件")
    
    # 実行履歴
    total_executions = db.query(Execution).count()
    print(f"📊 実行履歴: {total_executions}件")
    
    print()
    print("=" * 60)
    print("🎉 テストデータの作成が完了しました！")
    print("=" * 60)
    print()
    print("【ログイン情報】")
    print("管理者:")
    print("  username: admin")
    print("  password: admin123")
    print()
    print("ユーザー:")
    print("  username: user1  / password: user123")
    print("  username: user2  / password: user123")
    print("  username: demo   / password: demo123")
    print()
    print("=" * 60)


def main():
    """メイン処理"""
    print()
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 17 + "テストデータ作成" + " " * 23 + "║")
    print("╚" + "=" * 58 + "╝")
    print()
    
    db = SessionLocal()
    
    try:
        # 1. アカウント作成
        accounts = create_test_accounts(db)
        admin = next((a for a in accounts if a.account_type == AccountType.PARENT), accounts[0])
        
        # 2. プロンプト作成
        prompts = create_test_prompts(db, admin)
        
        # 3. プロンプトをユーザーに割り当て
        assign_prompts_to_users(db, prompts, accounts)
        
        # 4. 実行履歴を作成
        create_test_executions(db, prompts, accounts)
        
        # 5. サマリー表示
        print_summary(db)
        
        return 0
        
    except Exception as e:
        print(f"❌ エラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())

