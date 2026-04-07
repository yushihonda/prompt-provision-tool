# NexMAGI

**次世代AIオーケストレーションデスクトップアプリ** — マルチエージェントワークフローを3Dビジュアルパイプラインで実行・管理。

## 概要

NexMAGI は Tauri ベースのデスクトップアプリで、複数のAIエージェント（Researcher / Writer / Reviewer / Judge）を組み合わせたワークフローを実行します。実行は Rust の Worker Pool が並列に sidecar を起動して進め、その上に Coordinator 観測層がプラン・成果物・イベント・評価メトリクスを蓄積します。

- **3Dアクリルキューブ**による直感的なパイプライン表示
- **マルチモデル対応** — OpenAI GPT-5.x / Gemini 3.x / Claude 4.x
- **品質ゲート + リフレクション** — 自動検証・修正ループ
- **並列グループ + ジャッジ** — Mixture of Agents で結果を統合
- **Coordinator 観測層** — Plan / Workers / Artifacts / DAG / Eval メトリクス
- **アダプターレジストリ** — internal sidecar / local LLM / remote API を統一管理
- **ユーザー自身のAPIキー管理** — 設定ページから登録、サーバー側 .env フォールバックなし

## アーキテクチャ

```
[ Tauri Desktop ]
  ├ フロントエンド (Vanilla JS + 3D CSS)
  ├ Keychain 認証 / SQLite ローカル履歴
  └ OrchestrationManager (Rust) ─┐
                                 │ pending_local 取得
                                 ▼
                            [ sidecar ] (Python, ローカル AI 実行)
                                 │ 結果送信
                                 ▼
[ バックエンド (Docker) ]
  ├ FastAPI + MySQL + Redis
  ├ ワークフロー継続制御 / 品質ゲート / ジャッジ / スーパーバイザー
  ├ ユーザー APIキー暗号化保存 (Fernet)
  └ Coordinator 観測層
       ├ CoordinatorPlan / Worker / Artifact / Event
       ├ Follow-up tasks / Workspace isolation
       ├ DAG (depends_on → topological sort)
       └ Adapter Registry / Eval Harness / Resume
```

## クイックスタート (開発環境)

```bash
# 1. バックエンド起動 (Docker)
cd deployment
docker compose -f docker-compose.local.yml up -d

# 2. 既定アダプター seed と DB マイグレーションは起動時に自動実行
#    (coordinator_* テーブルも create_all で生成される)

# 3. デスクトップアプリ起動
cd desktop
npm install
npm run tauri:dev
```

## 主な機能

### ワークフロー実行
- マルチステップ AI ワークフロー（直列 / 並列グループ）
- 3D アクリルキューブのリアルタイム可視化
- 品質ゲート (regex / json_schema / LLM) と自動リフレクション
- 並列グループの結果を統合する Judge / Supervisor
- ハンドオフコンテキストの自動伝播
- 動的タスク分解 (planner → 動的ステップ生成)

### Coordinator 観測層
- ワークフロー開始時に **CoordinatorPlan** を生成（実行は既存の OrchestrationManager が担う）
- **Named Workers**: role × max_parallelism で論理ワーカーを生成し、task をラウンドロビン割当
- **Artifacts**: 各 execution の出力を notes / draft / review / score / final として構造化保存
- **DAG**: `depends_on` を解決した実行レイヤーを算出
- **Workspace Isolation**: `writes_files=true` なタスクの分離ワークスペースをメタデータ管理
- **Eval Harness**: completeness / revision_rate / judge_pass_rate / local_usage_rate などのメトリクスを履歴記録
- **Adapter Registry**: internal sidecar / local LLM / remote API を統一インターフェースで登録・検索
- **Resume**: 中断した plan を再開し、未完了タスクのみ再実行可能

### ユーザー設定 (API設定ページ)
- OpenAI / Gemini / Anthropic の API キーを各ユーザーが自分で登録 (Fernet 暗号化保存)
- 管理者は閲覧・上書き可能だが、フォールバック .env キーは廃止
- レート制限 (時間 / 日) は管理者が設定、ユーザーは閲覧のみ

### 管理画面
- スキル作成・編集 (プロンプトテンプレートの暗号化管理)
- ワークフロー作成・編集 (グループ構造・並列実行・depends_on)
- アカウント管理
- 実行ログ (ミニ 3D キューブで可視化、並列グループは縦並べ表示)

### デスクトップ機能
- Tauri 2.x + Rust
- macOS Keychain による安全な認証保存
- Python sidecar によるローカル AI 実行
- 最大 4 ワーカーの並列オーケストレーション

## 技術スタック

| レイヤー | 技術 |
|---------|------|
| デスクトップ | Tauri 2.x + Rust |
| フロントエンド | Vanilla JS + CSS (3D transforms) |
| バックエンド | FastAPI + SQLAlchemy |
| データベース | MySQL 8.0 + Redis |
| AI 実行 | Python (OpenAI / Gemini / Anthropic SDK) |
| 暗号化 | Fernet (cryptography) |

## DB テーブル概要

### 既存
- `accounts` / `api_configs` / `worker_api_keys`
- `workflows` / `workflow_groups` / `workflow_skills`
- `workflow_executions` / `executions`
- `skills` / `account_skills` / `daily_execution_counts`

### Coordinator 観測層 (新規)
- `coordinator_plans` — ワークフロー実行ごとの事前計画
- `coordinator_workers` — 名前付き論理ワーカー
- `coordinator_artifacts` — execution 出力を構造化保存
- `coordinator_events` — オーケストレーションイベントの時系列ログ
- `coordinator_followup_tasks` — 派生タスク
- `coordinator_workspaces` — workspace 分離メタデータ
- `coordinator_adapters` — 実行バックエンドのレジストリ
- `coordinator_eval_runs` — 品質メトリクス履歴

## ドキュメント

詳細は [`docs/`](./docs) を参照:
- [`docs/architecture.md`](./docs/architecture.md) — 全体アーキテクチャ
- [`docs/coordinator.md`](./docs/coordinator.md) — Coordinator 観測層の設計と API
- [`docs/api-keys.md`](./docs/api-keys.md) — ユーザー API キー設定の仕組み

## ライセンス

Proprietary
