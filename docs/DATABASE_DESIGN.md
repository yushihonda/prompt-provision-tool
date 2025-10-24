# データベース設計詳細

## 📊 概要

このドキュメントは、Prompt Provision Tool のデータベース設計の詳細を説明します。

---

## ER図（Entity-Relationship Diagram）

```
                    ┌─────────────────────────────────┐
                    │         accounts                │
                    ├─────────────────────────────────┤
                    │ id (PK)                         │
                    │ username (UNIQUE)               │
                    │ email (UNIQUE)                  │
                    │ hashed_password                 │
                    │ account_type (ENUM)             │
                    │ is_active                       │
                    │ created_at                      │
                    │ updated_at                      │
                    └─────────────────────────────────┘
                       │                    │
                       │1                   │1
                       │                    │
        ┌──────────────┤                    ├──────────────┐
        │              │                    │              │
        │N             │                    │1             │
        │              │                    │              │
┌───────▼──────┐  ┌───▼────────────┐  ┌───▼────────────┐
│  executions  │  │account_prompts │  │  api_configs   │
├──────────────┤  ├────────────────┤  ├────────────────┤
│ id (PK)      │  │ id (PK)        │  │ id (PK)        │
│ account_id FK│  │ account_id FK  │  │ account_id FK  │
│ prompt_id FK │  │ prompt_id FK   │  │ openai_api_key │
│ input_data   │  │ assigned_at    │  │ gemini_api_key │
│ output_data  │  └────────────────┘  │ rate_limit_ph  │
│ model_used   │         │N            │ rate_limit_pd  │
│ tokens_used  │         │             │ is_enabled     │
│ execution_   │         │             └────────────────┘
│   time       │         │
│ status       │         │
│ error_msg    │         │1
│ executed_at  │         │
└──────────────┘  ┌──────▼──────────┐
        ▲         │    prompts      │
        │N        ├─────────────────┤
        │         │ id (PK)         │
        └─────────┤ name            │
                  │ description     │
                  │ encrypted_      │
                  │   content       │◄──── 🔒 暗号化
                  │ model_type      │
                  │ input_schema    │◄──── JSON Schema
                  │ is_active       │
                  │ created_by FK   │─────┐
                  │ created_at      │     │
                  │ updated_at      │     │
                  └─────────────────┘     │
                          └───────────────┘
                              (自己参照)
```

---

## テーブル定義

### 1. accounts テーブル

**目的**: ユーザーアカウント情報を管理

```sql
CREATE TABLE accounts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    account_type ENUM('PARENT', 'CHILD') NOT NULL DEFAULT 'CHILD',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_username (username),
    INDEX idx_email (email),
    INDEX idx_account_type (account_type),
    INDEX idx_is_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

**カラム詳細**:

| カラム | 型 | NULL | デフォルト | 説明 |
|--------|-----|------|-----------|------|
| id | INT | NO | AUTO | 主キー |
| username | VARCHAR(100) | NO | - | ユーザー名（ログイン用） |
| email | VARCHAR(255) | NO | - | メールアドレス |
| hashed_password | VARCHAR(255) | NO | - | bcryptハッシュ化パスワード |
| account_type | ENUM | NO | CHILD | PARENT（管理者）/ CHILD（一般ユーザー） |
| is_active | BOOLEAN | NO | TRUE | アカウント有効/無効 |
| created_at | DATETIME | NO | NOW() | アカウント作成日時 |
| updated_at | DATETIME | YES | - | 最終更新日時 |

**制約**:
- UNIQUE: username, email
- CHECK: account_type IN ('PARENT', 'CHILD')

**サンプルデータ**:
```sql
INSERT INTO accounts (username, email, hashed_password, account_type) VALUES
('admin', 'admin@example.com', '$2b$12$...', 'PARENT'),
('user1', 'user1@example.com', '$2b$12$...', 'CHILD'),
('user2', 'user2@example.com', '$2b$12$...', 'CHILD');
```

---

### 2. prompts テーブル

**目的**: AIプロンプトを暗号化して保存

```sql
CREATE TABLE prompts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    encrypted_content TEXT NOT NULL,
    model_type VARCHAR(100) NOT NULL,
    input_schema TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by INT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME ON UPDATE CURRENT_TIMESTAMP,
    
    FOREIGN KEY (created_by) REFERENCES accounts(id) ON DELETE RESTRICT,
    
    INDEX idx_name (name),
    INDEX idx_model_type (model_type),
    INDEX idx_is_active (is_active),
    INDEX idx_created_by (created_by)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

**カラム詳細**:

| カラム | 型 | NULL | デフォルト | 説明 |
|--------|-----|------|-----------|------|
| id | INT | NO | AUTO | 主キー |
| name | VARCHAR(255) | NO | - | プロンプト名 |
| description | TEXT | YES | - | プロンプトの説明 |
| encrypted_content | TEXT | NO | - | 🔒 暗号化されたプロンプト本文 |
| model_type | VARCHAR(100) | NO | - | AIモデル種別 |
| input_schema | TEXT | YES | - | JSON Schema（入力定義） |
| is_active | BOOLEAN | NO | TRUE | プロンプト有効/無効 |
| created_by | INT | NO | - | 作成者ID（accounts.id） |
| created_at | DATETIME | NO | NOW() | 作成日時 |
| updated_at | DATETIME | YES | - | 更新日時 |

**暗号化方式**:
- **アルゴリズム**: Fernet（対称鍵暗号）
- **キー**: 環境変数 `ENCRYPTION_KEY`
- **復号化**: サーバー側でのみ実行
- **クライアント送信**: なし（セキュリティ）

**対応モデル**:
| model_type | 説明 |
|-----------|------|
| gpt-4 | GPT-4 |
| gpt-4-turbo-preview | GPT-4 Turbo |
| gpt-5-pro | GPT-5 Pro（将来対応） |
| gemini-pro | Gemini Pro |
| gemini-2.5-pro | Gemini 2.5 Pro |
| gemini-2.5-pro-deep-think | Gemini Deep Think |

**input_schema の例**:
```json
{
  "type": "object",
  "properties": {
    "text": {
      "type": "string",
      "title": "要約する文章",
      "description": "要約したい長文を入力してください"
    },
    "length": {
      "type": "string",
      "title": "要約の長さ",
      "description": "short / medium / long"
    }
  },
  "required": ["text"]
}
```

**サンプルデータ**:
```sql
INSERT INTO prompts (name, description, encrypted_content, model_type, input_schema, created_by) VALUES
(
    '文章要約プロンプト',
    '長文を簡潔に要約します',
    'gAAAAABl...', -- 暗号化された内容
    'gpt-4',
    '{"type":"object","properties":{"text":{"type":"string","title":"要約する文章"}},"required":["text"]}',
    1
);
```

---

### 3. account_prompts テーブル（中間テーブル）

**目的**: アカウントとプロンプトの紐付けを管理（多対多関係）

```sql
CREATE TABLE account_prompts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,
    prompt_id INT NOT NULL,
    assigned_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
    FOREIGN KEY (prompt_id) REFERENCES prompts(id) ON DELETE CASCADE,
    
    UNIQUE KEY uk_account_prompt (account_id, prompt_id),
    INDEX idx_account_id (account_id),
    INDEX idx_prompt_id (prompt_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

**カラム詳細**:

| カラム | 型 | NULL | デフォルト | 説明 |
|--------|-----|------|-----------|------|
| id | INT | NO | AUTO | 主キー |
| account_id | INT | NO | - | アカウントID |
| prompt_id | INT | NO | - | プロンプトID |
| assigned_at | DATETIME | NO | NOW() | 割り当て日時 |

**制約**:
- UNIQUE: (account_id, prompt_id) - 同じアカウントに同じプロンプトは1回のみ割り当て可能
- CASCADE: アカウントまたはプロンプトが削除されたら、この紐付けも削除

**サンプルデータ**:
```sql
-- user1 に プロンプト1, 2 を割り当て
INSERT INTO account_prompts (account_id, prompt_id) VALUES
(2, 1),  -- user1 → 文章要約プロンプト
(2, 2);  -- user1 → コード生成プロンプト
```

**クエリ例**:
```sql
-- user1 が使えるプロンプト一覧
SELECT p.* 
FROM prompts p
JOIN account_prompts ap ON p.id = ap.prompt_id
WHERE ap.account_id = 2 AND p.is_active = TRUE;

-- プロンプト1を使えるアカウント一覧
SELECT a.* 
FROM accounts a
JOIN account_prompts ap ON a.id = ap.account_id
WHERE ap.prompt_id = 1 AND a.is_active = TRUE;
```

---

### 4. executions テーブル

**目的**: プロンプト実行ログを記録

```sql
CREATE TABLE executions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,
    prompt_id INT,
    input_data TEXT,
    output_data TEXT,
    model_used VARCHAR(100),
    tokens_used INT,
    execution_time INT,
    status VARCHAR(50),
    error_message TEXT,
    executed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
    FOREIGN KEY (prompt_id) REFERENCES prompts(id) ON DELETE SET NULL,
    
    INDEX idx_account_id (account_id),
    INDEX idx_prompt_id (prompt_id),
    INDEX idx_status (status),
    INDEX idx_executed_at (executed_at),
    INDEX idx_account_executed (account_id, executed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

**カラム詳細**:

| カラム | 型 | NULL | デフォルト | 説明 |
|--------|-----|------|-----------|------|
| id | INT | NO | AUTO | 主キー |
| account_id | INT | NO | - | 実行したアカウントID |
| prompt_id | INT | YES | - | 使用したプロンプトID |
| input_data | TEXT | YES | - | ユーザーが入力したデータ（JSON） |
| output_data | TEXT | YES | - | AIが出力した結果 |
| model_used | VARCHAR(100) | YES | - | 使用したAIモデル |
| tokens_used | INT | YES | - | 消費したトークン数 |
| execution_time | INT | YES | - | 実行時間（ミリ秒） |
| status | VARCHAR(50) | YES | - | 実行ステータス |
| error_message | TEXT | YES | - | エラーメッセージ（エラー時のみ） |
| executed_at | DATETIME | NO | NOW() | 実行日時 |

**ステータス値**:
| status | 説明 |
|--------|------|
| success | 正常に完了 |
| error | エラーが発生 |
| timeout | タイムアウト |

**ON DELETE動作**:
- `account_id`: CASCADE - アカウントが削除されたらログも削除
- `prompt_id`: SET NULL - プロンプトが削除されてもログは残す（prompt_idをNULLに）

**サンプルデータ**:
```sql
INSERT INTO executions (
    account_id, prompt_id, input_data, output_data, 
    model_used, tokens_used, execution_time, status
) VALUES (
    2,
    1,
    '{"text":"人工知能は急速に発展しています。"}',
    '1. 人工知能は急速に発展している。',
    'gpt-4',
    156,
    3500,
    'success'
);
```

**統計クエリ例**:
```sql
-- 今日の実行回数
SELECT COUNT(*) 
FROM executions 
WHERE DATE(executed_at) = CURDATE();

-- アカウントごとの実行回数
SELECT account_id, COUNT(*) as count
FROM executions
GROUP BY account_id;

-- プロンプトごとの平均実行時間
SELECT prompt_id, AVG(execution_time) as avg_time
FROM executions
WHERE status = 'success'
GROUP BY prompt_id;

-- 今月のトークン使用量
SELECT SUM(tokens_used) as total_tokens
FROM executions
WHERE YEAR(executed_at) = YEAR(CURDATE())
  AND MONTH(executed_at) = MONTH(CURDATE());
```

---

### 5. api_configs テーブル

**目的**: アカウントごとのAPI設定を管理

```sql
CREATE TABLE api_configs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT UNIQUE NOT NULL,
    openai_api_key VARCHAR(255),
    gemini_api_key VARCHAR(255),
    rate_limit_per_hour INT DEFAULT 100,
    rate_limit_per_day INT DEFAULT 1000,
    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME ON UPDATE CURRENT_TIMESTAMP,
    
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
    
    INDEX idx_account_id (account_id),
    INDEX idx_is_enabled (is_enabled)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

**カラム詳細**:

| カラム | 型 | NULL | デフォルト | 説明 |
|--------|-----|------|-----------|------|
| id | INT | NO | AUTO | 主キー |
| account_id | INT | NO | - | アカウントID（UNIQUE） |
| openai_api_key | VARCHAR(255) | YES | - | 個別のOpenAI APIキー |
| gemini_api_key | VARCHAR(255) | YES | - | 個別のGemini APIキー |
| rate_limit_per_hour | INT | YES | 100 | 1時間あたりの実行制限 |
| rate_limit_per_day | INT | YES | 1000 | 1日あたりの実行制限 |
| is_enabled | BOOLEAN | NO | TRUE | API使用の有効/無効 |
| created_at | DATETIME | NO | NOW() | 作成日時 |
| updated_at | DATETIME | YES | - | 更新日時 |

**用途**:
1. **個別APIキー**: アカウントごとに独自のAPIキーを設定可能
2. **レート制限**: アカウントごとに実行回数を制限
3. **使用制御**: 一時的にAPI使用を無効化

**APIキーの優先順位**:
1. `api_configs.openai_api_key` / `api_configs.gemini_api_key`（個別設定）
2. 環境変数 `OPENAI_API_KEY` / `GEMINI_API_KEY`（グローバル設定）

**サンプルデータ**:
```sql
INSERT INTO api_configs (account_id, rate_limit_per_hour, rate_limit_per_day) VALUES
(2, 50, 500),   -- user1: 時間50回、日500回まで
(3, 100, 1000); -- user2: デフォルト制限
```

---

## データフロー

### 1. プロンプト実行フロー

```
[クライアント]
     │
     │ POST /api/execute
     │ { prompt_id: 1, input_data: {...} }
     ↓
[サーバー]
     │
     ├─→ 1. accounts テーブル: ユーザー認証（JWT）
     │
     ├─→ 2. account_prompts テーブル: アクセス権確認
     │       「このユーザーはこのプロンプトを使える？」
     │
     ├─→ 3. prompts テーブル: プロンプト取得
     │       - encrypted_content を復号化
     │       - input_schema を確認
     │
     ├─→ 4. プレースホルダー置換
     │       {text} → input_data.text
     │
     ├─→ 5. AI API呼び出し
     │       OpenAI / Gemini
     │
     ├─→ 6. executions テーブル: ログ保存
     │       - input_data
     │       - output_data
     │       - tokens_used
     │       - execution_time
     │
     └─→ 7. レスポンス返却
         { output: "...", model_used: "gpt-4", ... }
```

### 2. プロンプト割り当てフロー

```
[管理者]
     │
     │ 「user1 に 文章要約プロンプト を割り当て」
     ↓
[サーバー]
     │
     ├─→ 1. accounts テーブル: user1 の存在確認
     │
     ├─→ 2. prompts テーブル: プロンプトの存在確認
     │
     ├─→ 3. account_prompts テーブル: 紐付け作成
     │       INSERT INTO account_prompts
     │       (account_id, prompt_id)
     │       VALUES (2, 1)
     │
     └─→ 4. 完了
         → user1 が文章要約プロンプトを使用可能に
```

---

## インデックス戦略

### 主要なインデックス

#### accounts テーブル
```sql
-- ログイン時の検索
INDEX idx_username (username)

-- メール検索
INDEX idx_email (email)

-- アカウント種別でのフィルタリング
INDEX idx_account_type (account_type)

-- 有効アカウントのみ取得
INDEX idx_is_active (is_active)
```

#### prompts テーブル
```sql
-- プロンプト名検索
INDEX idx_name (name)

-- モデル種別でのフィルタリング
INDEX idx_model_type (model_type)

-- 有効プロンプトのみ取得
INDEX idx_is_active (is_active)

-- 作成者で検索
INDEX idx_created_by (created_by)
```

#### executions テーブル
```sql
-- アカウントの実行履歴
INDEX idx_account_id (account_id)

-- プロンプトの使用履歴
INDEX idx_prompt_id (prompt_id)

-- ステータスでのフィルタリング
INDEX idx_status (status)

-- 日時範囲での検索
INDEX idx_executed_at (executed_at)

-- アカウント＋日時（最も使用される組み合わせ）
INDEX idx_account_executed (account_id, executed_at)
```

---

## パフォーマンス考慮事項

### 1. 大量データ対策

#### executions テーブルのパーティショニング
```sql
-- 月ごとにパーティション分割（将来的に実装）
ALTER TABLE executions
PARTITION BY RANGE (YEAR(executed_at) * 100 + MONTH(executed_at)) (
    PARTITION p202310 VALUES LESS THAN (202311),
    PARTITION p202311 VALUES LESS THAN (202312),
    PARTITION p202312 VALUES LESS THAN (202401),
    ...
);
```

#### 古いログのアーカイブ
```sql
-- 3ヶ月以上前のログを別テーブルに移動
INSERT INTO executions_archive 
SELECT * FROM executions 
WHERE executed_at < DATE_SUB(NOW(), INTERVAL 3 MONTH);

DELETE FROM executions 
WHERE executed_at < DATE_SUB(NOW(), INTERVAL 3 MONTH);
```

### 2. クエリ最適化

#### 頻繁に使用されるクエリ

**ユーザーのプロンプト一覧（最適化済み）**:
```sql
SELECT p.id, p.name, p.description, p.model_type
FROM prompts p
INNER JOIN account_prompts ap ON p.id = ap.prompt_id
WHERE ap.account_id = ? 
  AND p.is_active = TRUE
ORDER BY p.name;

-- インデックス使用:
-- - account_prompts: idx_account_id
-- - prompts: PRIMARY KEY, idx_is_active
```

**実行履歴の取得（ページネーション）**:
```sql
SELECT * FROM executions
WHERE account_id = ?
ORDER BY executed_at DESC
LIMIT 50 OFFSET 0;

-- インデックス使用:
-- - executions: idx_account_executed (account_id, executed_at)
```

---

## セキュリティ考慮事項

### 1. 機密データの保護

| テーブル | カラム | 保護方法 |
|---------|--------|---------|
| accounts | hashed_password | bcrypt ハッシュ化 |
| prompts | encrypted_content | Fernet 暗号化 |
| api_configs | openai_api_key | 平文（環境変数推奨） |
| api_configs | gemini_api_key | 平文（環境変数推奨） |

### 2. アクセス制御

```sql
-- データベースユーザーの権限設定例
CREATE USER 'prompt_app'@'localhost' IDENTIFIED BY 'secure_password';

GRANT SELECT, INSERT, UPDATE ON prompt_provision_db.accounts TO 'prompt_app'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON prompt_provision_db.prompts TO 'prompt_app'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON prompt_provision_db.account_prompts TO 'prompt_app'@'localhost';
GRANT SELECT, INSERT ON prompt_provision_db.executions TO 'prompt_app'@'localhost';
GRANT SELECT, INSERT, UPDATE ON prompt_provision_db.api_configs TO 'prompt_app'@'localhost';

-- 管理者以外は DELETE できない
REVOKE DELETE ON prompt_provision_db.executions FROM 'prompt_app'@'localhost';
```

### 3. データ整合性

```sql
-- 外部キー制約による整合性保証
FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
FOREIGN KEY (prompt_id) REFERENCES prompts(id) ON DELETE SET NULL

-- UNIQUE制約による重複防止
UNIQUE KEY uk_account_prompt (account_id, prompt_id)
```

---

## バックアップ戦略

### 1. 完全バックアップ
```bash
# 毎日深夜に実行
mysqldump -u root -p prompt_provision_db > /backup/db_$(date +%Y%m%d).sql
```

### 2. 差分バックアップ
```bash
# バイナリログを使用
mysqlbinlog --start-datetime="2025-10-23 00:00:00" \
            --stop-datetime="2025-10-23 23:59:59" \
            /var/log/mysql/mysql-bin.000001 > /backup/binlog_20251023.sql
```

### 3. 重要データの優先順位
1. **最優先**: `prompts.encrypted_content` （復元不可能）
2. **高**: `accounts` （ユーザー情報）
3. **中**: `account_prompts` （割り当て情報）
4. **低**: `executions` （ログ、再生成可能）

---

## マイグレーション履歴

### バージョン 1.0.0 (初期)
```sql
-- 初期テーブル作成
CREATE TABLE accounts (...);
CREATE TABLE prompts (...);
CREATE TABLE account_prompts (...);
CREATE TABLE executions (...);
CREATE TABLE api_configs (...);
```

### バージョン 1.1.0 (予定)
```sql
-- プロンプトのカテゴリ機能追加
ALTER TABLE prompts ADD COLUMN category VARCHAR(100);
CREATE INDEX idx_category ON prompts(category);

-- お気に入り機能追加
CREATE TABLE favorites (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,
    prompt_id INT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
    FOREIGN KEY (prompt_id) REFERENCES prompts(id) ON DELETE CASCADE,
    UNIQUE KEY uk_account_prompt (account_id, prompt_id)
);
```

---

## まとめ

このデータベース設計は：
✅ セキュアなプロンプト保存（暗号化）
✅ 柔軟な権限管理（多対多関係）
✅ 詳細な実行ログ記録
✅ スケーラブルな構造
✅ パフォーマンス最適化

を実現しています。

