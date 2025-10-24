# サーバーセットアップ手順

サーバーIP: `160.251.172.234`

## ステップ1: サーバーへの接続確認

ローカルマシンから以下のコマンドで接続できることを確認：

```bash
ssh root@160.251.172.234
```

## ステップ2: ファイルのアップロード

**ローカルマシンで実行（プロジェクトルートから）：**

```bash
# プロジェクトディレクトリにいることを確認
cd /Users/hondayushi/workspaece/poifull/prompt-provision-tool

# サーバーにファイルをアップロード
scp -r . root@160.251.172.234:/opt/prompt-provision-tool/

# または、不要なファイルを除外してアップロード
rsync -av --exclude='.git' --exclude='venv' --exclude='__pycache__' --exclude='*.pyc' . root@160.251.172.234:/opt/prompt-provision-tool/
```

## ステップ3: サーバーでのセットアップ

**サーバーにSSHで接続：**

```bash
ssh root@160.251.172.234
```

**サーバー上で実行：**

```bash
cd /opt/prompt-provision-tool/deployment
chmod +x setup.sh
./setup.sh
```

セットアップスクリプトが以下を自動で行います：
- システムパッケージの更新
- Python 3.11、MySQL、Nginxのインストール
- ファイアウォールの設定
- データベースの作成
- Python環境のセットアップ

## ステップ4: 環境変数の設定

セットアップ完了後、生成されたキーをメモして、`.env`ファイルを編集：

```bash
nano /opt/prompt-provision-tool/backend/.env
```

以下の項目を設定：

```env
# Database
DB_HOST=localhost
DB_PORT=3306
DB_USER=prompt_tool_user
DB_PASSWORD=YOUR_DB_PASSWORD  # setup.shで設定したパスワード
DB_NAME=prompt_provision_db

# Security (setup.shで生成されたものを使用)
SECRET_KEY=<生成されたキー>
ENCRYPTION_KEY=<生成されたキー>
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# AI API Keys ← ここを必ず設定！
OPENAI_API_KEY=sk-your-openai-api-key-here
GEMINI_API_KEY=your-gemini-api-key-here

# Application
APP_HOST=0.0.0.0
APP_PORT=8000
CORS_ORIGINS=http://160.251.172.234

# Environment
ENVIRONMENT=production
```

## ステップ5: Nginx設定の調整

ドメイン名がない場合はIPアドレスで設定：

```bash
nano /etc/nginx/sites-available/prompt-tool
```

`server_name` を修正：

```nginx
server_name 160.251.172.234;
```

HTTPSの部分は一旦コメントアウト（ドメイン取得後に有効化）：

```nginx
# HTTPサーバーのみ有効化
server {
    listen 80;
    server_name 160.251.172.234;

    # 以下、location設定を追加...
}
```

## ステップ6: サービスの起動

```bash
# マイグレーション実行
cd /opt/prompt-provision-tool/backend
source ../venv/bin/activate
alembic upgrade head

# 管理者アカウント作成
python -m app.init_admin

# サービスの起動
sudo systemctl restart prompt-tool
sudo systemctl restart nginx

# 状態確認
sudo systemctl status prompt-tool
sudo systemctl status nginx
```

## ステップ7: 動作確認

ブラウザで以下にアクセス：

- **トップページ**: http://160.251.172.234/
- **管理者ログイン**: http://160.251.172.234/static/admin/login.html
- **ユーザーログイン**: http://160.251.172.234/static/user/login.html
- **APIドキュメント**: http://160.251.172.234/docs

## トラブルシューティング

### ログの確認

```bash
# アプリケーションログ
sudo tail -f /var/log/prompt-tool/app.log

# Nginxログ
sudo tail -f /var/log/nginx/prompt-tool-access.log
sudo tail -f /var/log/nginx/prompt-tool-error.log

# systemdログ
sudo journalctl -u prompt-tool -f
```

### サービスの再起動

```bash
sudo systemctl restart prompt-tool
sudo systemctl restart nginx
```

### ファイアウォールの確認

```bash
sudo ufw status
# 80番ポートが開いていることを確認
```

## 次のステップ（ドメイン取得後）

1. ドメインのDNS設定で `160.251.172.234` を指定
2. SSL証明書の取得：
   ```bash
   sudo certbot --nginx -d your-domain.com
   ```
3. HTTPSへのリダイレクト設定


