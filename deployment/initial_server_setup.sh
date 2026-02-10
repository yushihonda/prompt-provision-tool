#!/bin/bash
set -e

echo "=========================================="
echo "ConoHa VPS 初期設定スクリプト (Ubuntu)"
echo "=========================================="

# 1. タイムゾーン設定
echo "[1/4] タイムゾーンを Asia/Tokyo に設定します..."
sudo timedatectl set-timezone Asia/Tokyo
echo "完了: $(date)"

# 2. ユーザー作成
echo ""
echo "[2/4] 作業用sudoユーザーを作成します"
read -p "作成するユーザー名を入力してください (例: demo): " NEW_USER

if [ -z "$NEW_USER" ]; then
    echo "ユーザー名が入力されなかったため、スキップします。"
else
    if id "$NEW_USER" &>/dev/null; then
        echo "ユーザー $NEW_USER は既に存在します。"
    else
        sudo adduser "$NEW_USER"
        sudo usermod -aG sudo "$NEW_USER"
        echo "ユーザー $NEW_USER を作成し、sudo権限を付与しました。"
    fi

    # 3. SSH鍵の設定
    echo ""
    echo "[3/4] SSH公開鍵の設定"
    echo "1: GitHubからインポート (推奨)"
    echo "2: 手動で貼り付け"
    echo "3: スキップ"
    read -p "選択してください (1-3): " SSH_CHOICE

    USER_SSH_DIR="/home/$NEW_USER/.ssh"
    sudo mkdir -p "$USER_SSH_DIR"

    if [ "$SSH_CHOICE" = "1" ]; then
        read -p "GitHubのユーザー名を入力: " GH_USER
        curl -s "https://github.com/$GH_USER.keys" | sudo tee "$USER_SSH_DIR/authorized_keys" > /dev/null
        echo "GitHubから鍵をインポートしました。"
    elif [ "$SSH_CHOICE" = "2" ]; then
        echo "公開鍵(ssh-rsa ...)を貼り付けて、Enterを押してください:"
        read PUBLIC_KEY
        echo "$PUBLIC_KEY" | sudo tee "$USER_SSH_DIR/authorized_keys" > /dev/null
    fi

    if [ "$SSH_CHOICE" = "1" ] || [ "$SSH_CHOICE" = "2" ]; then
        sudo chmod 700 "$USER_SSH_DIR"
        sudo chmod 600 "$USER_SSH_DIR/authorized_keys"
        sudo chown -R "$NEW_USER":"$NEW_USER" "/home/$NEW_USER"
        echo "SSH鍵を設定しました。"
    fi
fi

# 4. SSH設定の堅牢化
echo ""
echo "[4/4] SSHセキュリティ設定"
echo "以下を設定します:"
echo "- PasswordAuthentication no (パスワード認証無効)"
echo "- PermitRootLogin no (Rootログイン無効)"
echo "" 
echo "⚠️ 注意: 事前に公開鍵認証でログインできることを確認してから行ってください。"
read -p "設定を適用しますか？ (y/n): " SECURE_SSH

if [ "$SECURE_SSH" = "y" ] || [ "$SECURE_SSH" = "Y" ]; then
    sudo cp /etc/ssh/sshd_config /etc/ssh/sshd_config.bak
    
    # 設定置換
    # 存在する場合置換、しない場合追記などの複雑な判定を避けるため、sedで一般的な行を置換
    sudo sed -i 's/^#*PasswordAuthentication .*/PasswordAuthentication no/' /etc/ssh/sshd_config
    sudo sed -i 's/^#*PermitRootLogin .*/PermitRootLogin no/' /etc/ssh/sshd_config
    sudo sed -i 's/^#*ChallengeResponseAuthentication .*/ChallengeResponseAuthentication no/' /etc/ssh/sshd_config
    
    # PasswordAuthentication yes が残っている場合に備えて念の為チェック
    if grep -q "^PasswordAuthentication yes" /etc/ssh/sshd_config; then
         sudo sed -i 's/^PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
    fi
    
    sudo systemctl restart ssh
    echo "SSH設定を変更しました。"
else
    echo "SSH設定の変更をスキップしました。"
fi

echo ""
echo "=========================================="
echo "初期設定完了"
echo "=========================================="
if [ ! -z "$NEW_USER" ]; then
    echo "次の手順:"
    echo "1. 別のターミナルを開き、作成したユーザー($NEW_USER)でログインできるか確認してください。"
    echo "   ssh $NEW_USER@<HOST_IP>"
    echo "2. 確認できたら、このセッションをログアウトしてください。"
fi
echo ""
