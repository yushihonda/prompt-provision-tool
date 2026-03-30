# Prompt Provision Tool

スキルを秘匿したまま、AI 実行機能を提供する汎用ワークフロー実行フレームワーク。

## 構成

```
サーバー (Docker)                    ローカル (ターミナル)
  スキル暗号化保存                     全ての AI 実行
  バンドル配信 (復号+署名)             リトライ・ストリーミング
  結果保存・課金・SSE                  並列実行制御
  AI 処理なし                          ユーザーの API キーで実行
```

## クイックスタート

```bash
# 1. Docker 起動 (サーバー)
cd deployment
docker compose -f docker-compose.local.yml up -d

# 2. マイグレーション
docker exec ppt-backend alembic upgrade head

# 3. ローカルワーカー起動 (ターミナル)
pip install -r local_worker/requirements.txt
python -m local_worker daemon
```

## ローカルワーカー設定

`.env.worker.sample` を `.env.worker` にコピーして編集:

```bash
cp .env.worker.sample .env.worker
```

| 変数 | 必須 | 説明 |
|------|------|------|
| `WORKER_SERVER_URL` | - | サーバーURL（デフォルト: `http://localhost:8000`） |
| `WORKER_API_KEY` | ※1 | Worker API Key（`wpk_...`形式、管理画面で発行） |
| `OPENAI_API_KEY` | ※2 | OpenAI APIキー |
| `GEMINI_API_KEY` | ※2 | Gemini APIキー |
| `WORKER_MAX_CONCURRENT` | - | 最大同時実行数（デフォルト: 8） |
| `WORKER_POLL_INTERVAL` | - | ポーリング間隔 秒（デフォルト: 2.0） |
| `WORKER_REQUEST_TIMEOUT` | - | リクエストタイムアウト 秒（デフォルト: 3600） |

- ※1 デーモンモードで使用。dev-login を使う場合は不要
- ※2 サーバー側のアカウントにAPIキーが設定されていれば不要（バンドルに含まれる）

## CLI コマンド

```bash
# スキル一覧
python -m local_worker list skills

# ワークフロー一覧
python -m local_worker list workflows

# スキル単体実行
python -m local_worker skill 260 --input '{"topic":"AI最新動向"}'

# ワークフロー実行 (グループベース: 並列+直列の組み合わせ)
python -m local_worker workflow 3 --input '{"topic":"AI記事"}'

# モデル切り替え
python -m local_worker skill 260 --input '{"topic":"AI"}' --model gpt-4o

# 常駐デーモン (UI から自動実行)
python -m local_worker daemon
```

## 対応モデル

| OpenAI | Google Gemini |
|--------|---------------|
| gpt-5.2, gpt-5.2-pro | gemini-3-pro-preview |
| gpt-5.1, gpt-5.1-thinking | gemini-2.5-pro, gemini-2.5-flash |
| gpt-5, gpt-5-pro | gemini-2.0-flash |
| gpt-4o, gpt-4o-mini | + deep-think variants |

## ワークフロー

管理画面でスキルとワークフローを作成。グループ単位で直列/並列を設定:

```
[Group 1: 並列] ──→ [Group 2: 直列] ──→ [親スキル]
  リサーチ             記事生成              最終統合
  市場分析
```

- **グループ内並列**: 同じグループのスキルを同時実行
- **グループ間直列**: グループ順に実行、前グループの出力を次に渡す
- **親スキル**: 全結果を統合する親スキル。ワークフローに埋め込み
- **ドラッグ&ドロップ**: 管理画面でグループ・スキルを視覚的に配置

## ディレクトリ構成

```
backend/                  FastAPI サーバー
  app/api/                API エンドポイント (auth, admin, user, execute, worker)
  app/models.py           DB モデル (Workflow, WorkflowGroup, WorkflowSkill, Execution)
  app/services/           Redis, 暗号化, 完了処理, ワーカー認証
  app/tasks/              ワークフロー継続ロジック
  alembic/                マイグレーション
frontend/                 Web UI
  admin/                  管理画面 (スキル管理, ワークフロービルダー)
  user/                   ユーザー画面 (実行, 履歴, ダウンロード)
local_worker/             ローカル実行 CLI
  cli.py                  コマンド定義 (list, skill, workflow, daemon)
  engine.py               実行エンジン (グループベース直列/並列)
  executor.py             LLM 呼び出し (OpenAI/Gemini, リトライ, tiktoken)
  daemon.py               常駐ワーカー (ポーリング→自動実行→SSE)
deployment/               Docker, Nginx, systemd
docs/                     詳細資料 (要件定義, デプロイ手順, etc.)
```

## セキュリティ

- スキル: Fernet 暗号化保存、復号はサーバーのみ
- バンドル: HMAC-SHA256 署名付き、1 回限り配信
- 認証: JWT (ユーザー) + job_token (ワーカー) + Worker API Key
- 出力: サニタイズ (テンプレート漏洩防止)
- ガードレール: スキル先頭に安全ポリシー注入

## 詳細資料

- [docs/README_FULL.md](docs/README_FULL.md) - 全仕様 (API, DB, 運用手順)
- [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) - 要件定義
- [docs/DEPLOYMENT_CHECKLIST.md](docs/DEPLOYMENT_CHECKLIST.md) - デプロイチェックリスト

次の変更箇所
並列処理などで同じスキルだと同じ検索してて意味ない　入力データが同じなので
サブスクでも実行可能にしたい
コード生成も可能にプレビューもあったがいいかもWP環境にも対応したい
