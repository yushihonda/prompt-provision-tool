#!/usr/bin/env python3
"""
テストデータ作成スクリプト（簡易版・直接SQL使用）
"""

import sys
import os
import json
import pymysql
from datetime import datetime

# プロジェクトルートをPythonパスに追加
sys.path.insert(0, os.path.dirname(__file__))

from app.config import settings
from app.auth import get_password_hash
from app.encryption import encryption_service


def main():
    print()
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 17 + "テストデータ作成" + " " * 23 + "║")
    print("╚" + "=" * 58 + "╝")
    print()
    
    # データベース接続
    conn = pymysql.connect(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database=settings.DB_NAME,
        charset='utf8mb4'
    )
    
    try:
        cursor = conn.cursor()
        
        # 1. アカウント作成
        print("=" * 60)
        print("👤 テストアカウントを作成中...")
        print("=" * 60)
        
        # 管理者アカウント
        cursor.execute("SELECT id, username FROM accounts WHERE username = 'admin'")
        admin = cursor.fetchone()
        if admin:
            print(f"✅ 既存の管理者アカウント: {admin[1]}")
            admin_id = admin[0]
        else:
            print("⚠️  管理者アカウントが見つかりません")
            return 1
        
        # ユーザーアカウント
        users_data = [
            ('user1', 'user1@example.com', 'user123', 50, 500),
            ('user2', 'user2@example.com', 'user123', 100, 1000),
            ('demo', 'demo@example.com', 'demo123', 20, 200)
        ]
        
        user_ids = {}
        for username, email, password, rate_hour, rate_day in users_data:
            cursor.execute("SELECT id FROM accounts WHERE username = %s", (username,))
            existing = cursor.fetchone()
            
            if existing:
                print(f"⚠️  既に存在: {username}")
                user_ids[username] = existing[0]
            else:
                hashed_password = get_password_hash(password)
                cursor.execute("""
                    INSERT INTO accounts (username, email, hashed_password, account_type, is_active)
                    VALUES (%s, %s, %s, 'CHILD', 1)
                """, (username, email, hashed_password))
                user_id = cursor.lastrowid
                user_ids[username] = user_id
                
                # API設定
                cursor.execute("""
                    INSERT INTO api_configs (account_id, rate_limit_per_hour, rate_limit_per_day, is_enabled)
                    VALUES (%s, %s, %s, 1)
                """, (user_id, rate_hour, rate_day))
                
                print(f"✅ ユーザーアカウント作成: {username} / {password}")
        
        conn.commit()
        print()
        
        # 2. プロンプト作成
        print("=" * 60)
        print("📝 テストプロンプトを作成中...")
        print("=" * 60)
        
        prompts_data = [
            ("文章要約プロンプト", "長い文章を簡潔に要約します", """あなたは優秀な要約アシスタントです。
以下の文章を読んで、重要なポイントを3-5点にまとめて要約してください。

【文章】
{text}

【要約のポイント】
- 主要な情報を漏らさない
- 簡潔で分かりやすく
- 箇条書きで出力""", "gpt-4", {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "title": "要約する文章",
                        "description": "要約したい長文を入力してください"
                    }
                },
                "required": ["text"]
            }),
            ("翻訳プロンプト（英→日）", "英語を自然な日本語に翻訳します", """あなたはプロの翻訳家です。
以下の英文を、自然で読みやすい日本語に翻訳してください。

【英文】
{english_text}

【翻訳のルール】
- 直訳ではなく、意訳で自然な日本語にする
- 専門用語は適切に訳す
- 文脈を考慮する""", "gpt-4-turbo-preview", {
                "type": "object",
                "properties": {
                    "english_text": {
                        "type": "string",
                        "title": "英文",
                        "description": "翻訳したい英文を入力してください"
                    }
                },
                "required": ["english_text"]
            }),
            ("コード説明プロンプト", "プログラムコードを分かりやすく説明します", """あなたは優秀なプログラミング講師です。
以下のコードを分析して、分かりやすく説明してください。

【コード】
```{language}
{code}
```

【説明してほしい内容】
1. このコードが何をしているか
2. 各部分の役割
3. 注意点やベストプラクティス
4. 改善案（あれば）""", "gemini-pro", {
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
            }),
            ("メール作成プロンプト", "ビジネスメールを自動生成します", """あなたはビジネスコミュニケーションの専門家です。
以下の情報をもとに、適切なビジネスメールを作成してください。

【送信先】{recipient}
【目的】{purpose}
【要点】{key_points}

【メールの要件】
- 適切な敬語を使用
- 簡潔で分かりやすく
- 丁寧だが堅苦しすぎない
- 件名も提案する""", "gpt-4", {
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
            }),
            ("アイデア発想プロンプト", "創造的なアイデアを生成します", """あなたは創造性豊かなブレインストーミングパートナーです。
以下のテーマについて、革新的で実用的なアイデアを5つ提案してください。

【テーマ】{theme}
【制約条件】{constraints}

【アイデアの条件】
- 実現可能性を考慮
- 独創的でユニークな視点
- 具体的な実施方法も含める
- それぞれのメリット・デメリットも記載""", "gemini-2.5-pro", {
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
            })
        ]
        
        prompt_ids = {}
        for name, description, content, model_type, input_schema in prompts_data:
            # 既存チェック
            cursor.execute("""
                SELECT id FROM prompts 
                WHERE name = %s AND created_by = %s
            """, (name, admin_id))
            existing = cursor.fetchone()
            
            if existing:
                print(f"⚠️  既に存在: {name}")
                prompt_ids[name] = existing[0]
                continue
            
            # 暗号化
            encrypted_content = encryption_service.encrypt(content)
            input_schema_json = json.dumps(input_schema, ensure_ascii=False)
            
            # 挿入
            cursor.execute("""
                INSERT INTO prompts (name, description, encrypted_content, model_type, 
                                   input_schema, is_active, created_by)
                VALUES (%s, %s, %s, %s, %s, 1, %s)
            """, (name, description, encrypted_content, model_type, 
                  input_schema_json, admin_id))
            
            prompt_ids[name] = cursor.lastrowid
            print(f"✅ プロンプト作成: {name} ({model_type})")
        
        conn.commit()
        print()
        
        # 3. プロンプト割り当て
        print("=" * 60)
        print("🔗 プロンプトをユーザーに割り当て中...")
        print("=" * 60)
        
        # user1: すべてのプロンプト
        if 'user1' in user_ids:
            for prompt_name, prompt_id in prompt_ids.items():
                cursor.execute("""
                    SELECT id FROM account_prompts 
                    WHERE account_id = %s AND prompt_id = %s
                """, (user_ids['user1'], prompt_id))
                
                if not cursor.fetchone():
                    cursor.execute("""
                        INSERT INTO account_prompts (account_id, prompt_id)
                        VALUES (%s, %s)
                    """, (user_ids['user1'], prompt_id))
            print(f"✅ user1: すべてのプロンプト ({len(prompt_ids)}個) を割り当て")
        
        # user2: 最初の3つ
        if 'user2' in user_ids:
            count = 0
            for prompt_name, prompt_id in list(prompt_ids.items())[:3]:
                cursor.execute("""
                    SELECT id FROM account_prompts 
                    WHERE account_id = %s AND prompt_id = %s
                """, (user_ids['user2'], prompt_id))
                
                if not cursor.fetchone():
                    cursor.execute("""
                        INSERT INTO account_prompts (account_id, prompt_id)
                        VALUES (%s, %s)
                    """, (user_ids['user2'], prompt_id))
                    count += 1
            print(f"✅ user2: {count}個のプロンプトを割り当て")
        
        # demo: 翻訳とメール
        if 'demo' in user_ids:
            demo_prompts = [name for name in prompt_ids.keys() 
                          if "翻訳" in name or "メール" in name]
            for prompt_name in demo_prompts:
                prompt_id = prompt_ids[prompt_name]
                cursor.execute("""
                    SELECT id FROM account_prompts 
                    WHERE account_id = %s AND prompt_id = %s
                """, (user_ids['demo'], prompt_id))
                
                if not cursor.fetchone():
                    cursor.execute("""
                        INSERT INTO account_prompts (account_id, prompt_id)
                        VALUES (%s, %s)
                    """, (user_ids['demo'], prompt_id))
            print(f"✅ demo: {len(demo_prompts)}個のプロンプトを割り当て")
        
        conn.commit()
        print()
        
        # サマリー
        print("=" * 60)
        print("📋 作成されたテストデータのサマリー")
        print("=" * 60)
        
        cursor.execute("SELECT COUNT(*) FROM accounts")
        total_accounts = cursor.fetchone()[0]
        print(f"👤 アカウント: {total_accounts}個")
        
        cursor.execute("SELECT COUNT(*) FROM prompts")
        total_prompts = cursor.fetchone()[0]
        print(f"📝 プロンプト: {total_prompts}個")
        
        cursor.execute("SELECT COUNT(*) FROM account_prompts")
        total_assignments = cursor.fetchone()[0]
        print(f"🔗 プロンプト割り当て: {total_assignments}件")
        
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
        
        return 0
        
    except Exception as e:
        print(f"❌ エラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
        return 1
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    sys.exit(main())

