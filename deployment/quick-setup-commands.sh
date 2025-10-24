#!/bin/bash

# クイックセットアップコマンド集
# サーバーIP: 160.251.172.234

echo "=========================================="
echo "プロンプト提供ツール - クイックセットアップ"
echo "=========================================="
echo ""

# 色の定義
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}[1/8] システムパッケージの更新${NC}"
apt update && apt upgrade -y

echo -e "${GREEN}[2/8] 必要なパッケージのインストール${NC}"
apt install -y python3.11 python3.11-venv python3-pip nginx mysql-server git ufw

echo -e "${GREEN}[3/8] ファイアウォールの設定${NC}"
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo -e "${GREEN}[4/8] MySQLデータベースの作成${NC}"
echo -e "${YELLOW}MySQLのrootパスワードを入力してください：${NC}"
read -s MYSQL_ROOT_PASSWORD

mysql -u root -p"$MYSQL_ROOT_PASSWORD" <<EOF
CREATE DATABASE IF NOT EXISTS prompt_provision_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'prompt_tool_user'@'localhost' IDENTIFIED BY 'PromptTool2024!';
GRANT ALL PRIVILEGES ON prompt_provision_db.* TO 'prompt_tool_user'@'localhost';
FLUSH PRIVILEGES;
EOF

echo -e "${GREEN}[5/8] Python仮想環境のセットアップ${NC}"
cd /opt/prompt-provision-tool
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r backend/requirements.txt

echo -e "${GREEN}[6/8] 環境変数の設定${NC}"
if [ ! -f backend/.env ]; then
    cp .env.example backend/.env
    
    # キーの生成
    SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    ENCRYPTION_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32)[:32])")
    
    # .envファイルに追記
    echo "" >> backend/.env
    echo "# Generated Keys" >> backend/.env
    echo "SECRET_KEY=$SECRET_KEY" >> backend/.env
    echo "ENCRYPTION_KEY=$ENCRYPTION_KEY" >> backend/.env
    echo "DB_PASSWORD=PromptTool2024!" >> backend/.env
    
    echo ""
    echo -e "${YELLOW}重要: 以下のAPIキーを backend/.env に追加してください：${NC}"
    echo "OPENAI_API_KEY=your-key-here"
    echo "GEMINI_API_KEY=your-key-here"
    echo ""
fi

echo -e "${GREEN}[7/8] Nginx設定${NC}"
cp deployment/nginx-ip-only.conf /etc/nginx/sites-available/prompt-tool
ln -sf /etc/nginx/sites-available/prompt-tool /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t

echo -e "${GREEN}[8/8] ログディレクトリの作成${NC}"
mkdir -p /var/log/prompt-tool
chown www-data:www-data /var/log/prompt-tool

echo -e "${GREEN}[完了] データベースマイグレーション${NC}"
cd /opt/prompt-provision-tool/backend
source ../venv/bin/activate
alembic upgrade head

echo -e "${GREEN}[完了] systemdサービスの設定${NC}"
cp deployment/prompt-tool.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable prompt-tool
systemctl start prompt-tool

echo -e "${GREEN}[完了] Nginxの起動${NC}"
systemctl restart nginx

echo ""
echo "=========================================="
echo "セットアップ完了！"
echo "=========================================="
echo ""
echo "次のステップ:"
echo "1. APIキーを設定: nano /opt/prompt-provision-tool/backend/.env"
echo "2. 管理者アカウント作成:"
echo "   cd /opt/prompt-provision-tool/backend"
echo "   source ../venv/bin/activate"
echo "   python -m app.init_admin"
echo "3. サービス再起動: systemctl restart prompt-tool"
echo ""
echo "アクセスURL: http://160.251.172.234/"
echo ""


