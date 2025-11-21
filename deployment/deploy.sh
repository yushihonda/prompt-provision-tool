#!/bin/bash

# ConoHa VPS デプロイスクリプト
# 本番環境への変更反映用

set -e

echo "=========================================="
echo "Prompt Provision Tool デプロイ"
echo "=========================================="

# 変数設定
APP_DIR="/opt/prompt-provision-tool"
VENV_DIR="$APP_DIR/venv"
BACKEND_DIR="$APP_DIR/backend"

# アプリケーションディレクトリに移動
cd $APP_DIR

# Gitから最新のコードを取得（Gitを使用している場合）
if [ -d "$APP_DIR/.git" ]; then
    echo "Gitから最新のコードを取得中..."
    git pull origin main || git pull origin master
else
    echo "⚠️  Gitリポジトリが見つかりません。手動でファイルを更新してください。"
fi

# 仮想環境をアクティベート
echo "仮想環境をアクティベート中..."
source $VENV_DIR/bin/activate

# Pythonパッケージの更新（必要に応じて）
echo "Pythonパッケージを確認中..."
cd $BACKEND_DIR
pip install --upgrade pip
pip install -r requirements.txt

# データベースマイグレーション
echo "データベースマイグレーションを実行中..."
alembic upgrade head

# アプリケーションの再起動
echo "アプリケーションを再起動中..."
sudo systemctl restart prompt-tool

# サービス状態の確認
echo "サービス状態を確認中..."
sleep 2
sudo systemctl status prompt-tool --no-pager -l

echo ""
echo "=========================================="
echo "デプロイ完了！"
echo "=========================================="
echo ""
echo "ログの確認:"
echo "  sudo tail -f /var/log/prompt-tool/app.log"
echo "  sudo tail -f /var/log/prompt-tool/error.log"
echo ""

