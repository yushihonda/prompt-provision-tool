# Prompt Provision Tool

スキルを秘匿したまま、AI 実行機能を提供する **次世代AIオーケストレーションフレームワーク**。

## 構成

```
サーバー (Docker)                    ローカル (ターミナル)
  スキル暗号化保存                     全ての AI 実行
  バンドル配信 (復号+署名)             リトライ・ストリーミング
  結果保存・課金・SSE                  並列実行制御 (最大8並列)
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
| `ANTHROPIC_API_KEY` | ※2 | Anthropic APIキー |
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
python -m local_worker skill 260 --input '{"topic":"AI"}' --model gpt-5.4

# 常駐デーモン (UI から自動実行)
python -m local_worker daemon
```

## 対応モデル

| OpenAI | Google Gemini | Anthropic Claude |
|--------|---------------|------------------|
| gpt-5.4, gpt-5.4-pro | gemini-3.1-pro-preview | claude-sonnet-4-6 |
| gpt-5.4-mini, gpt-5.4-thinking | gemini-3.1-pro-preview-deep-think | claude-sonnet-4-6-thinking |
| gpt-5.2, gpt-5.2-pro | gemini-3-pro-preview | claude-opus-4-6 |
| gpt-5.2-thinking | gemini-2.5-pro, gemini-2.5-flash | claude-opus-4-6-thinking |
| o4-mini | + deep-think variants | claude-haiku-4-5 |

## ワークフロー オーケストレーション

管理画面でスキルとワークフローを作成。2026年最新のAIオーケストレーションパターンに対応:

```
[Group 1: 並列]                   [Group 2: 直列]           [親スキル]
  リサーチA ──→ 品質ゲート           記事生成 ──→ 品質ゲート     最終統合
  リサーチB ──→ 品質ゲート           (BBから調査結果読取)
  市場分析  ──→ 品質ゲート
       ↓
  ジャッジ (3結果を比較・統合)
       ↓
  スーパーバイザー (十分か判断)
```

### 基本機能

- **グループ内並列**: 同じグループのスキルを同時実行（最大8並列）
- **グループ間直列**: グループ順に実行、前グループの出力を次に渡す
- **親スキル**: 全結果を統合する親スキル（必須/任意/無効を選択可能）
- **条件分岐**: グループに条件式を設定、結果に応じてスキップ可能
- **エラーリカバリ**: スキルごとに stop / skip / retry ポリシーを設定
- **明示的データマッピング**: input_mapping / output_key でステップ間データ参照を明示的に指定

### 次世代オーケストレーション機能

| 機能 | 概要 |
|------|------|
| **Reflection (自己修正)** | スキル完了後に品質ゲート（正規表現/JSON検証/LLM判定）で検証。不合格なら critique 付きで自動再実行 |
| **Blackboard (共有メモリ)** | 全スキルが読み書きできるKey-Valueストア。output_key を持つスキルの出力を自動保存 |
| **Supervisor (中間監視)** | グループ完了後にLLMが進捗を評価。continue / repeat / stop でルーティング判断 |
| **Dynamic Decomposition (動的分解)** | プランナースキルが実行時にタスクを動的生成。直列/並列を計画に応じて自動制御 |
| **Debate/Judge (議論・合議)** | 並列グループ完了後にジャッジが全結果を比較・統合。最良の回答を選択 |

### ワークフロー実行フロー

```
ユーザー入力
  ↓
Group 1 (parallel)
  ├── Skill A → 品質ゲート → (不合格なら critique 付き再実行)
  ├── Skill B → 品質ゲート → OK → Blackboard に自動保存
  └── Skill C → OK
  ↓ 全完了
  Judge: 3結果を比較して最良を選択 → Blackboard に保存
  ↓
  Supervisor: "調査は十分か?" → continue / repeat / stop
  ↓
Group 2 (dynamic)
  └── Planner Skill → {"steps": [...]} → スキルを動的起動
  ↓
Group 3 (serial)
  └── 執筆Skill → Blackboard から調査結果を読む → 品質ゲート
  ↓
親スキル: 全結果統合 → 最終出力
```

## ディレクトリ構成

```
backend/                  FastAPI サーバー
  app/api/                API エンドポイント (auth, admin, user, execute, worker)
  app/models.py           DB モデル (Workflow, WorkflowGroup, WorkflowSkill, Execution)
  app/services/           Redis, 暗号化, 完了処理, ワーカー認証
  app/tasks/              ワークフロー継続ロジック (オーケストレーション)
  alembic/                マイグレーション (001-003)
frontend/                 Web UI
  admin/                  管理画面 (ワークフロー/スキル管理)
  user/                   ユーザー画面 (実行, 履歴, ダウンロード)
local_worker/             ローカル実行 CLI
  cli.py                  コマンド定義 (list, skill, workflow, daemon)
  executor.py             LLM 呼び出し (OpenAI/Gemini/Claude, リトライ, tiktoken)
  daemon.py               常駐ワーカー (asyncio, Semaphore並列制御)
deployment/               Docker, Nginx, systemd
docs/                     詳細資料 (要件定義, デプロイ手順, etc.)
```

## セキュリティ

- スキル: Fernet 暗号化保存、復号はサーバーのみ
- バンドル: HMAC-SHA256 署名付き、1 回限り配信
- 認証: JWT (ユーザー) + job_token (ワーカー) + Worker API Key
- 出力: サニタイズ (テンプレート漏洩防止)
- ガードレール: スキル先頭に安全ポリシー注入
- 楽観ロック: 並列完了時の二重起動防止

## 詳細資料

- [docs/README_FULL.md](docs/README_FULL.md) - 全仕様 (API, DB, 運用手順)
- [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) - 要件定義
- [docs/DEPLOYMENT_CHECKLIST.md](docs/DEPLOYMENT_CHECKLIST.md) - デプロイチェックリスト
