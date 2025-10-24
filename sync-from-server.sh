#!/bin/bash

# サーバーからファイルをダウンロードする同期スクリプト

echo "=========================================="
echo "サーバーからファイル同期"
echo "=========================================="
echo ""

# 設定
REMOTE_HOST="conoha"
REMOTE_PATH="/opt/prompt-provision-tool"

# 除外するファイル・ディレクトリ
EXCLUDE_OPTS="--exclude='venv' --exclude='__pycache__' --exclude='*.pyc' --exclude='.DS_Store' --exclude='*.log'"

# 同期オプション
echo "どの部分を同期しますか？"
echo "1: .envファイルのみ（設定ファイル）"
echo "2: backend全体"
echo "3: frontend全体"
echo "4: 全体（注意：ローカルの変更が上書きされます）"
read -p "選択 [1-4]: " choice

case $choice in
  1)
    echo "🔑 .envファイルを取得します..."
    scp ${REMOTE_HOST}:${REMOTE_PATH}/backend/.env backend/.env
    echo "✅ .envファイルをダウンロードしました"
    ;;
  2)
    echo "🐍 backendを同期します..."
    rsync -av $EXCLUDE_OPTS ${REMOTE_HOST}:${REMOTE_PATH}/backend/ backend/
    ;;
  3)
    echo "🎨 frontendを同期します..."
    rsync -av $EXCLUDE_OPTS ${REMOTE_HOST}:${REMOTE_PATH}/frontend/ frontend/
    ;;
  4)
    read -p "⚠️  ローカルの変更が上書きされます。続行しますか？ [y/N]: " confirm
    if [[ $confirm == "y" || $confirm == "Y" ]]; then
      echo "📦 全体を同期します..."
      rsync -av $EXCLUDE_OPTS ${REMOTE_HOST}:${REMOTE_PATH}/ .
    else
      echo "❌ キャンセルしました"
      exit 0
    fi
    ;;
  *)
    echo "❌ 無効な選択です"
    exit 1
    ;;
esac

echo ""
echo "=========================================="
echo "✅ 同期が完了しました"
echo "=========================================="


