# NexMAGI

**次世代AIオーケストレーションデスクトップアプリ** — マルチエージェントワークフローを3Dビジュアルパイプラインで実行・管理。

## 概要

NexMAGI は Tauri ベースのデスクトップアプリで、複数のAIエージェント（Researcher / Writer / Reviewer / Judge）を組み合わせたワークフローを実行します。実行は Rust の Worker Pool が並列に sidecar を起動して進め、その上に Coordinator 観測層がプラン・成果物・イベント・評価メトリクスを蓄積します。

- **3Dアクリルキューブ**による直感的なパイプライン表示
- **マルチモデル対応** — OpenAI GPT-5.x / Gemini 3.x / Claude 4.x
- **ローカル LLM 対応** — Ollama (OpenAI互換 HTTP) を preflight + ランタイムフォールバック付きで実行
- **External CLI runtime** — ローカル `claude` / `codex` をターミナル埋め込み (xterm.js / PTY) で直接実行
- **品質ゲート + リフレクション** — 自動検証・修正ループ
- **並列グループ + ジャッジ** — Mixture of Agents で結果を統合
- **Coordinator 観測層** — Plan / Workers / Artifacts / DAG / Eval メトリクス
- **WorkflowRunSession** — durable session layer (status / resume cursor / runtime bindings / event sequence)
- **Normalized events** — `workflow.session.*` / `step.*` / `runtime.*` / `workspace.*` / `approval.*` / `artifact.*` の統一イベント体系
- **ask_before_shell 承認フロー** — shell 実行前に pause/approve/reject する durable approval gate
- **アダプターレジストリ** — internal sidecar / local LLM (HTTP) / external CLI / remote API を統一管理 (risk / workspace / approval デフォルト付き)
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
       ├ WorkflowRunSession (durable session layer)
       ├ ApprovalRequests (ask_before_shell gate)
       ├ Follow-up tasks / Workspace isolation
       ├ DAG (depends_on → topological sort)
       └ Adapter Registry (risk/workspace/approval defaults) / Eval Harness
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

### ローカル LLM (Ollama)
- OpenAI互換 HTTP プロバイダ (`http://localhost:11434/v1`)
- **Preflight** — `/v1/models` で疎通 + モデル存在確認してから chat 呼び出し
- **ランタイムフォールバック** — `local_preferred` タスクで連絡不通 / `model_not_found` → `remote_api` へ自動リトライ
- 設定画面から health refresh + モデル一覧取得
- 既定モデル: `qwen2.5-coder:14b`

### External CLI runtime (Claude Code / Codex / Generic)
- ローカルの `claude` / `codex` CLI をそのまま実行バックエンドとして使用
- Claude Pro / Max や ChatGPT Plus / Pro の既存サブスクでログイン済みであれば API キー不要
- 共通 trait (`ExternalCliAdapter`) + capability matrix で runtime を抽象化
  - Claude Code: file read/write, shell exec, local auth, workspace, streaming, PTY
  - Codex: scaffold (`codex -p` 前提、flag layout は実機で検証予定)
  - Generic: 設定駆動 (`/bin/sh -c ...`)、テスト / 任意 CLI に利用
- **デュアルモード terminal** — `cli-terminal.html` ページに2種類のビューア
  - パイプモード: `tokio::process::Command` 経由のストリーミング (xterm.js 読み取り専用)
  - PTY モード: `portable-pty` による duplex (キー入力 → 子プロセス、ファイル編集確認等に応答可能)
- **Capability gate** — 必須 capability がアダプタに無ければ spawn 前に `CapabilityMismatch` で拒否
- **Artifact provenance** — 実行後 `runtime` / `cwd` / `exit_code` / `changed_files` / `capability_check_passed` など全て artifact metadata に永続化
- **Judge は強制 remote** — 個人サブスクを judge に使わないよう hard rule で保護

### Mixed runtime ワークフロー
既存の管理画面ワークフロー定義を、ステップ単位で実行ランタイムを切り替えて動かせます。`WorkflowSkill.config_json` の `execution_config` キーに以下のメタデータを持たせるだけで、DBマイグレーション無しで適用できます。

- `execution.execution_kind` — `auto` / `provider` / `external_cli`
- `execution.preferred_adapter` — `claude-code-local` / `codex-local` / `generic-cli` 等
- `execution.candidate_adapters` — フォールバック順
- `execution.required_capabilities` — `file_write` / `shell_exec` / `workspace_aware` 等
- `workspace.workspace_policy` — `none` / `temp_dir` / `shared`
- `workspace.share_with_steps` — 上流ステップのワークスペースを再利用
- `approval.policy` — `read_only` / `ask_before_shell` / `allow_shell` / `allow_write`

例えば以下のように1つのワークフロー内で:
- **search step** → Gemini (HTTP provider)
- **plan step** → Ollama `qwen2.5-coder:14b` (HTTP local)
- **code step** → Claude Code CLI (`workspace_policy=temp_dir`, `allow_write`)
- **verify step** → Codex CLI (`share_with_steps=[code_step]`, read-only)
- **judge step** → Anthropic / OpenAI (hard rule: 強制 remote)

ように混在させることが可能です。capability mismatch / cwd 不在 / 認証必要 のときは fail-fast で artifact metadata に `selection_reason` が記録されます。

レガシー (execution_config 未設定) のステップは従来動作のまま、何も変わりません。

### Coordinator 観測層
- ワークフロー開始時に **CoordinatorPlan** を生成（実行は既存の OrchestrationManager が担う）
- **Named Workers**: role × max_parallelism で論理ワーカーを生成し、task をラウンドロビン割当
- **Artifacts**: 各 execution の出力を notes / draft / review / score / final として構造化保存
- **DAG**: `depends_on` を解決した実行レイヤーを算出
- **Workspace Isolation**: `writes_files=true` なタスクの分離ワークスペースをメタデータ管理
- **Eval Harness**: completeness / revision_rate / judge_pass_rate / local_usage_rate などのメトリクスを履歴記録
- **Adapter Registry**: internal sidecar / local LLM / remote API を統一インターフェースで登録・検索 (risk / workspace / approval デフォルト付き)
- **Resume**: 中断した plan を再開し、未完了タスクのみ再実行可能

### WorkflowRunSession (セッション層)
ワークフロー実行ごとに durable session を作成し、以下を一元管理:
- **session_status** — `initializing` / `running` / `waiting_approval` / `paused` / `completed` / `failed` / `cancelled`
- **runtime_bindings** — ステップごとの selected / actual runtime、fallback 情報
- **workspace_bindings** — ステップごとの workspace id / mode / path / status
- **approval_summary** — pending / granted / rejected の承認リクエスト参照
- **resume_cursor** — 再開位置 (step_id + attempt_no + position)
- **Normalized events** — `workflow.session.*` / `step.*` / `runtime.*` / `workspace.*` / `approval.*` / `artifact.*` の30種のイベントを `event_seq` 付きで append-only 記録

### ask_before_shell 承認フロー
external_cli ステップで `approval.policy = ask_before_shell` が設定されている場合:
1. CLI プロセス spawn 前に Tauri が承認リクエストイベントを発行
2. フロントエンドが SweetAlert モーダルを表示（adapter / runtime / cwd / prompt preview）
3. ユーザーが許可 or 拒否 → `submit_workflow_approval_response` Tauri コマンドが:
   - ローカル oneshot を解決（即座に runner に反映）
   - バックエンドに `POST .../approvals/{id}/respond` で durable record を同期
4. 許可 → shell capability 付与して CLI 実行、拒否 → step 失敗
5. session_status が `waiting_approval` ↔ `running` を遷移、artifact metadata に承認証跡を記録

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
| デスクトップ | Tauri 2.x + Rust (tokio, reqwest, portable-pty) |
| フロントエンド | Vanilla JS + CSS (3D transforms), xterm.js 5.x |
| バックエンド | FastAPI + SQLAlchemy |
| データベース | MySQL 8.0 + Redis |
| AI 実行 (クラウド) | Python (OpenAI / Gemini / Anthropic SDK) |
| AI 実行 (ローカル HTTP) | Ollama (OpenAI互換 API, `qwen2.5-coder:14b` など) |
| AI 実行 (外部 CLI) | `claude` (Claude Code) / `codex` / generic CLI |
| 暗号化 | Fernet (cryptography) |

## DB テーブル概要

### 既存
- `accounts` / `api_configs` / `worker_api_keys`
- `workflows` / `workflow_groups` / `workflow_skills`
- `workflow_executions` / `executions`
- `skills` / `account_skills` / `daily_execution_counts`

### Coordinator 観測層 + Session 層 (新規)
- `coordinator_plans` — ワークフロー実行ごとの事前計画
- `coordinator_workers` — 名前付き論理ワーカー
- `coordinator_artifacts` — execution 出力を構造化保存
- `coordinator_events` — オーケストレーションイベントの時系列ログ (+session_id / step_id / event_seq / event_namespace)
- `coordinator_followup_tasks` — 派生タスク
- `coordinator_workspaces` — workspace 分離メタデータ
- `coordinator_adapters` — 実行バックエンドのレジストリ (+risk_level / requires_workspace / default_approval_policy)
- `coordinator_eval_runs` — 品質メトリクス履歴
- `approval_requests` — durable 承認リクエスト (ask_before_shell gate)
- `workflow_executions` に session 列追加 (session_id / session_status / runtime_bindings / workspace_bindings / approval_summary / artifact_refs / resume_cursor)

## ドキュメント

詳細は [`docs/`](./docs) を参照:
- [`docs/architecture.md`](./docs/architecture.md) — 全体アーキテクチャ
- [`docs/coordinator.md`](./docs/coordinator.md) — Coordinator 観測層 + Session + Approval の設計と API
- [`docs/api-keys.md`](./docs/api-keys.md) — ユーザー API キー設定の仕組み

## ライセンス

Proprietary
