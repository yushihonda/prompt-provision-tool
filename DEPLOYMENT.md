# デプロイメントガイド

## GitHub Actionsによる自動デプロイ

mainブランチにマージすると、自動的に本番サーバーにデプロイされます。

### セットアップ手順

#### 1. GitHub Secretsの設定

リポジトリの Settings > Secrets and variables > Actions で以下を追加：

- **SSH_PRIVATE_KEY**: 本番サーバーへのSSH接続用の秘密鍵
  - 生成方法: `ssh-keygen -t rsa -b 4096 -C "github-actions" -f ~/.ssh/github_actions_deploy`
  - 秘密鍵（`~/.ssh/github_actions_deploy`）の内容をコピーして設定

- **SERVER_HOST**: 本番サーバーのIPアドレスまたはホスト名
  - 例: `160.251.172.234`

- **SERVER_USER**: SSH接続用のユーザー名
  - 例: `root` または `ubuntu`

#### 2. 本番サーバーでのSSH鍵設定

```bash
# 本番サーバー上で実行
mkdir -p ~/.ssh
# GitHub Actionsの公開鍵を authorized_keys に追加
echo "YOUR_PUBLIC_KEY_HERE" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
chmod 700 ~/.ssh
```

#### 3. sudo権限の設定（必要に応じて）

GitHub Actionsから`sudo systemctl restart`を実行するため、パスワードなしでsudoを実行できるように設定：

```bash
# 本番サーバー上で実行
echo "$SERVER_USER ALL=(ALL) NOPASSWD: /bin/systemctl restart prompt-tool.service, /bin/systemctl status prompt-tool.service" | sudo tee /etc/sudoers.d/prompt-tool-deploy
sudo chmod 440 /etc/sudoers.d/prompt-tool-deploy
```

### デプロイの動作

1. **トリガー**: mainブランチへのpush/マージ
2. **ファイル同期**: rsyncでファイルをアップロード（ローカルファイルは除外）
3. **マイグレーション**: データベースマイグレーションを自動実行
4. **依存パッケージ更新**: requirements.txtに基づいてパッケージを更新
5. **サービス再起動**: systemdサービスを再起動
6. **動作確認**: ヘルスチェックエンドポイントで動作確認

### 除外されるファイル

以下のファイル/ディレクトリは本番環境にデプロイされません：

- `.env`, `.env.local`, `.env.*.local` - 環境変数ファイル
- `venv/` - 仮想環境
- `__pycache__/`, `*.pyc`, `*.pyo` - Pythonキャッシュ
- `*.log` - ログファイル
- `.DS_Store`, `*.swp`, `*.swo` - OS/エディタファイル
- `.vscode/`, `.idea/` - IDE設定
- `backend/uploads/`, `backend/temp/`, `frontend/uploads/` - アップロードファイル
- `docker-compose.local.yml` - ローカル開発用Docker Compose
- `資料/` - ドキュメント

### トラブルシューティング

#### SSH接続エラー

```bash
# 本番サーバーでSSH接続をテスト
ssh -i ~/.ssh/github_actions_deploy $SERVER_USER@$SERVER_HOST
```

#### デプロイが失敗する場合

1. GitHub Actionsのログを確認
2. 本番サーバーで手動デプロイを試行: `sudo bash /opt/prompt-provision-tool/deployment/deploy.sh`
3. サービス状態を確認: `sudo systemctl status prompt-tool.service`

#### 手動デプロイ

GitHub Actionsの画面から、`workflow_dispatch`イベントで手動実行も可能です。
