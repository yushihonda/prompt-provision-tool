# 📝 Prompt Provision Tool - クイックリファレンス

## 🚀 1分でわかるシステム概要

### 目的
**プロンプトを外部に漏らさず、AI実行機能のみを提供**

### 特徴
✅ プロンプト暗号化保存  
✅ OpenAI / Gemini 対応  
✅ 権限管理（管理者/ユーザー）  
✅ 実行ログ完全記録  

---

## 👥 アカウント種別

| 種別 | 権限 | できること |
|------|------|-----------|
| **PARENT（管理者）** | 全権限 | プロンプト作成、アカウント管理、割り当て |
| **CHILD（ユーザー）** | 実行のみ | 割り当てられたプロンプトの実行 |

---

## 🔑 ログイン情報

### 管理者
- **URL**: `http://your-domain/static/admin/login.html`
- **初期アカウント**: データベースで作成

### ユーザー
- **URL**: `http://your-domain/static/user/login.html`
- **アカウント**: 管理者が作成

---

## 📊 データベーステーブル（5つ）

| テーブル | 説明 | 重要度 |
|---------|------|--------|
| **accounts** | アカウント情報 | ⭐⭐⭐ |
| **prompts** | プロンプト（暗号化） | ⭐⭐⭐ |
| **account_prompts** | 割り当て管理 | ⭐⭐ |
| **executions** | 実行ログ | ⭐⭐ |
| **api_configs** | API設定 | ⭐ |

---

## 🔐 セキュリティ

| 項目 | 方式 |
|------|------|
| パスワード | bcrypt ハッシュ化 |
| プロンプト | Fernet 暗号化 |
| 認証 | JWT（7日間有効） |
| 通信 | HTTPS/Bearer Token |

---

## 🎯 主要API

### 認証
```
POST /api/auth/login
```

### 管理者
```
GET    /api/admin/dashboard       # 統計
GET    /api/admin/accounts        # アカウント一覧
POST   /api/admin/accounts        # 作成
GET    /api/admin/prompts         # プロンプト一覧
POST   /api/admin/prompts         # 作成
POST   /api/admin/account-prompts/assign  # 割り当て
```

### ユーザー
```
GET    /api/user/prompts          # 自分のプロンプト一覧
GET    /api/user/prompts/:id      # 詳細
GET    /api/user/executions       # 実行履歴
```

### 実行
```
POST   /api/execute               # プロンプト実行
```

---

## 📝 プロンプトテンプレート書式

### プレースホルダー
```
{variable_name}
```

### 例
```
以下の文章を要約してください。

{text}
```

### Input Schema
```json
{
  "type": "object",
  "properties": {
    "text": {
      "type": "string",
      "title": "要約する文章",
      "description": "入力してください"
    }
  },
  "required": ["text"]
}
```

---

## 🤖 対応AIモデル

### OpenAI
- `gpt-4`
- `gpt-4-turbo-preview`
- `gpt-5-pro`（将来）

### Google
- `gemini-pro`
- `gemini-2.5-pro`
- `gemini-2.5-pro-deep-think`

---

## 📂 ファイル構造

```
prompt-provision-tool/
├── backend/
│   ├── app/
│   │   ├── api/          # エンドポイント
│   │   ├── models.py     # DB モデル
│   │   ├── schemas.py    # Pydantic
│   │   ├── encryption.py # 暗号化
│   │   └── services/     # AI API
│   └── requirements.txt
├── frontend/
│   ├── admin/           # 管理者画面
│   └── user/            # ユーザー画面
└── docs/                # ドキュメント
```

---

## ⚙️ 環境変数（.env）

```bash
# データベース
DB_HOST=localhost
DB_PORT=3306
DB_USER=prompt_user
DB_PASSWORD=prompt_password
DB_NAME=prompt_provision_db

# セキュリティ
SECRET_KEY=your-secret-key-here
ENCRYPTION_KEY=your-encryption-key-here

# AI API
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=your-gemini-key

# アプリ設定
APP_HOST=127.0.0.1
APP_PORT=8000
CORS_ORIGINS=http://localhost,http://160.251.172.234
```

---

## 🔧 よく使うコマンド

### 起動（開発）
```bash
cd backend
source venv/bin/activate
uvicorn app.main:app --reload
```

### 起動（本番）
```bash
sudo systemctl start prompt-tool.service
sudo systemctl status prompt-tool.service
```

### ログ確認
```bash
sudo journalctl -u prompt-tool.service -f
```

### データベース接続
```bash
mysql -u prompt_user -p prompt_provision_db
```

---

## 🐛 トラブルシューティング

### ログインできない
```bash
# DBを確認
mysql> SELECT username, is_active FROM accounts;

# パスワードをリセット
mysql> UPDATE accounts 
       SET hashed_password = '$2b$12$...' 
       WHERE username = 'admin';
```

### プロンプトが表示されない
```sql
-- 割り当てを確認
SELECT a.username, p.name 
FROM account_prompts ap
JOIN accounts a ON ap.account_id = a.id
JOIN prompts p ON ap.prompt_id = p.id
WHERE a.username = 'user1';

-- 割り当てを追加
INSERT INTO account_prompts (account_id, prompt_id)
VALUES (2, 1);
```

### サーバーが起動しない
```bash
# エラーログ確認
sudo journalctl -u prompt-tool.service -n 50 --no-pager

# 設定ファイル確認
cat /opt/prompt-provision-tool/backend/.env

# ポート確認
sudo netstat -tlnp | grep 8000
```

---

## 📊 統計クエリ

### 今日の実行回数
```sql
SELECT COUNT(*) FROM executions 
WHERE DATE(executed_at) = CURDATE();
```

### アカウントごとの実行回数
```sql
SELECT a.username, COUNT(e.id) as count
FROM accounts a
LEFT JOIN executions e ON a.id = e.account_id
GROUP BY a.id, a.username;
```

### プロンプトごとの平均実行時間
```sql
SELECT p.name, AVG(e.execution_time) as avg_ms
FROM prompts p
JOIN executions e ON p.id = e.prompt_id
WHERE e.status = 'success'
GROUP BY p.id, p.name;
```

### 今月のトークン使用量
```sql
SELECT SUM(tokens_used) as total_tokens
FROM executions
WHERE YEAR(executed_at) = YEAR(CURDATE())
  AND MONTH(executed_at) = MONTH(CURDATE());
```

---

## 🔗 関連ドキュメント

| ドキュメント | 用途 |
|-------------|------|
| [README.md](README.md) | プロジェクト概要 |
| [SYSTEM_SPECIFICATION.md](SYSTEM_SPECIFICATION.md) | システム仕様書 |
| [USER_GUIDE.md](USER_GUIDE.md) | ユーザーガイド |
| [DATABASE_DESIGN.md](DATABASE_DESIGN.md) | DB設計詳細 |
| [SETUP_GUIDE.md](SETUP_GUIDE.md) | 環境構築 |
| [deployment/README.md](deployment/README.md) | デプロイ |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | トラブル対処 |

---

## 📞 サポート連絡先

### システム管理者
- エラーで動かない
- パフォーマンス問題
- セキュリティ懸念

### 管理者ユーザー
- プロンプト作成支援
- アカウント管理
- 権限設定

---

## 🎓 学習リソース

### 初心者
1. README.md（5分）
2. USER_GUIDE.md クイックスタート（10分）

### 開発者
1. SYSTEM_SPECIFICATION.md（60分）
2. DATABASE_DESIGN.md（30分）
3. ソースコード閲覧

### 管理者
1. USER_GUIDE.md 管理者向け（15分）
2. SYSTEM_SPECIFICATION.md 機能仕様（30分）

---

## ⚡ クイックアクション

### 新しいユーザーを追加
```sql
-- 1. アカウント作成
INSERT INTO accounts (username, email, hashed_password, account_type)
VALUES ('newuser', 'new@example.com', '$2b$12$...', 'CHILD');

-- 2. プロンプトを割り当て
INSERT INTO account_prompts (account_id, prompt_id)
SELECT id, 1 FROM accounts WHERE username = 'newuser';
```

### プロンプトを無効化
```sql
UPDATE prompts SET is_active = FALSE WHERE id = 1;
```

### 実行ログを削除（古いデータ）
```sql
DELETE FROM executions 
WHERE executed_at < DATE_SUB(NOW(), INTERVAL 3 MONTH);
```

---

## 🎯 ベストプラクティス

### プロンプト作成
✅ 明確な指示を書く  
✅ 出力フォーマットを指定  
✅ 役割を明示（「あなたは〜です」）  
✅ プレースホルダーは `{variable_name}`  

### セキュリティ
✅ プロンプトは必ず暗号化  
✅ APIキーは環境変数で管理  
✅ パスワードは複雑に  
✅ 定期的にログを確認  

### パフォーマンス
✅ 古いログは定期削除  
✅ インデックスを活用  
✅ 必要最小限のデータ取得  
✅ ページネーション実装  

---

## 📌 重要な注意事項

⚠️ **プロンプトの内容は暗号化**されています  
⚠️ **ユーザーにはプロンプトの中身は見えません**  
⚠️ **実行ログはすべて記録**されます  
⚠️ **APIキーは環境変数**で管理してください  
⚠️ **本番環境ではHTTPS**を使用してください  

---

## ✅ チェックリスト

### 初回セットアップ
- [ ] データベース作成
- [ ] `.env` ファイル設定
- [ ] APIキー設定
- [ ] 管理者アカウント作成
- [ ] プロンプト作成
- [ ] ユーザー作成
- [ ] プロンプト割り当て
- [ ] 動作確認

### 本番デプロイ
- [ ] サーバー構築
- [ ] MySQL設定
- [ ] Nginx設定
- [ ] SSL証明書設定
- [ ] systemdサービス設定
- [ ] ログローテーション設定
- [ ] バックアップ設定
- [ ] 監視設定

---

## 🎉 まとめ

このクイックリファレンスで：
✅ システム全体を把握
✅ よく使う操作を確認
✅ トラブル時の対処法を参照
✅ ベストプラクティスを実践

**詳細は各ドキュメントを参照してください！**

