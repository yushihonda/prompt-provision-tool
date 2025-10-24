# プロンプト提供ツール セットアップガイド

このガイドでは、プロンプト提供ツールのローカル開発環境と本番環境（ConoHa VPS）のセットアップ方法を説明します。

## 目次

1. [ローカル開発環境のセットアップ](#ローカル開発環境のセットアップ)
2. [本番環境（ConoHa VPS）のセットアップ](#本番環境conohavpsのセットアップ)
3. [初期データの投入](#初期データの投入)
4. [動作確認](#動作確認)
5. [トラブルシューティング](#トラブルシューティング)

---

## ローカル開発環境のセットアップ

### 前提条件

- Python 3.11+
- MySQL 8.0+
- Git

### 手順

#### 1. リポジトリのクローン

```bash
git clone <repository-url>
cd prompt-provision-tool
```

#### 2. Python仮想環境の作成

```bash
python3.11 -m venv venv
source venv/bin/activate  # Windowsの場合: venv\Scripts\activate
```

#### 3. 依存パッケージのインストール

```bash
cd backend
pip install -r requirements.txt
```

#### 4. MySQLデータベースの作成

```bash
mysql -u root -p
```

MySQL内で以下を実行：

```sql
CREATE DATABASE prompt_provision_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'prompt_tool_user'@'localhost' IDENTIFIED BY 'your_password';
GRANT ALL PRIVILEGES ON prompt_provision_db.* TO 'prompt_tool_user'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

#### 5. 環境変数の設定

```bash
cp .env.example backend/.env
```

`backend/.env` を編集：

```env
# Database
DB_HOST=localhost
DB_PORT=3306
DB_USER=prompt_tool_user
DB_PASSWORD=your_password
DB_NAME=prompt_provision_db

# Security - 以下のコマンドで生成
# python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=your-generated-secret-key

# Encryption - 32文字のキー
# python -c "import secrets; print(secrets.token_urlsafe(32)[:32])"
ENCRYPTION_KEY=your-32-char-encryption-key

# AI API Keys
OPENAI_API_KEY=sk-your-openai-api-key
GEMINI_API_KEY=your-gemini-api-key

# Application
ENVIRONMENT=development
```

#### 6. データベースマイグレーション

```bash
cd backend
alembic upgrade head
```

#### 7. 初期管理者アカウントの作成

```bash
python -m app.init_admin
```

プロンプトに従って管理者アカウント情報を入力してください。

#### 8. アプリケーションの起動

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

ブラウザで http://localhost:8000 にアクセスして動作を確認します。

---

## 本番環境（ConoHa VPS）のセットアップ

### 前提条件

- ConoHa VPS (Ubuntu 22.04 LTS推奨)
- ドメイン名（DNS設定済み）
- root または sudo 権限

### 手順

#### 1. サーバーへの接続

```bash
ssh root@your-server-ip
```

#### 2. ファイルのアップロード

**方法A: SCP でアップロード**

ローカルマシンから：

```bash
scp -r /path/to/prompt-provision-tool root@your-server-ip:/opt/
```

**方法B: Git からクローン**

サーバー上で：

```bash
cd /opt
git clone <repository-url> prompt-provision-tool
```

#### 3. セットアップスクリプトの実行

```bash
cd /opt/prompt-provision-tool/deployment
chmod +x setup.sh

# スクリプトを実行（途中でデータベースパスワードなどを設定）
sudo ./setup.sh
```

#### 4. 環境変数の設定

生成された `.env` ファイルを編集：

```bash
nano /opt/prompt-provision-tool/backend/.env
```

以下の値を必ず設定：
- `DB_PASSWORD`: セットアップ時に設定したMySQLパスワード
- `SECRET_KEY`: セットアップ時に生成されたキー
- `ENCRYPTION_KEY`: セットアップ時に生成されたキー
- `OPENAI_API_KEY`: OpenAI APIキー
- `GEMINI_API_KEY`: Google Gemini APIキー

#### 5. Nginx設定の編集

```bash
sudo nano /etc/nginx/sites-available/prompt-tool
```

`your-domain.com` を実際のドメイン名に変更してください（複数箇所）。

#### 6. SSL証明書の取得

```bash
sudo certbot --nginx -d your-domain.com
```

メールアドレスと利用規約への同意を求められます。

#### 7. サービスの起動

```bash
sudo systemctl restart prompt-tool
sudo systemctl restart nginx
```

#### 8. 動作確認

```bash
# サービスの状態確認
sudo systemctl status prompt-tool
sudo systemctl status nginx

# ログの確認
sudo tail -f /var/log/prompt-tool/app.log
```

ブラウザで `https://your-domain.com` にアクセスして動作を確認します。

---

## 初期データの投入

### 管理者アカウントの作成

```bash
cd /opt/prompt-provision-tool/backend
source ../venv/bin/activate
python -m app.init_admin
```

### サンプルプロンプトの登録

管理者ログインして、管理画面からプロンプトを作成します。

**プロンプト例1: シンプルな要約プロンプト**

- **名前**: テキスト要約
- **説明**: 入力されたテキストを簡潔に要約します
- **モデル**: GPT-4 Turbo
- **プロンプト内容**:
  ```
  以下のテキストを3行で要約してください。

  {{input}}
  ```

**プロンプト例2: ファクトチェッカー（質問文に記載されているようなもの）**

- **名前**: ファクトチェック
- **説明**: 記事の見出しごとにファクトチェックを実行
- **モデル**: Gemini 2.5 Pro
- **プロンプト内容**: （質問文の長いプロンプトをそのまま使用）

### 子アカウントの作成とプロンプト割り当て

1. 管理画面「アカウント管理」から子アカウントを作成
2. 作成したアカウントに対して「プロンプト割り当て」でプロンプトを割り当て

---

## 動作確認

### 管理者側のテスト

1. `https://your-domain.com/static/admin/login.html` にアクセス
2. 管理者アカウントでログイン
3. ダッシュボードで統計情報が表示されるか確認
4. プロンプト管理でプロンプトの作成・編集・削除をテスト
5. アカウント管理で子アカウントの作成とプロンプト割り当てをテスト

### ユーザー側のテスト

1. `https://your-domain.com/static/user/login.html` にアクセス
2. 子アカウントでログイン
3. 割り当てられたプロンプト一覧が表示されるか確認
4. プロンプトを実行して結果が返ってくるか確認
5. 実行履歴が正しく記録されているか確認

### API テスト

```bash
# ヘルスチェック
curl https://your-domain.com/health

# APIドキュメント
# ブラウザで https://your-domain.com/docs にアクセス
```

---

## トラブルシューティング

### アプリケーションが起動しない

**症状**: `systemctl status prompt-tool` が失敗している

**解決策**:
```bash
# ログを確認
sudo journalctl -u prompt-tool -n 100

# 手動起動してエラーを確認
cd /opt/prompt-provision-tool/backend
source ../venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### データベース接続エラー

**症状**: `Could not connect to database`

**解決策**:
```bash
# MySQLの状態確認
sudo systemctl status mysql

# パスワードと接続テスト
mysql -u prompt_tool_user -p -h localhost prompt_provision_db

# .envファイルの設定を再確認
cat /opt/prompt-provision-tool/backend/.env | grep DB_
```

### Nginx 502 Bad Gateway

**症状**: ブラウザで502エラーが表示される

**解決策**:
```bash
# FastAPIが起動しているか確認
sudo systemctl status prompt-tool

# ポート8000がリッスンしているか確認
sudo ss -tulpn | grep 8000

# Nginxのエラーログを確認
sudo tail -f /var/log/nginx/prompt-tool-error.log
```

### AI APIエラー

**症状**: プロンプト実行時にエラーが発生

**解決策**:
```bash
# APIキーが正しく設定されているか確認
cd /opt/prompt-provision-tool/backend
source ../venv/bin/activate
python -c "from app.config import settings; print('OpenAI:', settings.OPENAI_API_KEY[:10]); print('Gemini:', settings.GEMINI_API_KEY[:10])"

# 実行ログを確認
sudo tail -f /var/log/prompt-tool/app.log
```

### プロンプトが復号化できない

**症状**: `復号化に失敗しました` エラー

**解決策**:
- `ENCRYPTION_KEY` が32文字であることを確認
- プロンプト作成時と同じ `ENCRYPTION_KEY` を使用していることを確認
- キーを変更した場合は、既存のプロンプトを再作成する必要があります

---

## セキュリティチェックリスト

本番環境デプロイ前に以下を確認してください：

- [ ] `.env` ファイルのパーミッションが適切（600または400）
- [ ] デフォルトの管理者パスワードを変更済み
- [ ] ファイアウォール（UFW）が有効で、必要なポートのみ開放
- [ ] SSL証明書が正しく設定されている
- [ ] データベースのrootパスワードが強固
- [ ] API キーが環境変数で管理されており、コードに含まれていない
- [ ] ログファイルのパーミッションが適切
- [ ] 定期的なバックアップが設定されている

---

## 次のステップ

第1段階のセットアップが完了したら、以下の機能追加を検討してください：

1. **第2段階: セキュリティ強化**
   - レート制限の実装
   - IPホワイトリスト機能
   - CSRF対策の追加

2. **監視とアラート**
   - Prometheus/Grafanaの導入
   - ログ監視とアラート通知

3. **バックアップ自動化**
   - データベースの自動バックアップスクリプト
   - 定期的なバックアップスケジュール

4. **パフォーマンス最適化**
   - キャッシング戦略の実装
   - データベースインデックスの最適化

---

## サポート

問題が解決しない場合は、以下の情報を収集してサポートに連絡してください：

- エラーログ: `/var/log/prompt-tool/app.log`
- Nginxログ: `/var/log/nginx/prompt-tool-error.log`
- システムログ: `journalctl -u prompt-tool -n 200`
- 環境情報: OS、Pythonバージョン、MySQLバージョン

