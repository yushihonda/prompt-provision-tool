# Prompt Provision Tool

プロンプト本文を外部に出さず、AI実行機能を提供するWebアプリケーション。

## 機能/セキュリティ（要点）
- プロンプトは暗号化保存（Fernet）し、復号はサーバ側のみ
- クライアントへ本文を送らず、完成プロンプトはAI APIにのみ送信
- JWT認証（PARENT/CHILDロール）
- ガードレール注入・出力サニタイズ・ログ抑止（漏洩対策）

## 対応モデル
- OpenAI: gpt-4 / gpt-4-turbo-preview
- Google: gemini-pro / gemini-2.5-pro / gemini-2.5-pro-deep-think（内部で1.5へフォールバック）

## 環境変数（.env）
```
# DB
DB_HOST=localhost
DB_PORT=3306
DB_USER=prompt_tool_user
DB_PASSWORD=your_password
DB_NAME=prompt_provision_db

# Security
SECRET_KEY=your-secret-hex
ENCRYPTION_KEY=your-32-char-key
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# AI API
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=...

# App
ENVIRONMENT=production
CORS_ORIGINS=http://your-domain
LOG_FINAL_PROMPT=false

# Guardrails（任意・推奨）
ENABLE_PROMPT_GUARDRAILS=true
GUARDRAIL_PREFIX="次のポリシーに従う...（開示拒否 等）"
SANITIZE_MIN_MATCH_LEN=60
SANITIZE_SIMILARITY_THRESHOLD=0.6
```

## セットアップ（本番）
1) 依存インストール
```
cd backend
pip install -r requirements.txt
```
2) DB作成（MySQL 8.0）
```
CREATE DATABASE prompt_provision_db CHARACTER SET utf8mb4;
CREATE USER 'prompt_tool_user'@'localhost' IDENTIFIED BY 'your_password';
GRANT ALL PRIVILEGES ON prompt_provision_db.* TO 'prompt_tool_user'@'localhost';
```
3) マイグレーション
```
cd backend
alembic upgrade head
```
4) 管理者作成
```
python -m app.init_admin
```
5) 起動
```
ENVIRONMENT=production uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## API（要約）
- 認証
  - POST /api/auth/login
- 管理者（PARENTのみ）
  - GET /api/admin/dashboard
  - GET/POST/PATCH/DELETE /api/admin/accounts...
  - GET/POST/PATCH/DELETE /api/admin/prompts...
  - POST /api/admin/assign-prompt, DELETE /api/admin/assign-prompt/{id}
  - GET /api/admin/executions
- 子ユーザー（CHILD）
  - GET /api/user/prompts
  - GET /api/user/prompts/{id}
  - GET /api/user/executions, GET /api/user/executions/{id}
- 実行
  - POST /api/execute  { prompt_id, input_data }

## 運用
- ヘルスチェック: GET /health
- ログ: systemdやNginx設定は `deployment/` 参照
- 本番要件
  - APIキー設定必須（未設定時は実行エラー）
  - `/docs` 非公開、入力詳細ログ非出力、完成プロンプトログ抑止

## 構成
```
prompt-provision-tool/
├── backend/        # FastAPI・アプリケーション
├── frontend/       # 静的フロント（/static に配信）
├── deployment/     # Nginx・systemd 等
└── README.md       # 本ファイル
```

## Docker（ローカル専用）

以下はローカル検証用です（本番は `deployment/` の systemd 構成を使用）。

1) 環境変数を用意（.env.local）
- リポジトリ直下に `.env.local` を作成し、以下を参考に値を設定
```
# ===== Backend (Settings)
DB_HOST=db
DB_PORT=3306
DB_USER=prompt
DB_PASSWORD=promptpass
DB_NAME=prompttool

SECRET_KEY=replace-with-long-secret
ENCRYPTION_KEY=replace-with-32-byte-base64

OPENAI_API_KEY=sk-your-openai-key
GEMINI_API_KEY=AIza-your-gemini-key

APP_HOST=0.0.0.0
APP_PORT=8000
CORS_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
ENVIRONMENT=development

# ===== MySQL (Compose)
DB_ROOT_PASSWORD=rootpass
```

2) 起動
```
docker compose -f docker-compose.local.yml up --build
```

3) 確認
- Backend: `http://127.0.0.1:8000/health`

4) 停止
```
docker compose -f docker-compose.local.yml down
```

5) テストデータの挿入（オプション）
```
# コンテナ内で実行
docker exec -it ppt-backend bash
python seed_test_data.py
```

注意
- このDocker構成はローカル検証向けです。本番環境（ConoHaVPS）では使用しません。
- 本番環境では `deployment/` の systemd 構成を使用してください。
- DB初期化/マイグレーションが必要な場合は、コンテナ内で `alembic upgrade head` を実行してください。
- `seed_test_data.py` はローカル開発用です。本番環境では使用しないでください。

