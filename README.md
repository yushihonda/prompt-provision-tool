# Prompt Provision Tool

プロンプト本文を外部に出さず、AI実行機能を提供するWebアプリケーション。

## 機能/セキュリティ（要点）
- プロンプトは暗号化保存（Fernet）し、復号はサーバ側のみ
- クライアントへ本文を送らず、完成プロンプトはAI APIにのみ送信
- JWT認証（PARENT/CHILDロール）
- ガードレール注入・出力サニタイズ・ログ抑止（漏洩対策）
- プロンプトの論理削除（物理削除なし、データ保持）
- 実行中のプロンプトのキャンセル機能

## 対応モデル
- **OpenAI**:
  - gpt-5.2（最新モデル）
  - gpt-5.2-pro（GPT-5.2 Pro）
  - gpt-5.2-thinking（思考時間自動調整モデル）
  - gpt-5.1
  - gpt-5.1-thinking（思考時間自動調整モデル）
  - gpt-5-pro
  - gpt-5
  - gpt-4o
  - gpt-4o-mini
- **Google**:
  - gemini-3-pro-preview（最新モデル）
  - gemini-3-pro-preview-deep-think（Deep Think対応）
  - gemini-2.5-pro
  - gemini-2.5-pro-deep-think（Deep Think対応）
  - gemini-2.5-flash
  - gemini-2.0-flash

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

## システム仕様書

### セキュリティキーの要件

#### SECRET_KEY（JWT署名用）
- **用途**: JWTアクセストークンの署名・検証
- **形式**: 任意の文字列（推奨: 32文字以上のhex文字列）
- **生成方法**: `secrets.token_hex(32)` で生成可能
- **例**: `6QgaI2NTUSns12GhPLVb3L6sZtXmG1mjhf8QNYno_vI5AD8CS2U5KV3pRp8yYkKA`
- **要件**: 本番環境では必ず強力なランダム文字列を使用すること

#### ENCRYPTION_KEY（Fernet暗号化用）
- **用途**: プロンプト本文の暗号化・復号化（Fernet方式）
- **形式**: 32バイトの文字列（Base64エンコードされる）
- **生成方法**: `secrets.token_urlsafe(32)[:32]` で生成可能
- **例**: `Yog4ak1a12Y9bBzsbDEIUn/0yTd2BYrZ`
- **要件**: 必ず32文字の文字列であること（システムが自動的にBase64エンコードする）

#### パスワードハッシュ
- **方式**: bcrypt
- **実装**: `passlib.context.CryptContext` を使用
- **保存**: `hashed_password` カラムにハッシュ化されたパスワードを保存

### 認証・認可仕様

#### JWT認証
- **アルゴリズム**: HS256（デフォルト、`ALGORITHM`環境変数で変更可能）
- **有効期限**: `ACCESS_TOKEN_EXPIRE_MINUTES`環境変数で設定（デフォルト: 1440分 = 24時間）
- **トークン形式**: Bearer認証（`Authorization: Bearer <token>`）
- **ペイロード**: `{"sub": username, "exp": expiration_time}`

#### アカウントタイプ
- **PARENT**: 管理者アカウント（全機能アクセス可能）
- **CHILD**: 子アカウント（ユーザー、制限付きアクセス）

#### アクセス制御
- 管理者専用エンドポイント: `get_current_active_parent`依存関数で保護
- 子アカウント専用エンドポイント: `get_current_active_child`依存関数で保護
- アカウント無効化: `is_active=False`の場合、認証は成功するがアクセスは拒否される

### 暗号化仕様

#### プロンプト暗号化
- **方式**: Fernet（symmetric encryption）
- **対象**: `prompts.encrypted_content`カラム
- **処理フロー**:
  1. プロンプト作成時: プレーンテキスト → Fernet暗号化 → Base64エンコード → DB保存
  2. プロンプト取得時: DB取得 → Base64デコード → Fernet復号化 → プレーンテキスト
- **復号場所**: サーバー側のみ（クライアントには送信しない）
- **空文字列処理**: `encrypted_content`が`None`または空文字列の場合は空文字列を返す

### 論理削除仕様

#### プロンプトの論理削除
- **カラム**: `prompts.deleted_at` (DateTime, timezone aware, nullable)
- **削除判定**: `deleted_at IS NULL` → 有効、`deleted_at IS NOT NULL` → 削除済み
- **削除処理**:
  - 削除時: `deleted_at`にJST（日本標準時）の現在時刻を設定
  - 物理削除は行わない（データは保持される）
- **クエリフィルタ**: すべてのプロンプト取得クエリで`Prompt.deleted_at.is_(None)`でフィルタリング
- **影響範囲**:
  - 管理者画面: 論理削除されたプロンプトは一覧に表示されない
  - ユーザー画面: 論理削除されたプロンプトは利用可能なプロンプトに含まれない
  - プロンプト割り当て: 論理削除されたプロンプトは新規割り当て不可（既存割り当ては解除可能）
  - 実行履歴: 既存の実行履歴は保持される（`prompt_id`は`SET NULL`にならない）

### タイムゾーン仕様

#### 使用タイムゾーン
- **標準**: JST（日本標準時、UTC+9）
- **適用箇所**:
  - `executions.executed_at`: 実行日時（JSTで保存）
  - `prompts.deleted_at`: 論理削除日時（JSTで保存）
  - `accounts.last_month_reset`: 月次リセット日時（JSTで保存）
  - 月次集計のリセット判定: JST基準で月初（1日0時0分）を判定

#### 月次リセットロジック
- **リセットタイミング**: 月初（JST基準、1日0時0分）
- **リセット対象**: `tokens_this_month`, `cost_this_month`, `executions_this_month`
- **判定方法**: `last_month_reset`が現在月より前の場合にリセット
- **タイムゾーン処理**: `last_month_reset`がtimezone-naiveの場合はJSTとして解釈

### アカウント統計仕様

#### 統計カラム（accountsテーブル）
- **全期間統計**:
  - `total_tokens`: 総トークン数（Integer, default: 0）
  - `total_cost`: 総料金（Numeric(12, 6), default: 0.0, USD）
  - `total_executions`: 総実行回数（Integer, default: 0）
- **月次統計**:
  - `tokens_this_month`: 今月のトークン数（Integer, default: 0）
  - `cost_this_month`: 今月の料金（Numeric(12, 6), default: 0.0, USD）
  - `executions_this_month`: 今月の実行回数（Integer, default: 0）
  - `last_month_reset`: 最後に月リセットした日時（DateTime, timezone aware, nullable）

#### 統計更新タイミング
- **実行完了時**: `execution_service.py`で自動更新
- **更新内容**:
  1. 月次統計のリセット判定（月初の場合）
  2. 月次統計のインクリメント（`tokens_this_month`, `cost_this_month`, `executions_this_month`）
  3. 全期間統計のインクリメント（`total_tokens`, `total_cost`, `total_executions`）
  4. `last_month_reset`の更新（リセット時のみ）

### 実行ログ仕様

#### executionsテーブル
- **コスト計算**: `calculate_token_cost()`関数でモデル別の単価から計算
- **コスト保存**: `cost`カラム（Numeric(10, 6), USD、小数点以下6桁）
- **Deep Think状態**: `enable_deep_think`カラムで実行時点のDeep Think設定を保存
- **実行日時**: `executed_at`（JSTで保存）
- **ステータス**: `status`カラム（success, error, cancelled, processing）

#### 実行キャンセル機能
- **APIエンドポイント**: `POST /api/execute/{execution_id}/cancel`
- **機能**: 実行中のプロンプトをキャンセル可能
- **制限**: 完了済み（success, error）の実行はキャンセル不可
- **処理**: キャンセル時は`status`を`cancelled`に設定し、料金は0として記録
- **実装**: バックグラウンド実行中に定期的にキャンセル状態をチェックし、キャンセルされた場合は処理を中断

### ガードレール・サニタイズ仕様

#### プロンプトガードレール
- **有効化**: `ENABLE_PROMPT_GUARDRAILS`環境変数で制御（デフォルト: true）
- **実装方式**:
  - OpenAI: systemメッセージとして`GUARDRAIL_PREFIX`を追加
  - Gemini: プロンプトの先頭に`GUARDRAIL_PREFIX`を追加
- **デフォルト内容**: 内部指示・プロンプト・システムメッセージの開示拒否ポリシー
- **カスタマイズ**: `GUARDRAIL_PREFIX`環境変数で内容を変更可能

#### 出力サニタイズ
- **目的**: AI出力からプロンプトテンプレートの漏洩を防止
- **実装**: `sanitize_output()`関数で類似度判定とマスキング
- **パラメータ**:
  - `SANITIZE_MIN_MATCH_LEN`: 最小マッチ長（デフォルト: 60文字）
  - `SANITIZE_SIMILARITY_THRESHOLD`: 類似度閾値（デフォルト: 0.6）
- **処理**: プロンプトテンプレートと類似した出力部分を`[REDACTED]`でマスキング

#### ログ抑止
- **完成プロンプトログ**: `LOG_FINAL_PROMPT`環境変数で制御（デフォルト: false）
- **本番環境**: 完成プロンプトはログに出力しない（漏洩対策）

### ファイル出力仕様

#### 対応形式
- **CSV**: テキストをCSV形式に変換（Excel対応、BOM付きUTF-8）
- **PDF**: ReportLabを使用してPDF生成（A4サイズ、日本語フォント対応）
- **DOCX**: python-docxを使用してWord文書生成（Markdown見出し認識、日本語フォント対応）
- **Markdown**: テキストをそのままMarkdown形式で出力
- **TXT**: プレーンテキスト形式で出力

#### 添付ファイル処理
- **形式**: Base64エンコードまたはプレーンテキスト
- **処理**: Base64デコードに失敗した場合はテキストとして扱う
- **プロンプトへの追加**: 添付ファイルの内容はプロンプトに追加される

### Deep Think機能仕様

#### 対応モデル
- **Gemini 2.5系**: `gemini-2.5-pro`, `gemini-2.5-pro-deep-think`
- **Gemini 3系**: `gemini-3-pro-preview`, `gemini-3-pro-preview-deep-think`
- **設定**: `prompts.enable_deep_think`カラムで有効/無効を制御（デフォルト: true）

#### 実装方式
- **Gemini 2.5系**: 新SDK（`genai`）の`thinking_budget`パラメータを使用
- **Gemini 3系**: 新SDK（`genai`）の`thinking_level`パラメータを使用（"high"）
- **実行時状態**: `executions.enable_deep_think`カラムに実行時点の設定を保存

### API制限仕様

#### レート制限
- **設定場所**: `api_configs`テーブル
- **制限項目**:
  - `rate_limit_per_hour`: 1時間あたりの実行制限（デフォルト: 100）
  - `rate_limit_per_day`: 1日あたりの実行制限（デフォルト: 1000）
- **適用**: 子アカウント（CHILD）のみに適用
- **管理者**: レート制限なし

#### APIキー設定
- **グローバル**: 環境変数`OPENAI_API_KEY`、`GEMINI_API_KEY`で設定
- **個別設定**: `api_configs`テーブルで子アカウントごとに個別のAPIキーを設定可能
- **優先順位**: 個別設定がある場合は個別設定を優先、なければグローバル設定を使用

### データベーススキーマ

### 主要テーブルと制約

#### accounts（アカウントテーブル）
- **プライマリキー**: `id` (Integer, auto increment)
- **ユニーク制約**:
  - `username` (String(100), unique, not null, indexed)
  - `email` (String(255), unique, not null, indexed)
- **その他のカラム**:
  - `hashed_password` (String(255), not null) - bcryptハッシュ
  - `account_type` (String(20), not null, default: 'CHILD')
  - `is_active` (Boolean, not null, default: true)
  - `total_tokens` (Integer, default: 0) - 総トークン数（全期間）
  - `total_cost` (Numeric(12, 6), default: 0.0) - 総料金（USD、全期間）
  - `total_executions` (Integer, default: 0) - 総実行回数（全期間）
  - `tokens_this_month` (Integer, default: 0) - 今月のトークン数
  - `cost_this_month` (Numeric(12, 6), default: 0.0) - 今月の料金（USD）
  - `executions_this_month` (Integer, default: 0) - 今月の実行回数
  - `last_month_reset` (DateTime, timezone aware, nullable) - 最後に月リセットした日時
  - `created_at` (DateTime, timezone aware)
  - `updated_at` (DateTime, timezone aware, auto update)

#### prompts（プロンプトテーブル）
- **プライマリキー**: `id` (Integer, auto increment)
- **インデックス**: `name` (String(255), indexed)
- **外部キー**: `created_by` → `accounts.id`
- **その他のカラム**:
  - `encrypted_content` (Text, not null) - 暗号化されたプロンプト内容（Fernet）
  - `model_type` (String(100), not null)
  - `input_schema` (Text) - JSON形式の入力フィールド定義
  - `is_active` (Boolean, not null, default: true)
  - `allows_file_output` (Boolean, not null, default: false)
  - `enable_deep_think` (Boolean, not null, default: true) - Deep Think機能（Gemini 2.5/3系のみ）
  - `deleted_at` (DateTime, timezone aware, nullable) - 論理削除日時（JST）
  - `created_at`, `updated_at` (DateTime, timezone aware)

#### account_prompts（アカウント-プロンプト紐付けテーブル）
- **プライマリキー**: `id` (Integer, auto increment)
- **外部キー**:
  - `account_id` → `accounts.id` (ondelete: CASCADE)
  - `prompt_id` → `prompts.id` (ondelete: CASCADE)
- **その他のカラム**:
  - `assigned_at` (DateTime, timezone aware)

#### executions（実行ログテーブル）
- **プライマリキー**: `id` (Integer, auto increment)
- **外部キー**:
  - `account_id` → `accounts.id` (ondelete: CASCADE)
  - `prompt_id` → `prompts.id` (ondelete: SET NULL)
- **その他のカラム**:
  - `input_data` (Text) - ユーザー入力データ（JSON形式）
  - `output_data` (Text) - AI出力結果
  - `model_used` (String(100)) - 使用されたAIモデル
  - `tokens_used` (Integer) - 使用トークン数
  - `cost` (Numeric(10, 6), nullable) - トークン料金（USD、小数点以下6桁）
  - `execution_time` (Integer) - 実行時間（ミリ秒）
  - `status` (String(50)) - success, error, timeout
  - `error_message` (Text) - エラーメッセージ
  - `enable_deep_think` (Boolean, nullable) - 実行時点のDeep Think設定状態
  - `executed_at` (DateTime, timezone aware) - 実行日時（JST）

#### api_configs（API設定テーブル）
- **プライマリキー**: `id` (Integer, auto increment)
- **ユニーク制約**: `account_id` (unique, not null)
- **外部キー**: `account_id` → `accounts.id` (ondelete: CASCADE)
- **その他のカラム**:
  - `openai_api_key` (String(255)) - オプション
  - `gemini_api_key` (String(255)) - オプション
  - `rate_limit_per_hour` (Integer, default: 100)
  - `rate_limit_per_day` (Integer, default: 1000)
  - `is_enabled` (Boolean, not null, default: true)
  - `created_at`, `updated_at` (DateTime, timezone aware)

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
  - POST /api/execute/{execution_id}/cancel（実行中のプロンプトをキャンセル）
  - GET /api/execute/download/{execution_id}?output_format={format}

## ファイル出力機能

プロンプト実行結果をCSV、PDF、DOCX、Markdown、TXT形式で出力する機能です。

### 機能概要

- **出力形式**: CSV、PDF、DOCX、Markdown、TXT
- **添付ファイル対応**: プロンプト実行時に複数のファイルを添付可能
- **ファイルダウンロード**: 実行結果を後からファイルとしてダウンロード可能

### API使用方法

#### 1. プロンプト実行時にファイル出力を指定

```json
POST /api/execute
{
  "prompt_id": 1,
  "input_data": {
    "text": "分析したいテキスト..."
  },
  "output_format": "csv",  // csv, pdf, docx, md, txt
  "attachments": [
    {
      "filename": "data.csv",
      "content": "項目名,値\n項目1,100\n項目2,200"
    },
    {
      "filename": "notes.md",
      "content": "# メモ\n\n重要な情報..."
    }
  ]
}
```

**レスポンス例:**
```json
{
  "output": "分析結果のテキスト...",
  "model_used": "gpt-5-pro",
  "tokens_used": 1500,
  "execution_time": 2500,
  "status": "success",
  "file_output": {
    "filename": "output_1_1234567890.csv",
    "content": "base64エンコードされたファイル内容",
    "format": "csv",
    "size": 1024
  }
}
```

#### 2. 実行結果をファイルとしてダウンロード

```
GET /api/execute/download/{execution_id}?output_format=csv
```

**パラメータ:**
- `execution_id`: 実行ID（必須）
- `output_format`: 出力形式（csv, pdf, docx, md, txt、デフォルト: txt）

**レスポンス:**
- Content-Type: ファイル形式に応じたMIMEタイプ
- Content-Disposition: ファイル名を含むダウンロードヘッダー
- ファイルのバイナリデータ

### 出力形式の詳細

#### CSV形式
- テキストをCSV形式に変換
- タブ区切りまたはカンマ区切りを自動検出
- Excel対応（BOM付きUTF-8）

#### PDF形式
- ReportLabを使用してPDF生成
- A4サイズ、適切な余白設定
- 日本語フォント対応

#### DOCX形式
- python-docxを使用してWord文書生成
- Markdown形式の見出しを自動認識
- 日本語フォント対応（游ゴシック）

#### Markdown形式
- テキストをそのままMarkdown形式で出力
- 拡張子: .md

#### TXT形式
- プレーンテキスト形式で出力
- 拡張子: .txt

### 添付ファイルの使用方法

#### テキスト形式で添付

```json
{
  "attachments": [
    {
      "filename": "data.csv",
      "content": "項目名,値\n項目1,100"
    }
  ]
}
```

#### Base64エンコード形式で添付

```json
{
  "attachments": [
    {
      "filename": "data.csv",
      "content": "5byg5LiJ5LiA5LiqLOWApA=="
    }
  ]
}
```

**注意**: Base64デコードに失敗した場合は、テキストとして扱われます。

### 使用例

#### 例1: CSV形式で出力

```bash
curl -X POST "http://localhost:8000/api/execute" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt_id": 1,
    "input_data": {
      "text": "データ分析結果..."
    },
    "output_format": "csv"
  }'
```

#### 例2: PDF形式で出力（添付ファイル付き）

```bash
curl -X POST "http://localhost:8000/api/execute" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt_id": 2,
    "input_data": {
      "data": "商品名,売上高\n商品A,1500000\n商品B,2000000"
    },
    "output_format": "pdf",
    "attachments": [
      {
        "filename": "raw_data.csv",
        "content": "商品名,売上高,販売数量\n商品A,1500000,500\n商品B,2000000,800"
      },
      {
        "filename": "notes.md",
        "content": "# 分析メモ\n\n2024年第1四半期のデータ"
      }
    ]
  }'
```

#### 例3: 実行結果をダウンロード

```bash
curl -X GET "http://localhost:8000/api/execute/download/123?output_format=pdf" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -o output.pdf
```

### エラーハンドリング

- ファイル出力に失敗した場合、テキスト形式で返されます
- サポートされていない形式を指定した場合、`ValueError`が発生します
- 添付ファイルの処理に失敗した場合、警告ログが出力されますが処理は継続されます

### 注意事項

1. **PDF/DOCX生成**: `reportlab`と`python-docx`ライブラリが必要です
2. **ファイルサイズ**: 大きなファイルの場合は、Base64エンコード後のサイズに注意してください
3. **セキュリティ**: 添付ファイルの内容はプロンプトに追加されるため、機密情報には注意してください

### 依存ライブラリ

以下のライブラリが`requirements.txt`に追加されています：
- `reportlab==4.0.7` (PDF生成)
- `python-docx==1.1.0` (DOCX生成)

インストール方法:
```bash
cd backend
pip install -r requirements.txt
```

## 運用
- ヘルスチェック: GET /health
- ログ: systemdやNginx設定は `deployment/` 参照
- 本番要件
  - APIキー設定必須（未設定時は実行エラー）
  - `/docs` 非公開、入力詳細ログ非出力、完成プロンプトログ抑止

## デプロイ（本番環境）

本番環境（ConoHa VPS）へのデプロイには、以下の2つの方法があります：

### 方法1: GitHub Actionsによる自動デプロイ（推奨）

mainブランチにマージすると、自動的に本番サーバーにデプロイされます。

#### セットアップ手順

1. **GitHub Secretsの設定**

   GitHubリポジトリの Settings > Secrets and variables > Actions で以下のSecretsを追加：

   - `SSH_PRIVATE_KEY`: 本番サーバーへのSSH接続用の秘密鍵（`~/.ssh/id_rsa`の内容）
   - `SERVER_HOST`: 本番サーバーのIPアドレスまたはホスト名（例: `160.251.172.234`）
   - `SERVER_USER`: SSH接続用のユーザー名（例: `root`）

2. **SSH鍵の設定**

   本番サーバーで、GitHub ActionsからSSH接続できるように公開鍵を登録：

   ```bash
   # 本番サーバー上で実行
   mkdir -p ~/.ssh
   # GitHub Actionsの公開鍵を authorized_keys に追加
   echo "YOUR_PUBLIC_KEY" >> ~/.ssh/authorized_keys
   chmod 600 ~/.ssh/authorized_keys
   chmod 700 ~/.ssh
   ```

3. **自動デプロイの動作**

   - mainブランチへのpush/マージで自動的にデプロイが開始されます
   - ローカルファイル（`.env`, `venv/`, `__pycache__/`など）は自動的に除外されます
   - デプロイ後、自動的にマイグレーションとサービス再起動が実行されます

#### 除外されるファイル

以下のファイル/ディレクトリは本番環境にデプロイされません：

- `.env`, `.env.local`, `.env.*.local` - 環境変数ファイル
- `venv/` - 仮想環境
- `__pycache__/`, `*.pyc`, `*.pyo` - Pythonキャッシュ
- `*.log` - ログファイル
- `.DS_Store`, `*.swp`, `*.swo` - OS/エディタファイル
- `.vscode/`, `.idea/` - IDE設定
- `backend/uploads/`, `backend/temp/`, `frontend/uploads/` - アップロードファイル
- `docker-compose.local.yml` - ローカル開発用Docker Compose
- `資料/` - ドキュメント

### 方法2: 手動デプロイ（非推奨）

GitHub Actionsによる自動デプロイを推奨します。手動でデプロイする場合は、本番サーバーにSSH接続して以下を実行してください：

```bash
# 本番サーバー上で実行
cd /opt/prompt-provision-tool/backend
source /opt/prompt-provision-tool/venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
alembic upgrade head
sudo systemctl restart prompt-tool.service
```

### デプロイ前の確認事項

- 環境変数（`.env`）が正しく設定されているか
- データベースのバックアップが取得されているか（必要に応じて）
- マイグレーションスクリプトが最新であるか

### ログの確認

デプロイ後、以下のコマンドでログを確認できます：

```bash
# アプリケーションログ
sudo tail -f /var/log/prompt-tool/app.log

# エラーログ
sudo tail -f /var/log/prompt-tool/error.log

# systemdサービスの状態
sudo systemctl status prompt-tool
```

## Git管理

### リポジトリの初期化（初回のみ）

```bash
cd /Users/hondayushi/workspaece/poifull/prompt-provision-tool
git init
git add .
git commit -m "Initial commit: Prompt Provision Tool"
```

### リモートリポジトリの設定

```bash
# リモートリポジトリを追加（例：GitHub）
git remote add origin https://github.com/your-username/prompt-provision-tool.git

# またはSSHを使用する場合
git remote add origin git@github.com:your-username/prompt-provision-tool.git
```

### 変更のコミットとプッシュ

```bash
# 変更をステージング
git add .

# コミット
git commit -m "コミットメッセージ"

# リモートにプッシュ
git push origin main
# または master ブランチの場合
git push origin master
```

### .gitignore の推奨設定

以下のファイル・ディレクトリはGit管理から除外することを推奨します：

```
# 環境変数ファイル
.env
.env.local
.env.production

# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
venv/
env/
ENV/

# ログファイル
*.log
app.log

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# その他
*.zip
prompt-provision-tool.zip

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

5) 初期管理者アカウントの作成
```
# コンテナ内で実行
docker exec -it ppt-backend bash
python -m app.init_admin
```

注意
- このDocker構成はローカル検証向けです。本番環境（ConoHaVPS）では使用しません。
- 本番環境では `deployment/` の systemd 構成を使用してください。
- DB初期化/マイグレーションが必要な場合は、コンテナ内で `alembic upgrade head` を実行してください。

## 更新履歴

### 2024年11月 - 機能追加と改善

#### ユーザーダッシュボード
- プロンプトカードの表示数を9枚に変更（PC表示時）

#### プロンプト管理
- プロンプトの有効/無効ステータスを表示
- プロンプト作成・編集時に有効/無効ステータスを設定可能
- ファイル出力の許可/不可ステータスを表示

#### アカウント管理
- **プロンプト割り当て機能**
  - アカウント管理画面からプロンプトの割り当て・解除が可能
  - 割り当て可能なプロンプトと割り当て済みプロンプトを分けて表示
  - 無効化されたプロンプトは新規割り当て不可（既存の割り当ては解除可能）
- **ユーザー編集機能**
  - アカウント情報の編集機能を追加
  - メールアドレス、パスワード、ステータス（有効/無効）の変更が可能
  - ユーザー名は変更不可
- **管理者表示**
  - 管理者（親アカウント）もアカウント一覧に表示
  - 管理者のプロンプト割り当て機能と削除機能を無効化

#### エラーハンドリングの改善
- FastAPIのバリデーションエラーの詳細を表示
- フロントエンド側でメールアドレスの形式チェックを追加

#### その他の改善
- デバッグログの削除
- プロンプト数の計算ロジックを修正（重複カウントを解消）
- アカウント管理画面のパスワード列を削除（セキュリティ向上）

## 画面ごとの詳細機能

### 管理者画面

#### ログイン画面 (`admin/login.html`)
- ユーザー名とパスワードによる認証
- JWTトークンによるセッション管理
- 認証エラー時のエラーメッセージ表示

#### ダッシュボード (`admin/dashboard.html`)
- **統計情報の表示**
  - 総アカウント数（子アカウントのみ）
  - 総プロンプト数
  - 総実行回数
  - 今日の実行回数
  - 今月の実行回数
- **ナビゲーション**
  - プロンプト管理、アカウント管理、実行ログへの遷移

#### プロンプト管理 (`admin/prompts.html`)
- **プロンプト一覧表示**
  - ページネーション対応（1ページ10件）
  - ID、プロンプト名、説明、モデル、ステータス、ファイル出力の表示
- **プロンプト作成**
  - プロンプト名、説明、AIモデル、プロンプト内容の入力
  - 入力スキーマ（JSON形式）の設定
  - 有効/無効ステータスの設定
  - ファイル出力許可の設定
- **プロンプト編集**
  - 既存プロンプトの情報を編集
  - プロンプト内容、入力スキーマ、ステータス、ファイル出力設定の変更
- **プロンプト削除**
  - 削除確認ダイアログ表示
  - プロンプトの削除処理
- **プロンプト内容表示**
  - プロンプトの詳細内容を表示（暗号化された内容を復号して表示）
- **ステータス切り替え**
  - プロンプトの有効/無効を切り替え

#### アカウント管理 (`admin/accounts.html`)
- **アカウント一覧表示**
  - ページネーション対応（1ページ10件）
  - ID、ユーザー名、メールアドレス、タイプ（管理者/ユーザー）、ステータス、プロンプト数、実行回数の表示
- **アカウント作成**
  - ユーザー名、メールアドレス、パスワード、アカウントタイプ（管理者/ユーザー）の入力
  - メールアドレスの形式バリデーション
- **アカウント編集**
  - メールアドレスの変更
  - パスワードの変更（変更する場合のみ入力）
  - ステータス（有効/無効）の変更
  - ユーザー名は変更不可
- **アカウント削除**
  - 削除確認ダイアログ表示
  - 管理者（親アカウント）は削除不可
- **プロンプト割り当て**
  - アカウントにプロンプトを割り当て
  - 割り当て済みプロンプトの解除
  - 割り当て可能なプロンプト（有効なプロンプトのみ）と割り当て済みプロンプトを分けて表示
  - 無効化されたプロンプトは新規割り当て不可（既存の割り当ては解除可能）
  - 管理者（親アカウント）はプロンプト割り当て不可

#### 実行ログ (`admin/executions.html`)
- **実行ログ一覧表示**
  - ページネーション対応（1ページ10件）
  - ID、実行日時、アカウントID、プロンプト名、モデル、実行時間、トークン数、ステータスの表示
- **実行ログ詳細表示**
  - 実行日時、アカウント情報、プロンプト情報、使用モデル、入力データ、出力データ、実行時間、トークン数の表示
  - ファイル出力がある場合はダウンロードリンクを表示

### ユーザー画面

#### ログイン画面 (`user/login.html`)
- ユーザー名とパスワードによる認証
- JWTトークンによるセッション管理
- 認証エラー時のエラーメッセージ表示

#### ダッシュボード (`user/dashboard.html`)
- **統計情報の表示**
  - 利用可能なプロンプト数
  - 総実行回数
  - 今日の実行回数
  - 今月の実行回数
- **プロンプト一覧表示**
  - ページネーション対応（PC表示時は9件、タブレット・モバイルは自動調整）
  - プロンプト名、説明、モデルの表示
  - プロンプトカードをクリックして実行画面へ遷移
- **プロンプト検索**
  - プロンプト名や説明での検索機能

#### プロンプト実行 (`user/execute.html`)
- **プロンプト情報表示**
  - プロンプト名、説明、使用モデルの表示
- **入力フォーム生成**
  - プロンプトの入力スキーマに基づいて動的に入力フィールドを生成
  - テキスト入力、数値入力、選択肢などの各種フィールドタイプに対応
- **ファイル出力設定**
  - プロンプトがファイル出力を許可している場合、出力形式を選択可能（TXT、CSV、PDF、DOCX、MD）
- **プロンプト実行**
  - 入力データを送信してプロンプトを実行
  - 実行中のローディング表示
  - 実行結果の表示
  - エラー時のエラーメッセージ表示
  - **実行中のキャンセル機能**（実行中に停止ボタンでキャンセル可能）
- **実行結果の操作**
  - 実行結果のコピー機能
  - ファイル出力がある場合はダウンロードリンクを表示
- **実行履歴表示**
  - このプロンプトの過去の実行履歴を表示（最新3件、もっと見るで追加表示）
  - 実行日時、モデル、実行時間、トークン数、ステータスの表示
  - 履歴の詳細表示
  - 過去の実行結果を再編集・再実行可能

#### 実行履歴 (`user/history.html`)
- **実行履歴一覧表示**
  - ページネーション対応（1ページ10件）
  - 実行日時、プロンプト名、モデル、実行時間、トークン数、ステータスの表示
- **実行履歴詳細表示**
  - 実行日時、プロンプト情報、使用モデル、入力データ、出力データ、実行時間、トークン数の表示
  - ファイル出力がある場合はダウンロードリンクを表示
- **実行結果の再編集・再実行**
  - 過去の実行結果を編集して再実行可能

