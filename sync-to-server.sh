#!/bin/bash

# サーバーへファイルを同期するスクリプト

echo "=========================================="
echo "サーバーへファイル同期"
echo "=========================================="
echo ""

# 設定
REMOTE_HOST="conoha"
REMOTE_PATH="/opt/prompt-provision-tool"

# 除外するファイル・ディレクトリ
EXCLUDE_OPTS="--exclude='.git' --exclude='venv' --exclude='__pycache__' --exclude='*.pyc' --exclude='.env' --exclude='.DS_Store' --exclude='*.log'"

# 同期オプション
read -p "どの部分を同期しますか？ [1: 全体, 2: backend, 3: frontend, 4: deployment]: " choice

case $choice in
  1)
    echo "📦 全体を同期します..."
    rsync -av $EXCLUDE_OPTS --delete-after . ${REMOTE_HOST}:${REMOTE_PATH}/
    ;;
  2)
    echo "🐍 backendを同期します..."
    rsync -av $EXCLUDE_OPTS --delete-after backend/ ${REMOTE_HOST}:${REMOTE_PATH}/backend/
    ;;
  3)
    echo "🎨 frontendを同期します..."
    rsync -av $EXCLUDE_OPTS --delete-after frontend/ ${REMOTE_HOST}:${REMOTE_PATH}/frontend/
    ;;
  4)
    echo "⚙️  deploymentを同期します..."
    rsync -av $EXCLUDE_OPTS --delete-after deployment/ ${REMOTE_HOST}:${REMOTE_PATH}/deployment/
    ;;
  *)
    echo "❌ 無効な選択です"
    exit 1
    ;;
esac

echo ""
echo "✅ 同期が完了しました"
echo ""

# サービス再起動の確認
read -p "サーバーのサービスを再起動しますか？ [y/N]: " restart

if [[ $restart == "y" || $restart == "Y" ]]; then
    echo "🔄 サービスを再起動中..."
    ssh ${REMOTE_HOST} "sudo systemctl restart prompt-tool"
    sleep 2
    ssh ${REMOTE_HOST} "sudo systemctl status prompt-tool --no-pager | head -20"
    echo ""
    echo "✅ サービスが再起動しました"
fi

echo ""
echo "=========================================="
echo "完了！"
echo "=========================================="


