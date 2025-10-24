# トラブルシューティングガイド

このドキュメントでは、Prompt Provision Toolで発生する可能性のある一般的な問題とその解決方法について説明します。

## 🚨 500 Internal Server Error（ログイン時）

### 症状
- ログイン画面で認証情報を入力すると500エラーが発生
- ブラウザのコンソールに以下のようなエラーが表示される：
  ```
  Failed to load resource: the server responded with a status of 500 (Internal Server Error)
  Login error: SyntaxError: Unexpected token 'I', "Internal S"... is not valid JSON
  ```

### 原因と解決方法

#### 1. データベース接続エラー

**確認方法：**
```bash
cd backend
python diagnose.py
```

**解決方法：**
- MySQLサーバーが起動していることを確認
  ```bash
  # macOS/Linux
  sudo systemctl status mysql
  # または
  sudo service mysql status
  ```
- `.env`ファイルのデータベース接続情報を確認
  ```env
  DB_HOST=localhost
  DB_PORT=3306
  DB_USER=your_username
  DB_PASSWORD=your_password
  DB_NAME=prompt_tool
  ```

#### 2. 環境変数が未設定

**確認方法：**
```bash
cd backend
ls -la .env
```

**解決方法：**
`.env`ファイルが存在しない場合は作成してください：
```env
# Database
DB_HOST=localhost
DB_PORT=3306
DB_USER=your_db_user
DB_PASSWORD=your_db_password
DB_NAME=prompt_tool

# Security
SECRET_KEY=your-secret-key-here-min-32-characters
ENCRYPTION_KEY=your-encryption-key-here-32-bytes-base64

# AI API Keys
OPENAI_API_KEY=your-openai-api-key
GEMINI_API_KEY=your-gemini-api-key

# Application
APP_HOST=0.0.0.0
APP_PORT=8000
CORS_ORIGINS=http://localhost:8000,http://160.251.172.234

# Environment
ENVIRONMENT=production
```

**SECRET_KEYの生成方法：**
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

**ENCRYPTION_KEYの生成方法：**
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

#### 3. データベースが初期化されていない

**確認方法：**
```bash
cd backend
python diagnose.py
```

**解決方法：**
マイグレーションを実行してテーブルを作成：
```bash
cd backend
alembic upgrade head
```

#### 4. アカウントが存在しない

**確認方法：**
```bash
cd backend
python diagnose.py
```

**解決方法：**
管理者アカウントを作成：
```bash
cd backend
python -m app.init_admin
```

対話形式で管理者のユーザー名とパスワードを入力してください。

#### 5. Pythonパッケージが不足

**確認方法：**
```bash
cd backend
pip list
```

**解決方法：**
必要なパッケージをインストール：
```bash
cd backend
pip install -r requirements.txt
```

## ⚠️ Unchecked runtime.lastError

### 症状
```
Unchecked runtime.lastError: The message port closed before a response was received.
```

### 原因
これはブラウザ拡張機能（Chrome拡張など）によって引き起こされる警告です。

### 解決方法
このエラーはアプリケーションの動作には影響しないため、**無視しても問題ありません**。

気になる場合は：
1. ブラウザの拡張機能を無効化
2. シークレットモード/プライベートブラウジングで試す
3. 別のブラウザで試す

## 🔒 CORS エラー

### 症状
```
Access to fetch at 'http://...' from origin 'http://...' has been blocked by CORS policy
```

### 解決方法
`.env`ファイルの`CORS_ORIGINS`を確認：
```env
CORS_ORIGINS=http://localhost:8000,http://160.251.172.234
```

アクセス元のURLをカンマ区切りで追加してください。

## 📊 サーバーログの確認

サーバーを起動している端末でログを確認してください：
```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level debug
```

`--log-level debug`オプションで詳細なログが表示されます。

## 🔍 診断ツールの使用

問題を素早く特定するために診断スクリプトを実行：
```bash
cd backend
python diagnose.py
```

このスクリプトは以下をチェックします：
- ✅ 環境変数ファイルの存在
- ✅ 設定の読み込み
- ✅ データベース接続
- ✅ テーブルの存在
- ✅ アカウントの存在

## 🆘 それでも解決しない場合

1. **サーバーログを確認**：エラーの詳細が記録されています
2. **診断スクリプトを実行**：`python backend/diagnose.py`
3. **データベースの状態を確認**：
   ```bash
   mysql -u your_user -p
   USE prompt_tool;
   SHOW TABLES;
   SELECT * FROM accounts;
   ```
4. **サーバーを再起動**：
   ```bash
   # サーバーを停止（Ctrl+C）
   cd backend
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

## 📝 ログファイル

システムログの場所（本番環境）：
- アプリケーションログ：`journalctl -u prompt-tool.service`
- Nginxアクセスログ：`/var/log/nginx/access.log`
- Nginxエラーログ：`/var/log/nginx/error.log`

## 🔧 よくある設定ミス

### 1. SECRET_KEYが短すぎる
SECRET_KEYは最低32文字必要です。

### 2. ENCRYPTION_KEYの形式が間違っている
ENCRYPTION_KEYはFernet形式のBase64エンコードされた32バイトの鍵である必要があります。

### 3. データベース名が間違っている
データベースを作成し忘れていることがあります：
```sql
CREATE DATABASE prompt_tool CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### 4. ポートが使用中
8000番ポートが既に使用されている場合：
```bash
# 使用中のポートを確認
lsof -i :8000
# プロセスを停止
kill -9 <PID>
```

## 📞 サポート

問題が解決しない場合は、以下の情報を含めてお問い合わせください：
- エラーメッセージの全文
- `diagnose.py`の実行結果
- サーバーログの関連部分
- 使用している環境（OS、Python バージョン、MySQL バージョン）

