#!/bin/bash

# ConoHa VPS セットアップスクリプト
# Ubuntu 22.04/24.04 LTS 対応

set -e

echo "=========================================="
echo "Prompt Provision Tool セットアップ"
echo "=========================================="

# 変数設定
APP_DIR="/opt/prompt-provision-tool"
VENV_DIR="$APP_DIR/venv"
DB_NAME="prompt_provision_db"
DB_USER="prompt_tool_user"
DB_PASSWORD="YOUR_DB_PASSWORD_HERE"  # 実際のパスワードに変更してください

# システムの更新
echo "システムパッケージを更新中..."
sudo apt update
sudo apt upgrade -y

# 必要なパッケージのインストール
echo "必要なパッケージをインストール中..."
sudo apt install -y \
    python3 \
    python3-venv \
    python3-pip \
    nginx \
    mysql-server \
    redis-server \
    certbot \
    python3-certbot-nginx \
    git \
    ufw

# ファイアウォール設定
echo "ファイアウォールを設定中..."
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable

# Redisの設定
echo "Redisを設定中..."
sudo systemctl enable redis-server
sudo systemctl start redis-server

# MySQLのセキュア設定とデータベース作成
echo "MySQLデータベースを設定中..."
sudo mysql -e "CREATE DATABASE IF NOT EXISTS $DB_NAME CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
sudo mysql -e "CREATE USER IF NOT EXISTS '$DB_USER'@'localhost' IDENTIFIED BY '$DB_PASSWORD';"
sudo mysql -e "GRANT ALL PRIVILEGES ON $DB_NAME.* TO '$DB_USER'@'localhost';"
sudo mysql -e "FLUSH PRIVILEGES;"

# アプリケーションディレクトリの作成
echo "アプリケーションディレクトリを作成中..."
sudo mkdir -p $APP_DIR
sudo chown -R $USER:$USER $APP_DIR

# リポジトリのクローン（または手動でファイルをコピー）
# git clone <your-repo-url> $APP_DIR

# Python仮想環境の作成
echo "Python仮想環境を作成中..."
python3 -m venv $VENV_DIR
source $VENV_DIR/bin/activate

# Pythonパッケージのインストール
echo "Pythonパッケージをインストール中..."
pip install --upgrade pip
pip install -r $APP_DIR/backend/requirements.txt

# 環境変数ファイルの作成
echo "環境変数ファイルを作成中..."
if [ ! -f "$APP_DIR/backend/.env" ]; then
    if [ -f "$APP_DIR/backend/.env.example" ]; then
        cp $APP_DIR/backend/.env.example $APP_DIR/backend/.env
    else
        # .env.exampleが存在しない場合は空の.envファイルを作成
        touch $APP_DIR/backend/.env
    fi
    echo "⚠️  $APP_DIR/backend/.env を編集して、適切な値を設定してください"
    echo "    README.mdの「環境変数（.env）」セクションを参照してください"
fi

# 暗号化キーの生成
echo "暗号化キーを生成中..."
ENCRYPTION_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32)[:32])")
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")

echo "生成されたキー（.envファイルに設定してください）:"
echo "SECRET_KEY=$SECRET_KEY"
echo "ENCRYPTION_KEY=$ENCRYPTION_KEY"

# データベースマイグレーション
echo "データベースマイグレーションを実行中..."
cd $APP_DIR/backend
alembic upgrade head

# 初期管理者アカウントの作成
echo "初期管理者アカウントを作成..."
python -m app.init_admin

# ログディレクトリの作成
echo "ログディレクトリを作成中..."
sudo mkdir -p /var/log/prompt-tool
sudo chown www-data:www-data /var/log/prompt-tool

# systemdサービスの設定
echo "systemdサービスを設定中..."
sudo cp $APP_DIR/deployment/prompt-tool.service /etc/systemd/system/
sudo cp $APP_DIR/deployment/prompt-tool-celery.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable prompt-tool
sudo systemctl enable prompt-tool-celery
sudo systemctl start prompt-tool
sudo systemctl start prompt-tool-celery

# Nginx設定
echo "Nginxを設定中..."
sudo cp $APP_DIR/deployment/nginx.conf /etc/nginx/sites-available/prompt-tool
sudo ln -sf /etc/nginx/sites-available/prompt-tool /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx

echo ""
echo "=========================================="
echo "セットアップ完了！"
echo "=========================================="
echo ""
echo "次のステップ:"
echo "1. $APP_DIR/backend/.env を編集して、データベース情報とAPIキーを設定"
echo "   - README.mdの「環境変数（.env）」セクションを参照"
echo "   - 生成されたSECRET_KEYとENCRYPTION_KEYを設定"
echo "2. deployment/nginx.conf のドメイン名を実際のドメインに変更"
echo "3. SSL証明書の取得:"
echo "   sudo certbot --nginx -d your-domain.com"
echo "4. サービスの再起動:"
echo "   sudo systemctl restart prompt-tool"
echo "   sudo systemctl restart prompt-tool-celery"
echo "   sudo systemctl restart nginx"
echo ""
echo "サービス状態の確認:"
echo "   sudo systemctl status prompt-tool"
echo "   sudo systemctl status prompt-tool-celery"
echo "   sudo systemctl status redis-server"
echo "   sudo systemctl status nginx"
echo ""
echo "ログの確認:"
echo "   sudo tail -f /var/log/prompt-tool/app.log"
echo "   sudo tail -f /var/log/prompt-tool/celery.log"
echo "   sudo tail -f /var/log/nginx/prompt-tool-error.log"
echo ""

