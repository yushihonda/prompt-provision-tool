# GitHub Actions ワークフロー

## デプロイワークフロー

### `deploy.yml`

mainブランチへのpush/マージ時に、本番サーバーへ自動デプロイを実行します。

#### 必要なGitHub Secrets

リポジトリの Settings > Secrets and variables > Actions で以下を設定してください：

- `SSH_PRIVATE_KEY`: 本番サーバーへのSSH接続用の秘密鍵
- `SERVER_HOST`: 本番サーバーのIPアドレスまたはホスト名
- `SERVER_USER`: SSH接続用のユーザー名

#### デプロイ処理の流れ

1. コードのチェックアウト
2. SSH接続の設定
3. rsyncによるファイル同期（ローカルファイルは除外）
4. データベースマイグレーションの実行
5. Python依存パッケージの更新
6. systemdサービスファイルの更新（FastAPI、Celery Worker）
7. アプリケーションサービスの再起動（FastAPI、Celery Worker）
8. サービス状態の確認
9. ヘルスチェックによる動作確認
10. Redis接続確認

#### 手動実行

GitHub Actionsの画面から、`workflow_dispatch`イベントで手動実行も可能です。

