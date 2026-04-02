# 本番環境デプロイチェックリスト

本番環境（ConoHa VPS）へのデプロイ時に確認すべき項目のチェックリストです。

## デプロイ前の確認事項

### 1. 環境変数の設定

- [ ] `backend/.env` ファイルが作成されている
- [ ] `SECRET_KEY` が設定されている（32文字以上のhex文字列）
- [ ] `ENCRYPTION_KEY` が設定されている（32文字の文字列）
- [ ] `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` が正しく設定されている
- [ ] `OPENAI_API_KEY` が設定されている
- [ ] `GEMINI_API_KEY` が設定されている
- [ ] `ENVIRONMENT=production` が設定されている
- [ ] `CORS_ORIGINS` が本番ドメインに設定されている
- [ ] `REDIS_URL` が設定されている（`redis://localhost:6379/0`）（SSEストリーミング用）

### 2. セキュリティキーの生成

セキュリティキーが未設定の場合は、以下のコマンドで生成：

```bash
# SECRET_KEYの生成
python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32))"

# ENCRYPTION_KEYの生成
python3 -c "import secrets; print('ENCRYPTION_KEY=' + secrets.token_urlsafe(32)[:32])"
```

生成されたキーを `backend/.env` に設定してください。

### 3. データベースの準備

- [ ] MySQLがインストールされている
- [ ] データベースが作成されている
- [ ] データベースユーザーが作成されている
- [ ] データベースのバックアップが取得されている（既存データがある場合）

### 4. Redisの準備

- [ ] Redisがインストールされている
- [ ] Redisが起動している（`sudo systemctl status redis-server`）
- [ ] Redisが自動起動に設定されている（`sudo systemctl enable redis-server`）

### 5. systemdサービスの設定

- [ ] `prompt-tool.service` が `/etc/systemd/system/` に配置されている
- [ ] `prompt-tool-worker.service` が `/etc/systemd/system/` に配置されている
- [ ] サービスが有効化されている（`sudo systemctl enable prompt-tool prompt-tool-worker`）

### 6. Nginx設定

- [ ] `nginx.conf` のドメイン名が実際のドメインに変更されている
- [ ] SSL証明書が取得されている（Let's Encrypt推奨）
- [ ] Nginx設定がテストされている（`sudo nginx -t`）

## デプロイ手順

### 初回デプロイ

1. **セットアップスクリプトの実行**

```bash
bash deployment/setup.sh
```

2. **環境変数の設定**

```bash
cd /opt/prompt-provision-tool/backend
# .envファイルを編集
nano .env
```

3. **データベースマイグレーション**

```bash
cd /opt/prompt-provision-tool/backend
source /opt/prompt-provision-tool/venv/bin/activate
alembic upgrade head
```

4. **初期管理者アカウントの作成**

```bash
python -m app.init_admin
```

5. **サービスの起動**

```bash
sudo systemctl start prompt-tool
sudo systemctl start prompt-tool-worker
sudo systemctl start nginx
```

### 更新デプロイ（GitHub Actions使用）

mainブランチにpush/マージすると自動的にデプロイされます。

### 更新デプロイ（手動）

```bash
# 本番サーバーにSSH接続
ssh user@your-server

# コードの更新（git pull等）
cd /opt/prompt-provision-tool
git pull origin main

# 依存パッケージの更新
cd backend
source /opt/prompt-provision-tool/venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# データベースマイグレーション
alembic upgrade head

# サービスの再起動
sudo systemctl restart prompt-tool
sudo systemctl restart prompt-tool-worker
```

## デプロイ後の確認事項

### 1. サービス状態の確認

```bash
# すべてのサービスが起動していることを確認
sudo systemctl status prompt-tool
sudo systemctl status prompt-tool-worker
sudo systemctl status redis-server
sudo systemctl status nginx
```

### 2. ヘルスチェック

```bash
# アプリケーションのヘルスチェック
curl http://127.0.0.1:8000/health
```

### 3. ログの確認

```bash
# アプリケーションログ
sudo tail -f /var/log/prompt-tool/app.log

# ローカルワーカーログ
sudo tail -f /var/log/prompt-tool/worker.log

# エラーログ
sudo tail -f /var/log/prompt-tool/error.log
sudo tail -f /var/log/prompt-tool/worker-error.log

# Nginxログ
sudo tail -f /var/log/nginx/prompt-tool-error.log
```

### 4. 動作確認

- [ ] 管理者ログインができる
- [ ] プロンプト実行ができる
- [ ] ストリーミングが正常に動作する
- [ ] ファイル出力が正常に動作する
- [ ] 実行履歴が表示される

## トラブルシューティング

### ローカルワーカーが起動しない

```bash
# ログを確認
sudo tail -f /var/log/prompt-tool/worker-error.log

# Redis接続を確認
redis-cli ping

# サービスを再起動
sudo systemctl restart prompt-tool-worker
```

### Redis接続エラー

```bash
# Redisが起動しているか確認
sudo systemctl status redis-server

# Redis接続をテスト
redis-cli ping

# Redisを再起動
sudo systemctl restart redis-server
```

### データベース接続エラー

```bash
# MySQL接続を確認
mysql -u prompt_tool_user -p prompt_provision_db

# 環境変数を確認
cat /opt/prompt-provision-tool/backend/.env | grep DB_
```

### ストリーミングが動作しない

- ローカルワーカーが起動しているか確認
- Redisが起動しているか確認
- ログでエラーがないか確認

## セキュリティ確認

- [ ] `.env` ファイルが適切な権限で保護されている（`chmod 600 .env`）
- [ ] SSL証明書が有効である
- [ ] ファイアウォールが適切に設定されている
- [ ] `/docs` エンドポイントが非公開である（本番環境では自動的に非公開）
- [ ] ログに機密情報が出力されていない

## パフォーマンス確認

- [ ] レスポンス時間が許容範囲内である
- [ ] メモリ使用量が適切である
- [ ] CPU使用率が適切である
- [ ] データベース接続プールが適切に設定されている

## バックアップ

- [ ] データベースのバックアップが取得されている
- [ ] バックアップの復元手順が文書化されている
- [ ] 定期的なバックアップが設定されている（cron等）

