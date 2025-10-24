# Prompt Provision Tool - システム仕様書

## 📋 目次

1. [システム概要](#システム概要)
2. [アーキテクチャ](#アーキテクチャ)
3. [データベース設計](#データベース設計)
4. [機能仕様](#機能仕様)
5. [API仕様](#api仕様)
6. [セキュリティ機能](#セキュリティ機能)
7. [使い方](#使い方)

---

## システム概要

### 目的
**プロンプトを外部に漏らさず、AI実行機能のみを提供するシステム**

### 主要機能
- ✅ プロンプトの暗号化保存
- ✅ ユーザー管理（管理者/子アカウント）
- ✅ プロンプトの割り当て管理
- ✅ OpenAI / Gemini API連携
- ✅ 実行ログの記録
- ✅ レート制限

### 技術スタック

#### バックエンド
- **フレームワーク**: FastAPI 0.104.1
- **データベース**: MySQL 8.0+
- **ORM**: SQLAlchemy 2.0.23
- **認証**: JWT (python-jose)
- **暗号化**: cryptography (Fernet)
- **AI API**: OpenAI, Google Gemini

#### フロントエンド
- **基盤**: HTML5, CSS3, JavaScript (Vanilla)
- **スタイル**: カスタムCSS（レスポンシブデザイン）
- **API通信**: Fetch API

---

## アーキテクチャ

```
┌─────────────────────────────────────────────────────────┐
│                     フロントエンド                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │  管理者画面   │  │ ユーザー画面  │  │  共通UI/JS   │ │
│  └──────────────┘  └──────────────┘  └──────────────┘ │
└─────────────────────────────────────────────────────────┘
                          ↓ HTTPS/JWT
┌─────────────────────────────────────────────────────────┐
│                   FastAPI バックエンド                    │
│  ┌────────────────────────────────────────────────────┐ │
│  │              API エンドポイント                      │ │
│  │  /api/auth  /api/admin  /api/user  /api/execute  │ │
│  └────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────┐ │
│  │          ビジネスロジック層                          │ │
│  │  認証  暗号化  プロンプト管理  実行管理  統計        │ │
│  └────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────┐ │
│  │              外部サービス連携                        │ │
│  │      OpenAI Service    Gemini Service             │ │
│  └────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
                ↓                           ↓
         ┌──────────┐              ┌────────────────┐
         │  MySQL   │              │  AI API        │
         │ Database │              │ OpenAI/Gemini  │
         └──────────┘              └────────────────┘
```

---

## データベース設計

### ER図

```
┌─────────────────┐
│    accounts     │
├─────────────────┤
│ id (PK)         │
│ username (UQ)   │
│ email (UQ)      │
│ hashed_password │
│ account_type    │◄──┐
│ is_active       │   │
│ created_at      │   │
│ updated_at      │   │
└─────────────────┘   │
         │            │
         │ 1:N        │
         ↓            │
┌─────────────────┐   │
│account_prompts  │   │
├─────────────────┤   │
│ id (PK)         │   │
│ account_id (FK) │───┘
│ prompt_id (FK)  │───┐
│ assigned_at     │   │
└─────────────────┘   │
         ↑            │
         │ N:1        │
         │            │
┌─────────────────┐   │
│    prompts      │   │
├─────────────────┤   │
│ id (PK)         │◄──┘
│ name            │
│ description     │
│ encrypted_content│  ← 🔒 暗号化
│ model_type      │
│ input_schema    │  ← JSON Schema
│ is_active       │
│ created_by (FK) │
│ created_at      │
│ updated_at      │
└─────────────────┘
         │
         │ 1:N
         ↓
┌─────────────────┐
│   executions    │  ← 実行ログ
├─────────────────┤
│ id (PK)         │
│ account_id (FK) │
│ prompt_id (FK)  │
│ input_data      │  ← ユーザー入力
│ output_data     │  ← AI出力
│ model_used      │
│ tokens_used     │
│ execution_time  │
│ status          │
│ error_message   │
│ executed_at     │
└─────────────────┘

┌─────────────────┐
│  api_configs    │  ← API設定
├─────────────────┤
│ id (PK)         │
│ account_id (FK) │─┐
│ openai_api_key  │ │ 1:1
│ gemini_api_key  │ │
│ rate_limit_ph   │ └─► accounts
│ rate_limit_pd   │
│ is_enabled      │
│ created_at      │
│ updated_at      │
└─────────────────┘
```

### テーブル詳細

#### 1. `accounts` テーブル

| カラム名 | データ型 | 制約 | 説明 |
|---------|---------|------|-----|
| id | INT | PK, AUTO_INCREMENT | アカウントID |
| username | VARCHAR(100) | UNIQUE, NOT NULL, INDEX | ユーザー名 |
| email | VARCHAR(255) | UNIQUE, NOT NULL, INDEX | メールアドレス |
| hashed_password | VARCHAR(255) | NOT NULL | ハッシュ化パスワード（bcrypt） |
| account_type | ENUM('PARENT', 'CHILD') | NOT NULL | アカウント種別 |
| is_active | BOOLEAN | NOT NULL, DEFAULT TRUE | 有効/無効フラグ |
| created_at | DATETIME | NOT NULL, DEFAULT NOW() | 作成日時 |
| updated_at | DATETIME | ON UPDATE NOW() | 更新日時 |

**インデックス**:
- PRIMARY KEY (id)
- UNIQUE INDEX (username)
- UNIQUE INDEX (email)

**アカウント種別**:
- `PARENT`: 管理者（プロンプト作成・ユーザー管理）
- `CHILD`: 子アカウント（プロンプト実行のみ）

---

#### 2. `prompts` テーブル

| カラム名 | データ型 | 制約 | 説明 |
|---------|---------|------|-----|
| id | INT | PK, AUTO_INCREMENT | プロンプトID |
| name | VARCHAR(255) | NOT NULL, INDEX | プロンプト名 |
| description | TEXT | NULL | 説明 |
| encrypted_content | TEXT | NOT NULL | 暗号化プロンプト（Fernet） |
| model_type | VARCHAR(100) | NOT NULL | AIモデル種別 |
| input_schema | TEXT | NULL | JSON Schema（入力定義） |
| is_active | BOOLEAN | NOT NULL, DEFAULT TRUE | 有効/無効フラグ |
| created_by | INT | FK, NOT NULL | 作成者ID (accounts.id) |
| created_at | DATETIME | NOT NULL, DEFAULT NOW() | 作成日時 |
| updated_at | DATETIME | ON UPDATE NOW() | 更新日時 |

**外部キー**:
- created_by → accounts(id)

**対応モデル**:
- `gpt-4`: GPT-4
- `gpt-4-turbo-preview`: GPT-4 Turbo
- `gpt-5-pro`: GPT-5 Pro（将来対応）
- `gemini-pro`: Gemini Pro
- `gemini-2.5-pro`: Gemini 2.5 Pro
- `gemini-2.5-pro-deep-think`: Gemini Deep Think

**input_schema 例**:
```json
{
  "type": "object",
  "properties": {
    "text": {
      "type": "string",
      "title": "要約する文章",
      "description": "要約したい長文を入力してください"
    }
  },
  "required": ["text"]
}
```

---

#### 3. `account_prompts` テーブル（中間テーブル）

| カラム名 | データ型 | 制約 | 説明 |
|---------|---------|------|-----|
| id | INT | PK, AUTO_INCREMENT | ID |
| account_id | INT | FK, NOT NULL | アカウントID |
| prompt_id | INT | FK, NOT NULL | プロンプトID |
| assigned_at | DATETIME | NOT NULL, DEFAULT NOW() | 割り当て日時 |

**外部キー**:
- account_id → accounts(id) ON DELETE CASCADE
- prompt_id → prompts(id) ON DELETE CASCADE

**制約**:
- UNIQUE (account_id, prompt_id)

---

#### 4. `executions` テーブル

| カラム名 | データ型 | 制約 | 説明 |
|---------|---------|------|-----|
| id | INT | PK, AUTO_INCREMENT | 実行ID |
| account_id | INT | FK, NOT NULL | アカウントID |
| prompt_id | INT | FK, NULL | プロンプトID |
| input_data | TEXT | NULL | ユーザー入力（JSON） |
| output_data | TEXT | NULL | AI出力 |
| model_used | VARCHAR(100) | NULL | 使用モデル |
| tokens_used | INT | NULL | 使用トークン数 |
| execution_time | INT | NULL | 実行時間（ミリ秒） |
| status | VARCHAR(50) | NULL | ステータス |
| error_message | TEXT | NULL | エラーメッセージ |
| executed_at | DATETIME | NOT NULL, DEFAULT NOW() | 実行日時 |

**外部キー**:
- account_id → accounts(id) ON DELETE CASCADE
- prompt_id → prompts(id) ON DELETE SET NULL

**ステータス**:
- `success`: 成功
- `error`: エラー
- `timeout`: タイムアウト

---

#### 5. `api_configs` テーブル

| カラム名 | データ型 | 制約 | 説明 |
|---------|---------|------|-----|
| id | INT | PK, AUTO_INCREMENT | 設定ID |
| account_id | INT | FK, UNIQUE, NOT NULL | アカウントID |
| openai_api_key | VARCHAR(255) | NULL | OpenAI APIキー |
| gemini_api_key | VARCHAR(255) | NULL | Gemini APIキー |
| rate_limit_per_hour | INT | DEFAULT 100 | 時間当たり制限 |
| rate_limit_per_day | INT | DEFAULT 1000 | 日当たり制限 |
| is_enabled | BOOLEAN | NOT NULL, DEFAULT TRUE | 有効/無効 |
| created_at | DATETIME | NOT NULL, DEFAULT NOW() | 作成日時 |
| updated_at | DATETIME | ON UPDATE NOW() | 更新日時 |

**外部キー**:
- account_id → accounts(id) ON DELETE CASCADE

---

## 機能仕様

### 1. 認証機能

#### ログイン
- **エンドポイント**: `POST /api/auth/login`
- **入力**: username, password
- **出力**: JWT access_token
- **有効期限**: 7日間

#### 認証方式
- JWT（JSON Web Token）
- Bearer認証
- トークンに含まれる情報:
  - username
  - account_type
  - exp（有効期限）

---

### 2. 管理者機能

#### 2.1 ダッシュボード
- **画面**: `/static/admin/dashboard.html`
- **表示内容**:
  - 総アカウント数
  - 総プロンプト数
  - 総実行回数
  - 今日の実行回数
  - 今月の実行回数

#### 2.2 アカウント管理
- **画面**: `/static/admin/accounts.html`
- **機能**:
  - アカウント一覧表示
  - 新規アカウント作成（PARENT/CHILD）
  - アカウント編集（メール、パスワード）
  - アカウント有効/無効化
  - アカウント削除
  - アカウントごとのプロンプト数・実行数表示

**API**:
```
GET    /api/admin/accounts           # 一覧取得
POST   /api/admin/accounts           # 作成
GET    /api/admin/accounts/:id       # 詳細取得
PUT    /api/admin/accounts/:id       # 更新
DELETE /api/admin/accounts/:id       # 削除
```

#### 2.3 プロンプト管理
- **画面**: `/static/admin/prompts.html`
- **機能**:
  - プロンプト一覧表示
  - 新規プロンプト作成
  - プロンプト編集
  - プロンプト削除
  - プロンプト有効/無効化
  - アカウントへの割り当て管理

**プロンプト作成フォーム**:
```
名前:        [プロンプト名]
説明:        [プロンプトの説明]
モデル:      [GPT-4 / GPT-4 Turbo / Gemini Pro / ...]
プロンプト:  [実際のプロンプトテキスト]
             ※ {variable_name} でプレースホルダー指定
Input Schema: [JSON Schemaで入力定義]
```

**API**:
```
GET    /api/admin/prompts            # 一覧取得
POST   /api/admin/prompts            # 作成
GET    /api/admin/prompts/:id        # 詳細取得
PUT    /api/admin/prompts/:id        # 更新
DELETE /api/admin/prompts/:id        # 削除
```

#### 2.4 プロンプト割り当て
- **機能**:
  - アカウントにプロンプトを割り当て
  - 割り当て解除
  - 割り当て一覧表示

**API**:
```
POST   /api/admin/account-prompts/assign    # 割り当て
DELETE /api/admin/account-prompts/:id       # 解除
GET    /api/admin/accounts/:id/prompts      # アカウントのプロンプト一覧
```

#### 2.5 実行ログ閲覧
- **画面**: `/static/admin/logs.html`
- **機能**:
  - 全アカウントの実行ログ閲覧
  - フィルタリング（アカウント、プロンプト、日付）
  - ページネーション

**API**:
```
GET /api/admin/executions?page=1&limit=50
GET /api/admin/executions?account_id=1
GET /api/admin/executions?prompt_id=2
```

---

### 3. ユーザー機能（子アカウント）

#### 3.1 ダッシュボード
- **画面**: `/static/user/dashboard.html`
- **表示内容**:
  - 自分に割り当てられたプロンプト一覧
  - 各プロンプトの基本情報（名前、説明、モデル）
  - 実行ボタン

**API**:
```
GET /api/user/prompts    # 自分に割り当てられたプロンプト
```

#### 3.2 プロンプト実行
- **画面**: `/static/user/execute.html?id=:prompt_id`
- **機能**:
  - プロンプト詳細表示
  - 動的フォーム生成（input_schemaに基づく）
  - プロンプト実行
  - 結果表示（出力、モデル、実行時間、トークン数）

**フロー**:
1. プロンプト詳細取得
2. input_schemaに基づいてフォーム生成
3. ユーザーが入力
4. サーバー側でプロンプトと入力を結合
5. AI APIに送信
6. 結果を返却・表示

**API**:
```
GET  /api/user/prompts/:id     # プロンプト詳細（暗号化内容は含まない）
POST /api/execute               # プロンプト実行
```

#### 3.3 実行履歴
- **画面**: `/static/user/history.html`
- **機能**:
  - 自分の実行ログ閲覧
  - 入力・出力・実行時間・トークン数の確認
  - ページネーション

**API**:
```
GET /api/user/executions?page=1&limit=50
```

---

### 4. プロンプト実行フロー

```
[フロントエンド]
   ↓ ① プロンプト詳細取得
GET /api/user/prompts/1
   ↓ レスポンス: { name, description, model_type, input_schema }
   ↓ ② input_schemaからフォーム動的生成
   ↓ ③ ユーザーが入力
   ↓ ④ 実行リクエスト
POST /api/execute
{
  "prompt_id": 1,
  "input_data": {
    "text": "要約してほしい文章"
  }
}
   ↓
[バックエンド]
   ↓ ⑤ プロンプト取得 & アクセス権確認
   ↓ ⑥ プロンプト復号化
   ↓    encrypted_content → decrypted_content
   ↓ ⑦ プレースホルダー置換
   ↓    {text} → "要約してほしい文章"
   ↓ ⑧ AI API呼び出し
   ↓    OpenAI / Gemini
   ↓ ⑨ 実行ログ保存
   ↓ ⑩ レスポンス返却
{
  "output": "要約結果...",
  "model_used": "gpt-4",
  "tokens_used": 256,
  "execution_time": 3500,
  "status": "success"
}
```

---

## API仕様

### 認証エンドポイント

#### POST /api/auth/login
**リクエスト**:
```http
POST /api/auth/login
Content-Type: multipart/form-data

username=admin&password=password123
```

**レスポンス**:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

---

### 管理者エンドポイント

#### GET /api/admin/dashboard
**ヘッダー**:
```
Authorization: Bearer {token}
```

**レスポンス**:
```json
{
  "total_accounts": 10,
  "total_prompts": 25,
  "total_executions": 1500,
  "executions_today": 45,
  "executions_this_month": 678
}
```

#### POST /api/admin/accounts
**リクエスト**:
```json
{
  "username": "user1",
  "email": "user1@example.com",
  "password": "password123",
  "account_type": "CHILD"
}
```

**レスポンス**:
```json
{
  "id": 5,
  "username": "user1",
  "email": "user1@example.com",
  "account_type": "CHILD",
  "is_active": true,
  "created_at": "2025-10-23T10:00:00"
}
```

#### POST /api/admin/prompts
**リクエスト**:
```json
{
  "name": "文章要約プロンプト",
  "description": "長文を簡潔に要約します",
  "model_type": "gpt-4",
  "content": "あなたは優秀な要約アシスタントです。\n以下の文章を読んで、重要なポイントを3-5点にまとめて要約してください。\n\n【文章】\n{text}\n\n【要約のポイント】\n- 主要な情報を漏らさない\n- 簡潔で分かりやすく\n- 箇条書きで出力",
  "input_schema": {
    "type": "object",
    "properties": {
      "text": {
        "type": "string",
        "title": "要約する文章",
        "description": "要約したい長文を入力してください"
      }
    },
    "required": ["text"]
  }
}
```

**レスポンス**:
```json
{
  "id": 1,
  "name": "文章要約プロンプト",
  "description": "長文を簡潔に要約します",
  "model_type": "gpt-4",
  "input_schema": { ... },
  "is_active": true,
  "created_by": 1,
  "created_at": "2025-10-23T10:00:00"
}
```

---

### ユーザーエンドポイント

#### GET /api/user/prompts
**ヘッダー**:
```
Authorization: Bearer {token}
```

**レスポンス**:
```json
[
  {
    "id": 1,
    "name": "文章要約プロンプト",
    "description": "長文を簡潔に要約します",
    "model_type": "gpt-4"
  },
  {
    "id": 2,
    "name": "コード生成プロンプト",
    "description": "仕様からコードを生成します",
    "model_type": "gpt-4-turbo-preview"
  }
]
```

#### GET /api/user/prompts/:id
**レスポンス**:
```json
{
  "id": 1,
  "name": "文章要約プロンプト",
  "description": "長文を簡潔に要約します",
  "model_type": "gpt-4",
  "input_schema": {
    "type": "object",
    "properties": {
      "text": {
        "type": "string",
        "title": "要約する文章",
        "description": "要約したい長文を入力してください"
      }
    },
    "required": ["text"]
  }
}
```

---

### 実行エンドポイント

#### POST /api/execute
**リクエスト**:
```json
{
  "prompt_id": 1,
  "input_data": {
    "text": "人工知能（AI）技術は近年、急速に発展しています。機械学習やディープラーニングの進歩により、画像認識、音声認識、自然言語処理などの分野で実用化が進んでいます。"
  }
}
```

**レスポンス**:
```json
{
  "output": "- 人工知能技術は急速に発展している\n- 機械学習とディープラーニングが進歩\n- 画像認識、音声認識、自然言語処理で実用化",
  "model_used": "gpt-4",
  "tokens_used": 256,
  "execution_time": 3500,
  "status": "success"
}
```

**エラーレスポンス**:
```json
{
  "detail": "AI実行エラー: OpenAI API実行エラー: Rate limit exceeded"
}
```

---

## セキュリティ機能

### 1. プロンプト暗号化
- **方式**: Fernet（対称鍵暗号）
- **キー管理**: 環境変数 `ENCRYPTION_KEY`
- **暗号化対象**: プロンプトの本文（`prompts.encrypted_content`）
- **復号化**: サーバー側のみ（クライアントには送信しない）

### 2. パスワード保護
- **ハッシュ化**: bcrypt
- **ストレッチング**: 自動（bcryptのデフォルト）
- **ソルト**: ユーザーごとにランダム生成

### 3. JWT認証
- **署名アルゴリズム**: HS256
- **有効期限**: 7日間
- **含まれる情報**:
  - username
  - account_type（PARENT/CHILD）
  - exp（有効期限）

### 4. CORS設定
- 許可オリジン: 環境変数 `CORS_ORIGINS`
- 認証情報送信: 許可
- 許可メソッド: すべて
- 許可ヘッダー: すべて

### 5. レート制限（将来実装）
- 時間当たり制限: `api_configs.rate_limit_per_hour`
- 日当たり制限: `api_configs.rate_limit_per_day`

---

## 使い方

### 管理者の使い方

#### 1. 初回セットアップ
```bash
# 1. 管理者アカウント作成（初回のみ）
mysql -u root -p prompt_provision_db
INSERT INTO accounts (username, email, hashed_password, account_type) 
VALUES ('admin', 'admin@example.com', '$2b$12$...', 'PARENT');
```

#### 2. ログイン
1. `http://your-domain/static/admin/login.html` にアクセス
2. ユーザー名: `admin`
3. パスワード: 設定したパスワード

#### 3. 子アカウント作成
1. ダッシュボード → 「アカウント管理」
2. 「新規アカウント作成」ボタン
3. 情報を入力:
   - ユーザー名: `user1`
   - メール: `user1@example.com`
   - パスワード: `user123`
   - アカウント種別: `CHILD`

#### 4. プロンプト作成
1. 「プロンプト管理」
2. 「新規プロンプト作成」ボタン
3. 情報を入力:

**例: 文章要約プロンプト**
```
名前: 文章要約プロンプト
説明: 長文を3-5点に要約します

モデル: gpt-4

プロンプト内容:
あなたは優秀な要約アシスタントです。
以下の文章を読んで、重要なポイントを3-5点にまとめて要約してください。

【文章】
{text}

【要約のポイント】
- 主要な情報を漏らさない
- 簡潔で分かりやすく
- 箇条書きで出力

Input Schema:
{
  "type": "object",
  "properties": {
    "text": {
      "type": "string",
      "title": "要約する文章",
      "description": "要約したい長文を入力してください"
    }
  },
  "required": ["text"]
}
```

#### 5. プロンプト割り当て
1. 「アカウント管理」
2. 対象アカウントの「プロンプト割り当て」ボタン
3. 割り当てたいプロンプトを選択
4. 「割り当て」ボタン

---

### ユーザーの使い方

#### 1. ログイン
1. `http://your-domain/static/user/login.html` にアクセス
2. ユーザー名とパスワードを入力

#### 2. プロンプト一覧
- ダッシュボードに自分に割り当てられたプロンプトが表示される

#### 3. プロンプト実行
1. 実行したいプロンプトの「実行」ボタンをクリック
2. 入力フォームが表示される（input_schemaに基づく）
3. 必要な情報を入力
4. 「実行」ボタンをクリック
5. 数秒待つ
6. 結果が表示される:
   - AI出力
   - 使用モデル
   - 実行時間
   - 使用トークン数

#### 4. 実行履歴確認
1. 「実行履歴」メニュー
2. 過去の実行結果を確認
3. 入力・出力・統計情報が表示される

---

## プロンプトテンプレート例

### 1. 文章要約
```
あなたは優秀な要約アシスタントです。
以下の文章を読んで、重要なポイントを3-5点にまとめて要約してください。

【文章】
{text}

【要約のポイント】
- 主要な情報を漏らさない
- 簡潔で分かりやすく
- 箇条書きで出力
```

**input_schema**:
```json
{
  "type": "object",
  "properties": {
    "text": {
      "type": "string",
      "title": "要約する文章"
    }
  },
  "required": ["text"]
}
```

### 2. コード生成
```
あなたは優秀なプログラマーです。
以下の仕様に基づいて、{language}のコードを生成してください。

【仕様】
{task}

【要件】
- コメントを含める
- エラーハンドリングを実装
- ベストプラクティスに従う
```

**input_schema**:
```json
{
  "type": "object",
  "properties": {
    "language": {
      "type": "string",
      "title": "プログラミング言語"
    },
    "task": {
      "type": "string",
      "title": "実装したい機能"
    }
  },
  "required": ["language", "task"]
}
```

### 3. 英文翻訳
```
以下の英文を日本語に翻訳してください。
自然で読みやすい日本語にしてください。

【英文】
{english_text}
```

**input_schema**:
```json
{
  "type": "object",
  "properties": {
    "english_text": {
      "type": "string",
      "title": "英文"
    }
  },
  "required": ["english_text"]
}
```

---

## トラブルシューティング

### プロンプトが実行されない
1. **アクセス権限を確認**
   - 管理者がプロンプトを割り当てているか
   - プロンプトが有効（is_active = true）か

2. **API設定を確認**
   - OpenAI / Gemini APIキーが設定されているか
   - `.env`ファイルの`OPENAI_API_KEY`と`GEMINI_API_KEY`

3. **ログを確認**
   ```bash
   sudo journalctl -u prompt-tool.service -n 100
   ```

### 入力フィールドが表示されない
1. **input_schemaを確認**
   - JSON形式が正しいか
   - `properties`と`required`が定義されているか

2. **ブラウザのキャッシュをクリア**
   ```
   Ctrl+Shift+R (Windows)
   Cmd+Shift+R (Mac)
   ```

### AI応答が正しくない
1. **プロンプトテンプレートを確認**
   - プレースホルダー `{variable_name}` が正しいか
   - 変数名がinput_schemaと一致しているか

2. **入力データを確認**
   - 必須フィールドが入力されているか
   - データ形式が正しいか

---

## まとめ

このシステムは：
✅ プロンプトを暗号化して保護
✅ ユーザーにAI実行機能のみを提供
✅ 実行ログを完全記録
✅ 柔軟な権限管理
✅ 複数AIモデル対応

これにより、**プロンプトを外部に漏らさず、安全にAI機能を提供**できます。

