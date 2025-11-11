# マイグレーション実行ガイド

## 概要

このガイドでは、データベースマイグレーションを実行する手順を説明します。

**注意**: テストデータの挿入は `seed_test_data.py` を使用してください（ローカル開発環境のみ）。

## 前提条件

- Docker と Docker Compose がインストールされていること
- `.env.local` ファイルが設定されていること

## 実行手順

### 1. プロジェクトディレクトリに移動

```bash
cd /Users/hondayushi/workspaece/poifull/prompt-provision-tool/prompt-provision-tool
```

### 2. Dockerコンテナの状態を確認

```bash
docker-compose -f docker-compose.local.yml ps
```

### 3. バックエンドコンテナに入る

```bash
docker exec -it ppt-backend bash
```

### 4. マイグレーションの現在の状態を確認（オプション）

```bash
alembic current
alembic history
```

### 5. マイグレーションを実行

```bash
alembic upgrade head
```

または、特定のリビジョンまで実行する場合：

```bash
alembic upgrade 002
```

### 6. 実行結果の確認

マイグレーションが成功すると、以下のようなメッセージが表示されます：

```
✓ テストデータを上書きしました
  管理者: admin / admin@example.com (パスワード: Admin#12345)
  ユーザー: user1 / user1@example.com (パスワード: User#12345)
  プロンプト: 7件
```

### 7. コンテナから出る

```bash
exit
```

## テストデータの挿入（ローカル開発環境のみ）

マイグレーション実行後、テストデータを挿入する場合は `seed_test_data.py` を使用してください：

```bash
# バックエンドコンテナ内で実行
docker exec -it ppt-backend bash
python seed_test_data.py
```

**注意**: 
- `seed_test_data.py` はローカル開発環境でのみ使用してください
- 本番環境では使用しないでください
- 既存データをすべて削除してからテストデータを追加します

## トラブルシューティング

### マイグレーションが失敗する場合

1. **データベース接続エラー**
   ```bash
   # データベースコンテナが起動しているか確認
   docker-compose -f docker-compose.local.yml ps db
   
   # データベースコンテナを再起動
   docker-compose -f docker-compose.local.yml restart db
   ```

2. **マイグレーションの状態をリセット**
   ```bash
   # バックエンドコンテナ内で実行
   alembic downgrade base
   alembic upgrade head
   ```

3. **ログを確認**
   ```bash
   docker logs ppt-backend
   ```

### テストデータが追加されない場合

- エラーメッセージを確認してください
- 暗号化サービスやパスワードハッシュライブラリが正しくインストールされているか確認してください
- `.env.local`の設定が正しいか確認してください

## 追加のコマンド

### マイグレーションを1つ戻す

```bash
alembic downgrade -1
```

### すべてのマイグレーションを元に戻す

```bash
alembic downgrade base
```

### マイグレーションのSQLを確認（実行しない）

```bash
alembic upgrade head --sql
```

## テストデータの詳細（seed_test_data.py）

`seed_test_data.py`を実行すると、以下のテストデータが作成されます：

### アカウント

- **管理者**
  - ユーザー名: `admin`
  - メール: `admin@example.com`
  - パスワード: `Admin#12345`
  - タイプ: `PARENT`

- **ユーザー**
  - ユーザー名: `user1`
  - メール: `user1@example.com`
  - パスワード: `User#12345`
  - タイプ: `CHILD`

### プロンプト（7件）

1. GPT-5 Thinking (`gpt-5-thinking`)
2. GPT-5 Pro (`gpt-5-pro`)
3. GPT-5 (`gpt-5`)
4. GPT-4o Mini (`gpt-4o-mini`)
5. Gemini 2.5 Pro Deep Think (`gemini-2.5-pro-deep-think`)
6. Gemini 2.5 (`gemini-2.5`)
7. Gemini 1.5 Flash (`gemini-1.5-flash`)

すべてのプロンプトは`user1`に割り当てられています。

## 次のステップ

マイグレーションが完了したら：

1. フロントエンドにアクセス: `http://localhost:8080`
2. 管理者アカウントでログイン: `admin` / `Admin#12345`
3. プロンプト管理画面でテストデータを確認

