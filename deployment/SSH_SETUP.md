# SSH設定ガイド - ConoHa VPS

## 📋 目次

1. [初回接続（パスワード認証）](#初回接続パスワード認証)
2. [SSH鍵認証の設定（推奨）](#ssh鍵認証の設定推奨)
3. [SSH設定の最適化](#ssh設定の最適化)
4. [セキュリティ強化](#セキュリティ強化)
5. [トラブルシューティング](#トラブルシューティング)

---

## 初回接続（パスワード認証）

### Mac/Linuxから接続

```bash
# 基本的な接続
ssh root@160.251.172.234

# 初回接続時の警告
# "The authenticity of host '160.251.172.234' can't be established."
# → "yes" と入力

# パスワードを入力（ConoHaで設定したrootパスワード）
```

### Windowsから接続

#### Windows 10/11（標準のSSH）

```cmd
# コマンドプロンプトまたはPowerShell
ssh root@160.251.172.234
```

#### PuTTYを使用する場合

1. PuTTYをダウンロード: https://www.putty.org/
2. Host Name: `160.251.172.234`
3. Port: `22`
4. Connection type: `SSH`
5. 「Open」をクリック
6. rootパスワードを入力

---

## SSH鍵認証の設定（推奨）

パスワード認証よりも**安全で便利**です！

### ステップ1: ローカルマシンでSSH鍵を生成

```bash
# SSH鍵のペアを生成（Mac/Linux）
ssh-keygen -t ed25519 -C "your_email@example.com"

# 保存場所（デフォルトでOK）
# Enter file in which to save the key (/Users/username/.ssh/id_ed25519): [Enter]

# パスフレーズ設定（推奨）
# Enter passphrase (empty for no passphrase): [パスフレーズ入力]
# Enter same passphrase again: [パスフレーズ再入力]

# 鍵が生成されました
# Your identification has been saved in /Users/username/.ssh/id_ed25519
# Your public key has been saved in /Users/username/.ssh/id_ed25519.pub
```

### ステップ2: 公開鍵をサーバーにコピー

#### 方法A: ssh-copy-id を使用（簡単！）

```bash
# Mac/Linuxの場合
ssh-copy-id -i ~/.ssh/id_ed25519.pub root@160.251.172.234

# パスワードを入力すると、自動的に公開鍵がコピーされる
```

#### 方法B: 手動でコピー

```bash
# 1. ローカルで公開鍵の内容を表示
cat ~/.ssh/id_ed25519.pub
# 出力例: ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAILrxxx... your_email@example.com

# 2. サーバーにログイン
ssh root@160.251.172.234

# 3. サーバーで .ssh ディレクトリを作成
mkdir -p ~/.ssh
chmod 700 ~/.ssh

# 4. authorized_keys ファイルに公開鍵を追加
nano ~/.ssh/authorized_keys
# ↑ ローカルでコピーした公開鍵の内容を貼り付け
# Ctrl+X → Y → Enter で保存

# 5. パーミッション設定
chmod 600 ~/.ssh/authorized_keys

# 6. 一旦ログアウト
exit
```

### ステップ3: 鍵認証でログイン

```bash
# パスワード不要で接続できる！
ssh root@160.251.172.234

# または鍵ファイルを明示的に指定
ssh -i ~/.ssh/id_ed25519 root@160.251.172.234
```

---

## SSH設定の最適化

### ローカルマシンの ~/.ssh/config 設定

**この設定をすると、`ssh conoha` だけで接続できる！**

```bash
# Mac/Linux
nano ~/.ssh/config

# 以下を追加
Host conoha
    HostName 160.251.172.234
    User root
    IdentityFile ~/.ssh/id_ed25519
    Port 22
    ServerAliveInterval 60
    ServerAliveCountMax 3

# 複数のユーザーを設定する場合
Host conoha-root
    HostName 160.251.172.234
    User root
    IdentityFile ~/.ssh/id_ed25519

Host conoha-deployer
    HostName 160.251.172.234
    User deployer
    IdentityFile ~/.ssh/id_ed25519
```

**パーミッション設定:**

```bash
chmod 600 ~/.ssh/config
```

**使い方:**

```bash
# 超簡単！
ssh conoha

# 別名で接続
ssh conoha-deployer
```

---

## セキュリティ強化

### 1. 作業用ユーザーの作成

```bash
# サーバーにrootでログイン
ssh root@160.251.172.234

# 作業用ユーザーを作成
adduser deployer
# パスワードを設定
# その他の質問はEnterでスキップ可

# sudo権限を付与
usermod -aG sudo deployer

# deployer用のSSH鍵設定
# ユーザーを切り替え
su - deployer

# .sshディレクトリ作成
mkdir -p ~/.ssh
chmod 700 ~/.ssh

# authorized_keysにローカルの公開鍵を追加
# （rootと同じ公開鍵を使用可能）
exit  # rootに戻る
cp /root/.ssh/authorized_keys /home/deployer/.ssh/
chown deployer:deployer /home/deployer/.ssh/authorized_keys
chmod 600 /home/deployer/.ssh/authorized_keys

# テスト接続（別のターミナルで）
ssh deployer@160.251.172.234
```

### 2. rootログインの無効化

**⚠️ 注意: deployerユーザーで接続できることを確認してから実行！**

```bash
# サーバーでSSH設定を編集
sudo nano /etc/ssh/sshd_config

# 以下の行を変更
PermitRootLogin yes  →  PermitRootLogin no

# パスワード認証も無効化（鍵認証のみ許可）
PasswordAuthentication yes  →  PasswordAuthentication no

# SSH再起動
sudo systemctl restart sshd
```

### 3. SSHポートの変更（オプション）

デフォルトの22番から変更すると攻撃を減らせます。

```bash
# SSH設定を編集
sudo nano /etc/ssh/sshd_config

# ポート番号を変更
Port 22  →  Port 2222

# ファイアウォールで新しいポートを許可
sudo ufw allow 2222/tcp

# SSH再起動
sudo systemctl restart sshd

# 次回からの接続方法
ssh -p 2222 deployer@160.251.172.234

# ~/.ssh/config にも追記
Host conoha
    HostName 160.251.172.234
    User deployer
    Port 2222
    IdentityFile ~/.ssh/id_ed25519
```

### 4. Fail2Ban の設定（ブルートフォース攻撃対策）

```bash
# インストール
sudo apt install fail2ban -y

# 設定ファイルのコピー
sudo cp /etc/fail2ban/jail.conf /etc/fail2ban/jail.local

# 設定編集
sudo nano /etc/fail2ban/jail.local

# [sshd] セクションで以下を設定
[sshd]
enabled = true
port = ssh
filter = sshd
logpath = /var/log/auth.log
maxretry = 5
bantime = 3600
findtime = 600

# サービス開始
sudo systemctl enable fail2ban
sudo systemctl start fail2ban

# 状態確認
sudo fail2ban-client status
sudo fail2ban-client status sshd
```

---

## SSH設定ファイルの全体像

### サーバー側: /etc/ssh/sshd_config

**推奨設定:**

```bash
# 基本設定
Port 22  # または 2222 など
ListenAddress 0.0.0.0
Protocol 2

# 認証設定
PermitRootLogin no  # rootログイン無効化
PasswordAuthentication no  # パスワード認証無効化
PubkeyAuthentication yes  # 鍵認証有効化
AuthorizedKeysFile .ssh/authorized_keys

# セキュリティ設定
PermitEmptyPasswords no
ChallengeResponseAuthentication no
UsePAM yes
X11Forwarding no
PrintMotd no
AcceptEnv LANG LC_*

# 接続タイムアウト
ClientAliveInterval 300
ClientAliveCountMax 2

# ログ設定
SyslogFacility AUTH
LogLevel INFO
```

**設定を反映:**

```bash
# 設定のテスト
sudo sshd -t

# エラーがなければ再起動
sudo systemctl restart sshd
```

### クライアント側: ~/.ssh/config

```bash
# デフォルト設定
Host *
    ServerAliveInterval 60
    ServerAliveCountMax 3
    TCPKeepAlive yes
    Compression yes

# ConoHa VPSの設定
Host conoha
    HostName 160.251.172.234
    User deployer
    Port 22
    IdentityFile ~/.ssh/id_ed25519
    ForwardAgent no
    StrictHostKeyChecking ask
    UserKnownHostsFile ~/.ssh/known_hosts

# 開発環境用（便利設定）
Host conoha-dev
    HostName 160.251.172.234
    User deployer
    Port 22
    IdentityFile ~/.ssh/id_ed25519
    LocalForward 8000 localhost:8000  # ポートフォワーディング
    LocalForward 3306 localhost:3306
```

---

## よく使うSSHコマンド

### 基本接続

```bash
# 通常の接続
ssh username@160.251.172.234

# ポート指定
ssh -p 2222 username@160.251.172.234

# 鍵ファイル指定
ssh -i ~/.ssh/id_ed25519 username@160.251.172.234

# 詳細ログ表示（トラブルシューティング用）
ssh -v username@160.251.172.234
ssh -vv username@160.251.172.234  # より詳細
ssh -vvv username@160.251.172.234  # 最も詳細
```

### ファイル転送

```bash
# ローカル → サーバー
scp file.txt root@160.251.172.234:/opt/

# サーバー → ローカル
scp root@160.251.172.234:/opt/file.txt ./

# ディレクトリごと転送
scp -r ./directory root@160.251.172.234:/opt/

# rsync（差分転送、高速）
rsync -av ./directory/ root@160.251.172.234:/opt/directory/
```

### ポートフォワーディング

```bash
# ローカルポートフォワーディング
# サーバーの8000番をローカルの8000番に転送
ssh -L 8000:localhost:8000 root@160.251.172.234

# MySQLへの接続
ssh -L 3306:localhost:3306 root@160.251.172.234
# → ローカルから localhost:3306 でサーバーのMySQLに接続可能
```

### コマンドの実行

```bash
# サーバーでコマンドを実行して結果を取得
ssh root@160.251.172.234 'ls -la /opt'

# 複数コマンド
ssh root@160.251.172.234 'cd /opt && ls -la'

# ローカルスクリプトをサーバーで実行
ssh root@160.251.172.234 'bash -s' < local_script.sh
```

---

## トラブルシューティング

### 1. 接続できない

```bash
# 詳細ログで確認
ssh -vvv root@160.251.172.234

# よくある原因:
# - IPアドレスが間違っている
# - ファイアウォールでポートが閉じられている
# - SSHサービスが起動していない
```

### 2. "Permission denied (publickey)"

```bash
# 原因1: 公開鍵が正しく設定されていない
# サーバーで確認
cat ~/.ssh/authorized_keys

# 原因2: パーミッションが間違っている
# 正しいパーミッション
chmod 700 ~/.ssh
chmod 600 ~/.ssh/authorized_keys

# 原因3: 鍵ファイルのパス間違い
ssh -i ~/.ssh/id_ed25519 root@160.251.172.234
```

### 3. "Too many authentication failures"

```bash
# SSH agentの鍵を確認
ssh-add -l

# 不要な鍵を削除
ssh-add -D

# 必要な鍵のみ追加
ssh-add ~/.ssh/id_ed25519
```

### 4. 接続が切れる

```bash
# ~/.ssh/config に追加
ServerAliveInterval 60
ServerAliveCountMax 3
TCPKeepAlive yes
```

### 5. "WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED"

```bash
# known_hosts からホストを削除
ssh-keygen -R 160.251.172.234

# または該当行を削除
nano ~/.ssh/known_hosts
```

---

## セキュリティチェックリスト

設定完了後、以下を確認してください：

- [ ] SSH鍵認証が動作している
- [ ] パスワード認証が無効になっている
- [ ] rootログインが無効になっている（作業用ユーザーで接続可能）
- [ ] ファイアウォール（UFW）でSSHポートのみ許可
- [ ] Fail2banが動作している
- [ ] 鍵ファイルのパーミッションが正しい（600）
- [ ] ~/.ssh/config のパーミッションが正しい（600）
- [ ] 定期的にSSHログを確認
  ```bash
  sudo tail -f /var/log/auth.log
  ```

---

## 便利なTips

### SSH接続を高速化

```bash
# ~/.ssh/config に追加
Host *
    ControlMaster auto
    ControlPath ~/.ssh/control-%r@%h:%p
    ControlPersist 10m
```

### SSH agentの使用

```bash
# SSH agentに鍵を追加（パスフレーズを1回だけ入力）
ssh-add ~/.ssh/id_ed25519

# 登録されている鍵を確認
ssh-add -l

# すべての鍵を削除
ssh-add -D
```

### SSHバナーの表示

```bash
# サーバーで /etc/ssh/banner を作成
sudo nano /etc/ssh/banner

# 内容例:
*********************************************
*  Prompt Provision Tool Server           *
*  Unauthorized access is prohibited.     *
*********************************************

# sshd_config に追加
sudo nano /etc/ssh/sshd_config
# Banner /etc/ssh/banner

# SSH再起動
sudo systemctl restart sshd
```

---

## まとめ：推奨設定の手順

```bash
# 1. SSH鍵の生成（ローカル）
ssh-keygen -t ed25519 -C "your_email@example.com"

# 2. 公開鍵をサーバーにコピー
ssh-copy-id root@160.251.172.234

# 3. 作業用ユーザーの作成（サーバー）
adduser deployer
usermod -aG sudo deployer

# 4. deployerにも鍵を設定
sudo cp /root/.ssh/authorized_keys /home/deployer/.ssh/
sudo chown deployer:deployer /home/deployer/.ssh/authorized_keys

# 5. 接続テスト
ssh deployer@160.251.172.234

# 6. セキュリティ設定
sudo nano /etc/ssh/sshd_config
# PermitRootLogin no
# PasswordAuthentication no

# 7. SSH再起動
sudo systemctl restart sshd

# 8. Fail2banのインストール
sudo apt install fail2ban -y
sudo systemctl enable fail2ban

# 9. ~/.ssh/config の設定（ローカル）
nano ~/.ssh/config
# Host conoha の設定を追加
```

---

これで安全で便利なSSH環境が完成です！🔐


