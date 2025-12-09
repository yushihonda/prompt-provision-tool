#!/bin/bash

# ConoHaサーバーへのデプロイスクリプト
# 使用方法: ./deploy-to-conoha.sh

set -e

echo "=========================================="
echo "ConoHaサーバーへのデプロイ"
echo "=========================================="
echo ""

# サーバー情報の取得（環境変数または対話入力）
if [ -z "$SERVER_IP" ]; then
    read -p "サーバーのIPアドレスまたはホスト名: " SERVER_IP
fi
if [ -z "$SSH_USER" ]; then
    read -p "SSHユーザー名: " SSH_USER
fi
if [ -z "$APP_DIR" ]; then
    read -p "アプリケーションディレクトリ [/opt/prompt-provision-tool]: " APP_DIR
    APP_DIR=${APP_DIR:-/opt/prompt-provision-tool}
fi

echo ""
echo "デプロイ先: $SSH_USER@$SERVER_IP:$APP_DIR"
read -p "続行しますか？ (y/n): " CONFIRM

if [ "$CONFIRM" != "y" ] && [ "$CONFIRM" != "Y" ]; then
    echo "デプロイをキャンセルしました。"
    exit 1
fi

# 現在のディレクトリを取得
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$SCRIPT_DIR/prompt-provision-tool"

if [ ! -d "$PROJECT_DIR" ]; then
    echo "エラー: $PROJECT_DIR が見つかりません。"
    exit 1
fi

echo ""
echo "ファイルをアップロード中..."
echo ""

# フロントエンドファイルをアップロード
echo "1. フロントエンドファイルをアップロード..."
scp "$PROJECT_DIR/frontend/user/js/user-common.js" "$SSH_USER@$SERVER_IP:$APP_DIR/prompt-provision-tool/frontend/user/js/"

if [ $? -eq 0 ]; then
    echo "✓ フロントエンドファイルのアップロード完了"
else
    echo "✗ フロントエンドファイルのアップロードに失敗しました"
    exit 1
fi

echo ""
echo "2. サーバー側でNginxをリロード..."
ssh "$SSH_USER@$SERVER_IP" "sudo systemctl reload nginx"

if [ $? -eq 0 ]; then
    echo "✓ Nginxのリロード完了"
else
    echo "⚠️  Nginxのリロードに失敗しました（手動で確認してください）"
fi

echo ""
echo "=========================================="
echo "デプロイ完了！"
echo "=========================================="
echo ""
echo "ブラウザで確認してください。"
echo "キャッシュをクリアする場合は、Ctrl+Shift+R (Windows/Linux) または Cmd+Shift+R (Mac) を押してください。"
echo ""

