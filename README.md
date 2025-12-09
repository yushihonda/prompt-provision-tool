# Prompt Provision Tool

プロンプト本文を外部に出さず、AI実行機能を提供するWebアプリケーション。

## 機能/セキュリティ（要点）
- プロンプトは暗号化保存（Fernet）し、復号はサーバ側のみ
- クライアントへ本文を送らず、完成プロンプトはAI APIにのみ送信
- JWT認証（PARENT/CHILDロール）
- ガードレール注入・出力サニタイズ・ログ抑止（漏洩対策）

## 対応モデル
- OpenAI: gpt-5.1（最新モデル） / gpt-5-pro / gpt-5 / gpt-4o-mini
- Google: gemini-3-pro-preview（最新モデル） / gemini-2.5-pro / gemini-2.5-flash / gemini-2.0-flash

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

## データベーススキーマ

### 主要テーブルと制約

#### accounts（アカウントテーブル）
- **プライマリキー**: `id` (Integer, auto increment)
- **ユニーク制約**:
  - `username` (String(100), unique, not null, indexed)
  - `email` (String(255), unique, not null, indexed)
- **その他のカラム**:
  - `hashed_password` (String(255), not null)
  - `account_type` (String(20), not null, default: 'CHILD')
  - `is_active` (Boolean, not null, default: true)
  - `created_at` (DateTime, timezone aware)
  - `updated_at` (DateTime, timezone aware, auto update)

#### prompts（プロンプトテーブル）
- **プライマリキー**: `id` (Integer, auto increment)
- **インデックス**: `name` (String(255), indexed)
- **外部キー**: `created_by` → `accounts.id`
- **その他のカラム**:
  - `encrypted_content` (Text, not null) - 暗号化されたプロンプト内容
  - `model_type` (String(100), not null)
  - `input_schema` (Text) - JSON形式の入力フィールド定義
  - `is_active` (Boolean, not null, default: true)
  - `allows_file_output` (Boolean, not null, default: false)
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
  - `input_data` (Text)
  - `output_data` (Text)
  - `model_used` (String(100))
  - `tokens_used` (Integer)
  - `execution_time` (Integer) - ミリ秒
  - `status` (String(50)) - success, error, timeout
  - `error_message` (Text)
  - `executed_at` (DateTime, timezone aware)

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

本番環境（ConoHa VPS）へのデプロイは `deployment/deploy.sh` スクリプトを使用します。

### デプロイスクリプトの使用方法

```bash
# 本番サーバー上で実行
cd /opt/prompt-provision-tool
sudo bash deployment/deploy.sh
```

### デプロイスクリプトの処理内容

1. Gitから最新のコードを取得（Gitリポジトリが存在する場合）
2. 仮想環境のアクティベート
3. Pythonパッケージの更新
4. データベースマイグレーションの実行
5. アプリケーションの再起動（systemd）
6. サービス状態の確認

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

