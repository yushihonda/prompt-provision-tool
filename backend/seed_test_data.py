"""
テストデータ挿入スクリプト（ローカル開発用）

本番環境では使用しないでください。

使用方法:
    cd backend
    python seed_test_data.py
"""

from typing import List
from app.database import SessionLocal
from app.models import Account, AccountType, APIConfig, Prompt, AccountPrompt, Execution
from app.auth import get_password_hash
from app.encryption import encryption_service
import json


ALLOWED_MODELS: List[str] = [
    "gpt-5-thinking",
    "gpt-5-pro",
    "gpt-5",
    "gpt-4o-mini",  # コスパ最適化モデル
    "gemini-2.5-pro-deep-think",
    "gemini-2.5-pro",  # 無料枠: 1日100リクエストまで
    "gemini-2.5-flash",
    "gemini-2.0-flash",  # コスパ最適化モデル
]


def reset_and_seed() -> None:
    """既存データを削除してテストデータを追加"""
    db = SessionLocal()
    try:
        # 既存データを削除（依存関係の下位→上位の順）
        db.query(Execution).delete(synchronize_session=False)
        db.query(AccountPrompt).delete(synchronize_session=False)
        db.query(Prompt).delete(synchronize_session=False)
        db.query(APIConfig).delete(synchronize_session=False)
        db.query(Account).delete(synchronize_session=False)
        db.commit()

        # 管理者アカウント
        admin = Account(
            username="admin",
            email="admin@example.com",
            hashed_password=get_password_hash("Admin#12345"),
            account_type=AccountType.PARENT,
            is_active=True,
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)

        # 子ユーザー
        user = Account(
            username="user1",
            email="user1@example.com",
            hashed_password=get_password_hash("User#12345"),
            account_type=AccountType.CHILD,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        # 子ユーザー向け API 設定
        api_cfg = APIConfig(
            account_id=user.id,
            rate_limit_per_hour=100,
            rate_limit_per_day=1000,
            is_enabled=True,
        )
        db.add(api_cfg)
        db.commit()

        # テスト用プロンプト定義（具体的な内容と入力スキーマ）
        test_prompts_config = [
            # 1. 長文要約タスク（シンプルな入力スキーマ）
            {
                "name": "長文要約",
                "description": "長文テキストを要約し、要点を整理します。長文テストに最適です。",
                "model": "gpt-5-thinking",
                "allows_file_output": True,  # PDFやDOCXで出力可能
                "content": """以下の長文テキストを要約し、要点を整理してください。

## 出力形式
- タイトル: テキストの主題を1行で
- 要点: 3-5個の箇条書き
- 詳細要約: 段落形式で200-300文字
- キーワード: 重要な用語を5-10個

## 入力テキスト
{{text}}

上記のテキストを分析し、構造化された要約を出力してください。""",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "title": "要約するテキスト",
                            "description": "要約したい長文テキストを入力してください（10,000文字以上でも対応可能）"
                        }
                    },
                    "required": ["text"]
                }
            },
            # 2. コードレビュー（複数フィールド、オプション含む）
            {
                "name": "コードレビュー",
                "description": "コードとコメントを分析し、改善提案を行います。",
                "model": "gpt-5-pro",
                "content": """以下のコードをレビューし、改善提案を行ってください。

## レビュー観点
- コードの品質と可読性
- パフォーマンスの最適化
- セキュリティ上の懸念
- ベストプラクティスへの準拠

## コード
```{{language}}
{{code}}
```

## レビュー依頼者のコメント（オプション）
{{comment}}

## 特に確認してほしい点（オプション）
{{focus}}

上記のコードをレビューし、具体的な改善提案を出力してください。""",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "title": "レビューするコード",
                            "description": "レビューしたいコードを入力してください（長文のコードでも対応可能）"
                        },
                        "language": {
                            "type": "string",
                            "title": "プログラミング言語",
                            "description": "コードのプログラミング言語（例: python, javascript, java）",
                            "default": "python"
                        },
                        "comment": {
                            "type": "string",
                            "title": "コメント（オプション）",
                            "description": "レビュー依頼者のコメントや質問（任意）"
                        },
                        "focus": {
                            "type": "string",
                            "title": "特に確認してほしい点（オプション）",
                            "description": "特に重点的にレビューしてほしい点（任意）"
                        }
                    },
                    "required": ["code", "language"]
                }
            },
            # 3. 文章生成（複数パラメータ、オプション含む）
            {
                "name": "文章生成",
                "description": "指定された条件に基づいて文章を生成します。",
                "model": "gemini-2.5-pro",
                "allows_file_output": True,  # DOCXやPDFで出力可能
                "content": """以下の条件に基づいて文章を生成してください。

## 生成条件
- トピック: {{topic}}
- 文体: {{style}}
- 文字数: 約{{length}}文字
- トーン（オプション）: {{tone}}
- 含めるキーワード（オプション）: {{keywords}}
- 対象読者（オプション）: {{audience}}

上記の条件に基づいて、読みやすく魅力的な文章を生成してください。""",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "topic": {
                            "type": "string",
                            "title": "トピック",
                            "description": "文章の主題やトピック"
                        },
                        "style": {
                            "type": "string",
                            "title": "文体",
                            "description": "文章の文体（例: フォーマル、カジュアル、技術的）",
                            "default": "カジュアル"
                        },
                        "length": {
                            "type": "integer",
                            "title": "文字数",
                            "description": "生成する文章の目安文字数",
                            "default": 1000,
                            "minimum": 100,
                            "maximum": 10000
                        },
                        "tone": {
                            "type": "string",
                            "title": "トーン（オプション）",
                            "description": "文章のトーン（例: 前向き、真剣、ユーモラス）"
                        },
                        "keywords": {
                            "type": "string",
                            "title": "含めるキーワード（オプション）",
                            "description": "文章に含めたいキーワード（カンマ区切り）"
                        },
                        "audience": {
                            "type": "string",
                            "title": "対象読者（オプション）",
                            "description": "文章の対象読者（例: 一般読者、専門家、学生）"
                        }
                    },
                    "required": ["topic", "style", "length"]
                }
            },
            # 4. データ分析（複数のデータフィールド）
            {
                "name": "データ分析",
                "description": "提供されたデータを分析し、洞察を提供します。",
                "model": "gemini-2.5-pro-deep-think",
                "allows_file_output": True,  # CSVやPDFで出力可能
                "content": """以下のデータを分析し、洞察と推奨事項を提供してください。

## データ
{{data}}

## 背景情報（オプション）
{{context}}

## 分析してほしい質問（オプション）
{{question}}

## 出力形式
1. データの概要
2. 主要な発見事項（3-5個）
3. 統計的な傾向
4. 推奨事項

上記のデータを分析し、構造化された分析結果を出力してください。""",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "data": {
                            "type": "string",
                            "title": "分析するデータ",
                            "description": "分析したいデータを入力してください（CSV、JSON、テキスト形式など、長文でも対応可能）"
                        },
                        "context": {
                            "type": "string",
                            "title": "背景情報（オプション）",
                            "description": "データの背景や文脈に関する情報（任意）"
                        },
                        "question": {
                            "type": "string",
                            "title": "分析してほしい質問（オプション）",
                            "description": "特に分析してほしい質問や仮説（任意）"
                        }
                    },
                    "required": ["data"]
                }
            },
            # 5. 長文翻訳（シンプルな入力スキーマ、長文対応）
            {
                "name": "長文翻訳",
                "description": "長文テキストを翻訳します。長文テストに最適です。",
                "model": "gemini-2.5-flash",
                "allows_file_output": True,  # PDFやDOCXで出力可能
                "content": """以下のテキストを{{target_language}}に翻訳してください。

## 翻訳条件
- 元の言語: {{source_language}}
- 翻訳先の言語: {{target_language}}
- 専門分野（オプション）: {{domain}}
- トーン（オプション）: {{tone}}

## 原文
{{text}}

上記のテキストを自然で正確な{{target_language}}に翻訳してください。専門用語や固有名詞は適切に処理してください。""",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "title": "翻訳するテキスト",
                            "description": "翻訳したいテキストを入力してください（10,000文字以上でも対応可能）"
                        },
                        "source_language": {
                            "type": "string",
                            "title": "元の言語",
                            "description": "原文の言語（例: 日本語、英語、中国語）",
                            "default": "日本語"
                        },
                        "target_language": {
                            "type": "string",
                            "title": "翻訳先の言語",
                            "description": "翻訳先の言語（例: 英語、中国語、スペイン語）",
                            "default": "英語"
                        },
                        "domain": {
                            "type": "string",
                            "title": "専門分野（オプション）",
                            "description": "テキストの専門分野（例: 技術、医学、法律）"
                        },
                        "tone": {
                            "type": "string",
                            "title": "トーン（オプション）",
                            "description": "翻訳のトーン（例: フォーマル、カジュアル）"
                        }
                    },
                    "required": ["text", "source_language", "target_language"]
                }
            },
            # 6. その他のモデル用の基本プロンプト（全モデル対応）
            {
                "name": "基本要約",
                "description": "テキストの要点を簡潔にまとめます。",
                "model": "gpt-5",
                "content": """以下の入力をもとに要点を日本語で簡潔にまとめてください。
- 出力はmarkdownで、見出し/箇条書きを適宜使用
- 必要なら短い提案を1つ添える

<入力>
{{input}}""",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "input": {
                            "type": "string",
                            "title": "入力テキスト",
                            "description": "モデルに渡す任意のテキスト（長文可）"
                        }
                    },
                    "required": ["input"]
                }
            },
            {
                "name": "基本要約",
                "description": "テキストの要点を簡潔にまとめます。",
                "model": "gpt-4o-mini",
                "content": """以下の入力をもとに要点を日本語で簡潔にまとめてください。
- 出力はmarkdownで、見出し/箇条書きを適宜使用
- 必要なら短い提案を1つ添える

<入力>
{{input}}""",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "input": {
                            "type": "string",
                            "title": "入力テキスト",
                            "description": "モデルに渡す任意のテキスト（長文可）"
                        }
                    },
                    "required": ["input"]
                }
            },
            {
                "name": "基本要約",
                "description": "テキストの要点を簡潔にまとめます。",
                "model": "gemini-2.0-flash",
                "content": """以下の入力をもとに要点を日本語で簡潔にまとめてください。
- 出力はmarkdownで、見出し/箇条書きを適宜使用
- 必要なら短い提案を1つ添える

<入力>
{{input}}""",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "input": {
                            "type": "string",
                            "title": "入力テキスト",
                            "description": "モデルに渡す任意のテキスト（長文可）"
                        }
                    },
                    "required": ["input"]
                }
            },
        ]

        created_prompts: List[Prompt] = []
        for prompt_config in test_prompts_config:
            content_plain = prompt_config["content"]
            encrypted = encryption_service.encrypt(content_plain)
            input_schema_str = json.dumps(prompt_config["input_schema"], ensure_ascii=False)
            
            p = Prompt(
                name=prompt_config["name"],
                description=prompt_config["description"],
                encrypted_content=encrypted,
                model_type=prompt_config["model"],
                input_schema=input_schema_str,
                is_active=True,
                allows_file_output=prompt_config.get("allows_file_output", False),  # デフォルトはFalse
                created_by=admin.id,
            )
            db.add(p)
            db.commit()
            db.refresh(p)
            created_prompts.append(p)

        # 子ユーザーへ全てのプロンプトを割り当て
        for p in created_prompts:
            ap = AccountPrompt(account_id=user.id, prompt_id=p.id)
            db.add(ap)
        db.commit()

        print("✓ テストデータを初期化しました")
        print(f"  管理者: {admin.username} / admin@example.com (パスワード: Admin#12345)")
        print(f"  ユーザー: {user.username} / user1@example.com (パスワード: User#12345)")
        print(f"  プロンプト: {len(created_prompts)}件")
        print("\n作成されたプロンプト:")
        for p in created_prompts:
            file_output_status = "✅ ファイル出力可" if p.allows_file_output else "❌ ファイル出力不可"
            print(f"  - {p.name} ({p.model_type}) - {file_output_status}")

    except Exception as e:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    reset_and_seed()

