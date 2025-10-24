# ConoHa VPS 初期設定ガイド

## 📋 ConoHa VPS の推奨スペック

### 今回のツールに必要なスペック

| 項目 | 推奨スペック | 理由 |
|------|------------|------|
| **メモリ** | 2GB以上 | Python + MySQL + Nginx を同時稼働 |
| **CPU** | 2コア以上 | FastAPIのマルチワーカー対応 |
| **ストレージ** | 50GB SSD | OS + アプリ + ログ + DB |
| **OS** | Ubuntu 22.04 LTS | 安定性と長期サポート |

### ConoHa VPSのプラン例

- **512MBプラン**: ❌ メモリ不足の可能性
- **1GBプラン**: △ 最低限動作（本番運用は厳しい）
- **2GBプラン**: ✅ **推奨**（月額1,000円程度）
- **4GBプラン**: ✅ より安定（複数ユーザー対応）

---

## 🚀 ConoHa VPS 初期設定手順

### 1. VPSの契約・作成

1. **ConoHa VPSにログイン**
   - https://www.conoha.jp/

2. **サーバー追加**
   - サービス: VPS
   - リージョン: 東京
   - プラン: 2GB推奨
   - イメージタイプ: **Ubuntu 22.04**
   - rootパスワード: 強固なパスワードを設定

3. **作成完了後、IPアドレスを確認**
   - 例: `160.251.172.234`

### 2. 初回SSH接続

ローカルマシンから接続：

```bash
ssh root@160.251.172.234
```

初回接続時は以下の警告が出ます（正常）：
```
The authenticity of host '160.251.172.234' can't be established.
```
→ `yes` と入力して続行

### 3. 最初にやるべき基本設定

#### A. システムの更新

```bash
# パッケージリストの更新
apt update

# すべてのパッケージを最新化
apt upgrade -y

# 不要パッケージの削除
apt autoremove -y
```

#### B. タイムゾーンの設定

```bash
# 日本時間に設定
timedatectl set-timezone Asia/Tokyo

# 確認
date
```

#### C. ホスト名の設定（オプション）

```bash
# わかりやすい名前に変更
hostnamectl set-hostname prompt-tool-server

# 確認
hostname
```

#### D. ロケールの設定

```bash
# 日本語と英語のロケールを有効化
locale-gen ja_JP.UTF-8 en_US.UTF-8

# システムのデフォルトを英語に
update-locale LANG=en_US.UTF-8
```

---

## 🔒 セキュリティ基本設定

### 1. rootログインの無効化（推奨）

```bash
# 作業用ユーザーの作成
adduser deployer
# パスワードを設定

# sudoグループに追加
usermod -aG sudo deployer

# SSH接続テスト（別のターミナルで）
ssh deployer@160.251.172.234

# 動作確認後、rootログインを無効化
nano /etc/ssh/sshd_config
# ↓ この行を変更
PermitRootLogin no

# SSH再起動
systemctl restart sshd
```

### 2. SSHポートの変更（オプション・推奨）

```bash
# SSH設定ファイルを編集
nano /etc/ssh/sshd_config

# 以下の行を変更
Port 22  →  Port 2222  # 任意のポート番号

# SSH再起動
systemctl restart sshd

# 次回からの接続方法
ssh -p 2222 root@160.251.172.234
```

### 3. ファイアウォールの設定

```bash
# UFW（ファイアウォール）の設定
ufw allow 22/tcp      # SSH（ポート変更した場合は変更後の番号）
ufw allow 80/tcp      # HTTP
ufw allow 443/tcp     # HTTPS
ufw --force enable    # 有効化

# 確認
ufw status
```

### 4. Fail2ban の設定（ブルートフォース攻撃対策）

```bash
# インストール
apt install fail2ban -y

# 設定ファイルのコピー
cp /etc/fail2ban/jail.conf /etc/fail2ban/jail.local

# 設定編集
nano /etc/fail2ban/jail.local

# [sshd] セクションで以下を確認
# enabled = true
# maxretry = 5
# bantime = 3600

# サービス開始
systemctl enable fail2ban
systemctl start fail2ban

# 状態確認
fail2ban-client status
```

---

## 🛠️ 今回のツールで使用する構成

### インストールするソフトウェア

| ソフトウェア | バージョン | 用途 | ポート |
|------------|----------|------|-------|
| **Python** | 3.11+ | バックエンド実行環境 | - |
| **FastAPI** | 最新 | Webアプリケーションフレームワーク | - |
| **Uvicorn** | 最新 | ASGIサーバー | 8000 (内部) |
| **MySQL** | 8.0+ | データベース | 3306 (内部) |
| **Nginx** | 最新 | Webサーバー・リバースプロキシ | 80, 443 |
| **systemd** | システム標準 | プロセス管理 | - |

### ディレクトリ構成

```
/opt/
└── prompt-provision-tool/          # アプリケーションルート
    ├── backend/
    │   ├── app/                    # Pythonアプリケーション
    │   ├── alembic/                # DBマイグレーション
    │   ├── .env                    # 環境変数（重要！）
    │   └── requirements.txt
    ├── frontend/
    │   ├── admin/                  # 管理画面HTML
    │   ├── user/                   # ユーザー画面HTML
    │   └── css/
    ├── deployment/
    │   ├── nginx.conf
    │   └── prompt-tool.service
    └── venv/                       # Python仮想環境

/etc/
├── nginx/
│   └── sites-available/
│       └── prompt-tool             # Nginx設定
└── systemd/system/
    └── prompt-tool.service         # systemdサービス

/var/log/
├── prompt-tool/                    # アプリログ
│   ├── app.log
│   └── error.log
└── nginx/                          # Nginxログ
    ├── prompt-tool-access.log
    └── prompt-tool-error.log
```

### ポート使用状況

| ポート | 用途 | 外部アクセス | 備考 |
|-------|------|------------|------|
| **80** | HTTP | ✅ 可 | Nginxが受付 |
| **443** | HTTPS | ✅ 可 | SSL設定後 |
| **8000** | FastAPI | ❌ 不可 | 内部のみ（127.0.0.1） |
| **3306** | MySQL | ❌ 不可 | 内部のみ（localhost） |
| **22** | SSH | ✅ 可 | 管理用 |

### データフロー

```
インターネット
    ↓
[ポート80/443] Nginx
    ↓ リバースプロキシ
[ポート8000] FastAPI (Uvicorn)
    ↓ データベース接続
[ポート3306] MySQL
```

---

## 📦 必要なパッケージ一覧

### システムパッケージ（apt）

```bash
# 必須パッケージ
apt install -y \
  python3.11 \
  python3.11-venv \
  python3-pip \
  mysql-server \
  nginx \
  git \
  ufw \
  curl \
  wget

# セキュリティパッケージ（推奨）
apt install -y \
  fail2ban \
  certbot \
  python3-certbot-nginx
```

### Pythonパッケージ（pip）

`backend/requirements.txt` に記載：

```txt
# FastAPI Core
fastapi==0.109.0
uvicorn[standard]==0.27.0
pydantic==2.5.3
pydantic-settings==2.1.0

# Database
SQLAlchemy==2.0.25
pymysql==1.1.0
cryptography==42.0.0
alembic==1.13.1

# Authentication
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
python-multipart==0.0.6

# AI APIs
openai==1.10.0
google-generativeai==0.3.2

# Utilities
python-dotenv==1.0.0
aiofiles==23.2.1
httpx==0.26.0
```

---

## 💾 データベース設定

### MySQL初期設定

```bash
# MySQLのセキュア設定
mysql_secure_installation

# 質問への回答例:
# - Set root password? → Y（rootパスワード設定）
# - Remove anonymous users? → Y
# - Disallow root login remotely? → Y
# - Remove test database? → Y
# - Reload privilege tables? → Y
```

### アプリ用データベース作成

```bash
mysql -u root -p

# MySQL内で実行
CREATE DATABASE prompt_provision_db 
  CHARACTER SET utf8mb4 
  COLLATE utf8mb4_unicode_ci;

CREATE USER 'prompt_tool_user'@'localhost' 
  IDENTIFIED BY 'your_secure_password';

GRANT ALL PRIVILEGES ON prompt_provision_db.* 
  TO 'prompt_tool_user'@'localhost';

FLUSH PRIVILEGES;
EXIT;
```

---

## 🔑 環境変数の設定

`/opt/prompt-provision-tool/backend/.env` ファイル：

```env
# Database Configuration
DB_HOST=localhost
DB_PORT=3306
DB_USER=prompt_tool_user
DB_PASSWORD=your_secure_password_here
DB_NAME=prompt_provision_db

# Security Keys（生成コマンド）
# python3 -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=generated-secret-key-here
ENCRYPTION_KEY=32-character-encryption-key

ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# AI API Keys（必須！）
OPENAI_API_KEY=sk-your-openai-api-key
GEMINI_API_KEY=your-gemini-api-key

# Application Settings
APP_HOST=0.0.0.0
APP_PORT=8000
CORS_ORIGINS=http://160.251.172.234

# Environment
ENVIRONMENT=production
```

---

## 🚦 サービスの管理

### systemd サービスコマンド

```bash
# サービスの起動
sudo systemctl start prompt-tool

# サービスの停止
sudo systemctl stop prompt-tool

# サービスの再起動
sudo systemctl restart prompt-tool

# サービスの状態確認
sudo systemctl status prompt-tool

# 自動起動の有効化
sudo systemctl enable prompt-tool

# 自動起動の無効化
sudo systemctl disable prompt-tool

# ログのリアルタイム確認
sudo journalctl -u prompt-tool -f
```

### Nginx コマンド

```bash
# 設定ファイルのテスト
sudo nginx -t

# Nginxの再起動
sudo systemctl restart nginx

# Nginxの状態確認
sudo systemctl status nginx

# ログの確認
sudo tail -f /var/log/nginx/prompt-tool-access.log
sudo tail -f /var/log/nginx/prompt-tool-error.log
```

### MySQL コマンド

```bash
# MySQLの起動・停止
sudo systemctl start mysql
sudo systemctl stop mysql
sudo systemctl restart mysql

# MySQLの状態確認
sudo systemctl status mysql

# MySQLへのログイン
mysql -u prompt_tool_user -p prompt_provision_db
```

---

## 📊 リソース監視

### メモリ使用量の確認

```bash
# メモリ状況
free -h

# プロセスごとのメモリ使用量
ps aux --sort=-%mem | head -10
```

### ディスク使用量の確認

```bash
# ディスク全体
df -h

# ディレクトリごと
du -sh /opt/prompt-provision-tool/*
du -sh /var/log/*
```

### CPU使用率の確認

```bash
# リアルタイム監視
top

# または
htop  # 要インストール: apt install htop
```

---

## 🔧 トラブルシューティング

### よくある問題と解決方法

#### 1. メモリ不足

**症状**: アプリが突然停止する

**解決策**:
```bash
# スワップファイルの作成（2GB）
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# 永続化
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

#### 2. ポート競合

**症状**: `Address already in use`

**解決策**:
```bash
# ポート使用状況の確認
sudo ss -tulpn | grep :8000
sudo ss -tulpn | grep :80

# プロセスの終了
sudo kill <PID>
```

#### 3. データベース接続エラー

**症状**: `Can't connect to MySQL server`

**解決策**:
```bash
# MySQLの状態確認
sudo systemctl status mysql

# MySQLの起動
sudo systemctl start mysql

# 接続テスト
mysql -u prompt_tool_user -p -h localhost
```

---

## 📈 本番運用のチェックリスト

### セキュリティチェック

- [ ] rootパスワードを強固なものに変更
- [ ] ファイアウォール（UFW）が有効
- [ ] 不要なポートが閉じられている
- [ ] Fail2banが動作中
- [ ] SSH鍵認証を使用（パスワード認証を無効化）
- [ ] `.env`ファイルのパーミッションが600

### パフォーマンスチェック

- [ ] スワップメモリの設定
- [ ] ログローテーションの設定
- [ ] 不要なサービスの停止
- [ ] Uvicornのワーカー数を調整（CPU数×2）

### バックアップ

- [ ] データベースの定期バックアップスクリプト
- [ ] `.env`ファイルのバックアップ
- [ ] アプリケーションコードのバックアップ

---

## 🎯 まとめ

### 最小構成での実行手順

1. **ConoHa VPSを契約**（2GBプラン、Ubuntu 22.04）
2. **基本設定**: システム更新、タイムゾーン設定
3. **セキュリティ設定**: ファイアウォール、Fail2ban
4. **ファイルアップロード**: rsyncでコードを転送
5. **クイックセットアップ実行**: `quick-setup-commands.sh`
6. **環境変数設定**: APIキーを`.env`に追加
7. **サービス起動**: systemctl restart
8. **動作確認**: ブラウザでアクセス

### 推定所要時間

- VPS契約: 10分
- 初期設定: 20分
- アプリセットアップ: 15分
- 動作確認: 5分
- **合計: 約50分**

---

**次のステップ**: `deployment/SERVER_SETUP.md` を参照して実際のセットアップを開始してください！


