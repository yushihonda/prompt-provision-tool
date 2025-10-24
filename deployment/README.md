# デプロイメントガイド - ConoHa VPS

## 前提条件

- ConoHa VPS (Ubuntu 22.04 LTS)
- ドメイン名（DNS設定済み）
- root または sudo 権限

## セットアップ手順

### 1. サーバーへの接続

```bash
ssh root@your-server-ip
```

### 2. アプリケーションファイルのアップロード

プロジェクトファイルをサーバーにアップロードします：

```bash
# ローカルマシンから
scp -r /path/to/prompt-provision-tool root@your-server-ip:/opt/
```

または、Gitリポジトリからクローン：

```bash
# サーバー上で
cd /opt
git clone <your-repo-url> prompt-provision-tool
```

### 3. セットアップスクリプトの実行

```bash
cd /opt/prompt-provision-tool/deployment
chmod +x setup.sh
./setup.sh
```

### 4. 環境変数の設定

`.env` ファイルを編集して、適切な値を設定します：

```bash
nano /opt/prompt-provision-tool/backend/.env
```

必須項目：
- `DB_PASSWORD`: MySQLパスワード
- `SECRET_KEY`: セットアップ時に生成されたキー
- `ENCRYPTION_KEY`: セットアップ時に生成されたキー
- `OPENAI_API_KEY`: OpenAI APIキー
- `GEMINI_API_KEY`: Google Gemini APIキー

### 5. Nginx設定の編集

ドメイン名を実際のドメインに変更します：

```bash
sudo nano /etc/nginx/sites-available/prompt-tool
```

`your-domain.com` を実際のドメイン名に置き換えてください。

### 6. SSL証明書の取得（Let's Encrypt）

```bash
sudo certbot --nginx -d your-domain.com
```

証明書の自動更新テスト：

```bash
sudo certbot renew --dry-run
```

### 7. サービスの起動

```bash
sudo systemctl restart prompt-tool
sudo systemctl restart nginx
```

### 8. 動作確認

```bash
# サービスの状態確認
sudo systemctl status prompt-tool
sudo systemctl status nginx

# アプリケーションログ
sudo tail -f /var/log/prompt-tool/app.log

# Nginxログ
sudo tail -f /var/log/nginx/prompt-tool-access.log
sudo tail -f /var/log/nginx/prompt-tool-error.log
```

ブラウザで https://your-domain.com にアクセスして動作を確認します。

## 管理コマンド

### サービスの管理

```bash
# サービスの起動
sudo systemctl start prompt-tool

# サービスの停止
sudo systemctl stop prompt-tool

# サービスの再起動
sudo systemctl restart prompt-tool

# サービスの状態確認
sudo systemctl status prompt-tool
```

### データベース管理

```bash
# MySQLへのログイン
mysql -u prompt_tool_user -p prompt_provision_db

# バックアップ
mysqldump -u prompt_tool_user -p prompt_provision_db > backup.sql

# リストア
mysql -u prompt_tool_user -p prompt_provision_db < backup.sql
```

### アプリケーションの更新

```bash
cd /opt/prompt-provision-tool

# 最新コードの取得
git pull

# 仮想環境のアクティベート
source venv/bin/activate

# パッケージの更新
pip install -r backend/requirements.txt

# マイグレーション実行
cd backend
alembic upgrade head

# サービスの再起動
sudo systemctl restart prompt-tool
```

## トラブルシューティング

### アプリケーションが起動しない

```bash
# ログを確認
sudo journalctl -u prompt-tool -n 50

# 手動で起動してエラーを確認
cd /opt/prompt-provision-tool/backend
source ../venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### データベース接続エラー

```bash
# MySQLの状態確認
sudo systemctl status mysql

# 接続テスト
mysql -u prompt_tool_user -p -e "SHOW DATABASES;"
```

### Nginx 502 Bad Gateway

```bash
# FastAPIが起動しているか確認
sudo systemctl status prompt-tool

# ポート8000がリッスンしているか確認
sudo netstat -tulpn | grep 8000
```

### SSL証明書の更新

```bash
# 手動更新
sudo certbot renew

# 自動更新の設定確認
sudo systemctl status certbot.timer
```

## セキュリティ推奨事項

1. **定期的な更新**
   ```bash
   sudo apt update && sudo apt upgrade -y
   ```

2. **ファイアウォールの確認**
   ```bash
   sudo ufw status
   ```

3. **ログの監視**
   - 定期的にアクセスログとエラーログを確認

4. **バックアップ**
   - データベースの定期バックアップを設定
   - `.env` ファイルのバックアップ

5. **APIキーの管理**
   - APIキーは絶対に公開しない
   - 定期的にキーをローテーション

## パフォーマンスチューニング

### Uvicornワーカー数の調整

`/etc/systemd/system/prompt-tool.service` の `--workers` オプションを調整：

```
ExecStart=/opt/prompt-provision-tool/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 4
```

推奨：CPU コア数 × 2

### Nginxの最適化

`/etc/nginx/nginx.conf` の `worker_processes` を調整：

```nginx
worker_processes auto;
```

## 監視とアラート

### Prometheusとの統合（オプション）

```bash
pip install prometheus-fastapi-instrumentator
```

### ログローテーション

```bash
sudo nano /etc/logrotate.d/prompt-tool
```

```
/var/log/prompt-tool/*.log {
    daily
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 www-data www-data
    sharedscripts
    postrotate
        systemctl reload prompt-tool > /dev/null
    endscript
}
```

## サポート

問題が発生した場合は、以下の情報を確認してください：
- アプリケーションログ: `/var/log/prompt-tool/app.log`
- Nginxログ: `/var/log/nginx/prompt-tool-error.log`
- システムログ: `sudo journalctl -u prompt-tool`

