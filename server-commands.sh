#!/bin/bash

# サーバー管理用コマンド集

echo "=========================================="
echo "サーバー管理コマンド"
echo "=========================================="
echo ""

# メニュー
echo "実行したい操作を選択してください："
echo "1. サービス再起動"
echo "2. サービス状態確認"
echo "3. ログ確認（リアルタイム）"
echo "4. ログ確認（最新50行）"
echo "5. サーバー内でアプリ動作確認"
echo "6. .envファイルの確認（機密情報注意）"
echo "7. データベース接続確認"
echo "8. 全体のヘルスチェック"
echo ""
read -p "選択 [1-8]: " choice

case $choice in
  1)
    echo "🔄 サービスを再起動中..."
    ssh conoha "sudo systemctl restart prompt-tool && sudo systemctl restart nginx"
    sleep 2
    ssh conoha "sudo systemctl status prompt-tool --no-pager | head -20"
    ;;
  2)
    echo "📊 サービス状態を確認中..."
    ssh conoha "sudo systemctl status prompt-tool --no-pager"
    echo "---"
    ssh conoha "sudo systemctl status nginx --no-pager | head -15"
    ;;
  3)
    echo "📝 ログをリアルタイム表示（Ctrl+Cで終了）..."
    ssh conoha "sudo journalctl -u prompt-tool -f"
    ;;
  4)
    echo "📝 最新ログ（50行）..."
    ssh conoha "sudo journalctl -u prompt-tool -n 50 --no-pager"
    ;;
  5)
    echo "🧪 サーバー内部でアプリ動作確認..."
    ssh conoha "curl -s http://localhost/ | head -30"
    echo ""
    echo "---"
    ssh conoha "curl -I http://localhost:8000/docs"
    ;;
  6)
    echo "⚠️  .envファイルの内容（機密情報を含みます）"
    read -p "本当に表示しますか？ [y/N]: " confirm
    if [[ $confirm == "y" || $confirm == "Y" ]]; then
      ssh conoha "cat /opt/prompt-provision-tool/backend/.env"
    fi
    ;;
  7)
    echo "🗄️  データベース接続確認..."
    ssh conoha "mysql -u prompt_tool_user -pYOUR_DB_PASSWORD_HERE -e 'SELECT COUNT(*) as account_count FROM prompt_provision_db.accounts;' 2>/dev/null || echo 'データベース接続エラー'"
    ;;
  8)
    echo "🏥 全体のヘルスチェック..."
    echo ""
    echo "=== FastAPI サービス ==="
    ssh conoha "sudo systemctl is-active prompt-tool && echo '✅ 起動中' || echo '❌ 停止'"
    echo ""
    echo "=== Nginx ==="
    ssh conoha "sudo systemctl is-active nginx && echo '✅ 起動中' || echo '❌ 停止'"
    echo ""
    echo "=== MySQL ==="
    ssh conoha "sudo systemctl is-active mysql && echo '✅ 起動中' || echo '❌ 停止'"
    echo ""
    echo "=== ポート確認 ==="
    ssh conoha "sudo ss -tulpn | grep -E ':(80|8000|3306)' | grep LISTEN"
    echo ""
    echo "=== ディスク使用量 ==="
    ssh conoha "df -h | grep -E 'Filesystem|/$'"
    echo ""
    echo "=== メモリ使用量 ==="
    ssh conoha "free -h"
    ;;
  *)
    echo "❌ 無効な選択です"
    ;;
esac

echo ""
echo "=========================================="


