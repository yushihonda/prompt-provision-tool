# プロンプト提供ツール

GPT及びGeminiのプロンプトを外部に漏らさず、実行機能のみを提供するWebアプリケーションです。

## 技術スタック

- **バックエンド**: FastAPI (Python 3.11+)
- **フロントエンド**: HTML/CSS/JavaScript
- **データベース**: MySQL 8.0
- **インフラ**: ConoHa VPS
- **AI**: OpenAI GPT-4/5, Google Gemini 2.5 Pro

## セキュリティ機能

- プロンプトはAES-256で暗号化してDB保存
- クライアントにプロンプトを一切送信しない
- JWT認証によるアクセス制御
- 親/子アカウントの権限分離

## セットアップ

### 1. 依存パッケージのインストール

```bash
cd backend
pip install -r requirements.txt
```

### 2. 環境変数の設定

```bash
cp .env.example .env
# .envファイルを編集して、適切な値を設定
```

### 3. データベースのセットアップ

```bash
# MySQLにログイン
mysql -u root -p

# データベースとユーザーの作成
CREATE DATABASE prompt_provision_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'prompt_tool_user'@'localhost' IDENTIFIED BY 'your_secure_password';
GRANT ALL PRIVILEGES ON prompt_provision_db.* TO 'prompt_tool_user'@'localhost';
FLUSH PRIVILEGES;
```

### 4. マイグレーション実行

```bash
cd backend
alembic upgrade head
```

### 5. 初期管理者アカウントの作成

```bash
python -m app.init_admin
```

### 6. アプリケーションの起動

```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

アプリケーションは http://localhost:8000 でアクセスできます。

## API ドキュメント

起動後、以下のURLでSwagger UIを確認できます：
- http://localhost:8000/docs

## プロジェクト構造

```
prompt-provision-tool/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPIエントリポイント
│   │   ├── config.py            # 設定管理
│   │   ├── database.py          # DB接続
│   │   ├── models.py            # SQLAlchemyモデル
│   │   ├── schemas.py           # Pydanticスキーマ
│   │   ├── auth.py              # 認証・JWT
│   │   ├── encryption.py        # プロンプト暗号化
│   │   ├── api/
│   │   │   ├── admin.py
│   │   │   ├── user.py
│   │   │   └── execute.py
│   │   └── services/
│   │       ├── openai_service.py
│   │       └── gemini_service.py
│   ├── requirements.txt
│   └── alembic/
├── frontend/
│   ├── admin/
│   ├── user/
│   └── css/
└── deployment/
```

## 📚 ドキュメント

詳細なドキュメントは [`docs/`](docs/) フォルダにあります：

### 📖 主要ドキュメント
- **[システム仕様書](docs/SYSTEM_SPECIFICATION.md)** - システム全体の仕様（必読）
- **[ユーザーガイド](docs/USER_GUIDE.md)** - 管理者・ユーザー向けガイド
- **[データベース設計](docs/DATABASE_DESIGN.md)** - DB設計詳細

### 🚀 セットアップ・運用
- **[セットアップガイド](docs/SETUP_GUIDE.md)** - 環境構築手順
- **[デプロイガイド](deployment/README.md)** - 本番環境構築
- **[トラブルシューティング](docs/TROUBLESHOOTING.md)** - 問題解決

### 📝 リファレンス
- **[ドキュメント一覧](docs/DOCUMENTATION_INDEX.md)** - 全ドキュメントのナビゲーション
- **[クイックリファレンス](docs/QUICK_REFERENCE.md)** - コマンド・API一覧

**まずは [ドキュメント一覧](docs/DOCUMENTATION_INDEX.md) をご覧ください！**

