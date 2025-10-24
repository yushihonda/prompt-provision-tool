# クイックスタートガイド

このガイドでは、プロンプト提供ツールを最速で起動する方法を説明します。

## 🚀 5分で起動（ローカル開発環境）

### 前提条件

- Python 3.11+
- MySQL 8.0+ (または Docker)

### 手順

```bash
# 1. MySQL起動（Dockerの場合）
docker run --name mysql-prompt-tool -e MYSQL_ROOT_PASSWORD=root -e MYSQL_DATABASE=prompt_provision_db -p 3306:3306 -d mysql:8.0

# 2. リポジトリのクローンと移動
cd prompt-provision-tool

# 3. 仮想環境の作成とアクティベート
python3.11 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 4. 依存パッケージのインストール
cd backend
pip install -r requirements.txt

# 5. 環境変数の設定
cp ../backend/.env.example .env
# .envファイルを編集してAPIキーを設定

# 6. キーの生成と設定
python -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32))" >> .env
python -c "import secrets; print('ENCRYPTION_KEY=' + secrets.token_urlsafe(32)[:32])" >> .env

# 7. データベースの初期化
# MySQLにログインしてデータベースとユーザーを作成
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS prompt_provision_db CHARACTER SET utf8mb4;"
mysql -u root -p -e "CREATE USER IF NOT EXISTS 'prompt_tool_user'@'localhost' IDENTIFIED BY 'password123';"
mysql -u root -p -e "GRANT ALL ON prompt_provision_db.* TO 'prompt_tool_user'@'localhost';"

# 8. マイグレーション実行
alembic upgrade head

# 9. 管理者アカウント作成
python -m app.init_admin
# デフォルト: username=admin, password=admin123

# 10. アプリケーション起動
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### アクセス

- **管理者ログイン**: http://localhost:8000/static/admin/login.html
- **ユーザーログイン**: http://localhost:8000/static/user/login.html
- **API ドキュメント**: http://localhost:8000/docs

---

## 📝 最初にやること

### 1. 管理者でログイン

デフォルト認証情報:
- ユーザー名: `admin`
- パスワード: `admin123`

### 2. プロンプトを作成

管理画面 > プロンプト管理 > 新しいプロンプトを作成

**簡単な例**:
- **名前**: テスト要約
- **説明**: テキストを要約します
- **モデル**: GPT-4 Turbo
- **プロンプト内容**:
  ```
  以下のテキストを3行で要約してください:
  
  {{text}}
  ```
- **入力スキーマ** (オプション):
  ```json
  {
    "text": {
      "type": "textarea",
      "label": "要約したいテキスト",
      "required": true
    }
  }
  ```

### 3. ユーザーアカウントを作成

管理画面 > アカウント管理 > 新しいアカウントを作成

- ユーザー名: `testuser`
- メール: `test@example.com`
- パスワード: `test123`
- アカウントタイプ: 子アカウント

### 4. プロンプトを割り当て

アカウント一覧 > プロンプト割り当て > 作成したプロンプトを選択

### 5. ユーザーとしてテスト

1. ログアウト
2. ユーザーログイン (testuser / test123)
3. プロンプト一覧から実行
4. テキストを入力して実行ボタンをクリック

---

## 🔧 よくある問題と解決方法

### データベース接続エラー

`.env`ファイルのDB設定を確認:
```env
DB_HOST=localhost
DB_PORT=3306
DB_USER=prompt_tool_user
DB_PASSWORD=password123
DB_NAME=prompt_provision_db
```

### OpenAI APIエラー

`.env`ファイルにAPIキーを設定:
```env
OPENAI_API_KEY=sk-your-actual-api-key
```

### ポート8000が使用中

別のポートで起動:
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

### マイグレーションエラー

テーブルを削除してやり直し:
```bash
mysql -u root -p -e "DROP DATABASE prompt_provision_db; CREATE DATABASE prompt_provision_db CHARACTER SET utf8mb4;"
alembic upgrade head
```

---

## 📚 次のステップ

- [SETUP_GUIDE.md](SETUP_GUIDE.md) - 詳細なセットアップ手順
- [FEATURES.md](FEATURES.md) - 全機能の説明
- [deployment/README.md](deployment/README.md) - 本番環境へのデプロイ

---

## 💡 ヒント

### API キーの取得

- **OpenAI**: https://platform.openai.com/api-keys
- **Google Gemini**: https://ai.google.dev/

### 開発のヒント

- `--reload` オプションでホットリロード有効
- Swagger UI (`/docs`) でAPIをテスト
- ログは標準出力に表示される

### セキュリティ

⚠️ **本番環境では必ず以下を実施**:
1. デフォルトパスワードの変更
2. 強固な `SECRET_KEY` と `ENCRYPTION_KEY` の生成
3. HTTPSの有効化
4. ファイアウォールの設定

---

**楽しいプロンプトエンジニアリングを！** 🎉

