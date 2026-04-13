# NexMAGI アーキテクチャ

## 全体構成

```
┌──────────────────────────────────────────────────────────┐
│  Tauri Desktop App                                       │
│  ├─ Frontend (Vanilla JS, 3D CSS, xterm.js)              │
│  ├─ Keychain Auth + SQLite Local History                 │
│  ├─ OrchestrationManager (Rust)                          │
│  │   └─ worker pool (max 4 sidecars)                     │
│  ├─ sidecar (Python) per worker                          │
│  │     ├─ OpenAI / Gemini / Anthropic SDK                │
│  │     └─ OpenAI互換 HTTP provider (Ollama)              │
│  └─ External CLI runtime (Rust, registry-driven)         │
│        ├─ ExternalCliAdapter trait + registry            │
│        ├─ Pipe mode (tokio::process::Command)            │
│        ├─ PTY mode (portable-pty, duplex)                │
│        └─ Adapters: Claude Code / Codex / Generic        │
└──────────────┬───────────────────────────────────────────┘
               │ HTTP                           │ HTTP
               ▼                                ▼
┌─────────────────────────────────┐   ┌──────────────────┐
│  Backend (Docker)               │   │  Ollama (local)  │
│  ├─ FastAPI                     │   │  /v1/models      │
│  ├─ MySQL 8.0 (永続化)          │   │  /v1/chat/…      │
│  ├─ Redis (SSE ストリーミング)  │   └──────────────────┘
│  └─ ワークフロー継続制御        │
│       ├─ 品質ゲート / Reflection│
│       ├─ ジャッジ / SV          │
│       ├─ 動的タスク分解         │
│       ├─ Coordinator 観測層     │
│       ├─ WorkflowRunSession     │
│       │   (durable session)     │
│       ├─ ApprovalRequests       │
│       │   (ask_before_shell)    │
│       ├─ resolve_execution_kind │
│       │   (http / external_cli) │
│       └─ Adapter Registry +     │
│         health / risk / defaults│
└─────────────────────────────────┘
```

## 実行フロー

1. ユーザーがフロントエンドからワークフロー実行ボタンを押下
2. `POST /api/execute/workflow` で `WorkflowExecution` と最初の `Execution` (status=`pending_local`) を生成
3. 同時に `CoordinatorPlan` を生成（観測スナップショット、実行は駆動しない）
4. Tauri 側 `OrchestrationManager` が `pending_local` をポーリングして取得
5. バックエンドが bundle を返すときに `resolve_execution_kind()` でルーティング決定
   - `http_provider` → 既存の provider payload (OpenAI / Gemini / Anthropic / Ollama) を乗せる
   - `external_cli` → `external_cli_payload` を乗せる (Claude Code / Codex / Generic)
   - judge タスクは hard rule で必ず `http_provider` (remote_only)
6a. **HTTP provider 経路**:
    - sidecar をサブプロセスとして起動し、LLM API を呼び出し
    - Ollama の場合は preflight (`/v1/models`) → chat → 失敗なら remote にフォールバック
6b. **External CLI 経路**:
    - sidecar は `delegated_to_external_cli_runtime` marker を返して bypass
    - desktop Rust の `consume_external_cli_bundle` が同じ execution を fetch
    - `ExternalCliRegistry` から adapter を lookup → capability check → spawn (pipe or PTY)
    - ターミナルは `cli-terminal.html` の xterm.js にストリーミング
7. 結果を `POST /api/worker/executions/{id}/complete` に送信
   - HTTP provider は `provider_meta` を、external CLI は `external_cli_meta` を含める
8. `finalize_execution` が `output_data` を保存し、`CoordinatorArtifact` を生成
   (runtime-specific provenance を `extra_metadata` に埋め込む)
   - 同時に session event (`step.completed` / `runtime.selected` / `artifact.created`) を emit
   - runtime_bindings / artifact_refs を session に bind
9. `continue_workflow_execution` が次ステップを起動（直列なら次のスキル、並列なら次のグループ）
   - session の current_step_id / resume_cursor を更新
   - `workflow.session.step_entered` / `step.started` event を emit
10. 全ステップ完了後、リーダースキルが結果を統合
    - session_status → `completed` / `failed`、`workflow.session.completed` event を emit

## レイヤーと責務

| レイヤー | 責務 |
|---------|------|
| Tauri Desktop | UI / 認証 / ワーカー pool / sidecar 起動 / External CLI runtime |
| sidecar | 単一 execution の LLM 実行 (クラウド API + Ollama HTTP)、external_cli bundle は bypass |
| External CLI runtime (Rust) | `claude` / `codex` / generic CLI の spawn + 結果 normalize |
| FastAPI | ワークフロー継続制御・状態管理・暗号化・adapter health |
| MySQL | 永続化 (workflow / execution / coordinator / adapter / artifact) |
| Redis | SSE ストリーミング |
| Coordinator 観測層 | 観測・メタデータ・評価メトリクス |
| Session 層 | durable session (status / bindings / events / resume) |
| Approval 層 | ask_before_shell の pause/approve/reject gate |

## 観測層 (Coordinator) の位置付け

Coordinator 層はワークフロー実行を**観測してメタデータを蓄積するだけ**で、実行を駆動しません。
既存の `WorkflowExecution / Execution + OrchestrationManager` が実行のソース・オブ・トゥルースです。
将来的に Coordinator 自身が adapter を呼び出す自律的オーケストレーションへ移行する余地を残しています。

詳細は [`coordinator.md`](./coordinator.md) を参照。

## ランタイム分類と選択ルール

バックエンド `coordinator_service.resolve_execution_kind()` が各タスクを以下の3カテゴリに分類し、bundle に対応する payload を載せます。

| execution_kind | payload | 実行場所 | 使用例 |
|---|---|---|---|
| `http_provider` | `provider_payload` | sidecar (Python) | OpenAI / Gemini / Anthropic / **Ollama (ローカル HTTP)** |
| `external_cli` | `external_cli_payload` | desktop Rust runtime | **Claude Code / Codex / Generic CLI** |
| `internal` | なし | sidecar 内蔵 CLI | legacy `local_worker.provider_adapter` |

### 選択ルール (opt-in)
1. `judge` ロールは **強制的に** `http_provider` (remote_only) — 個人サブスクを judge に使わない (hard rule)
2. ワークフロースキルの `config_json.execution_config.execution.execution_kind == "external_cli"` で、`preferred_adapter` / `candidate_adapters` / `cli_runtime_hint` のいずれかが解決可能で `cwd` が指定されている → `external_cli`
3. capability mismatch (step の `required_capabilities` が選ばれた adapter の declared capabilities を超える) → planner時点で `step_capability_mismatch:NAME:missing=...` を `selection_reason` に書き込み `http_provider` に fall back
4. レガシー (execution_config 未設定) のステップは既存 `resolve_execution_provider` にフォールスルー → `http_provider`

### Mixed runtime workflow execution

ステップ単位の実行ランタイム metadata は `WorkflowSkill.config_json` の `execution_config` キーに JSON として持ちます。DBマイグレーション無しで以下を宣言できます:

- `execution.execution_kind` (`auto` / `provider` / `external_cli`)
- `execution.preferred_adapter` / `execution.candidate_adapters` / `execution.required_capabilities`
- `workspace.workspace_policy` (`none` / `temp_dir` / `shared`) + `workspace.share_with_steps`
- `approval.policy` (`read_only` / `ask_before_shell` / `allow_shell` / `allow_write`)

これにより1つのワークフロー内で「search step → Gemini」「plan step → Ollama qwen2.5-coder」「code step → Claude Code (workspace temp_dir, allow_write)」「verify step → Codex (share_with_steps=[code_step], read_only)」「judge step → 強制 remote」のように混在実行ができます。詳細は [`coordinator.md`](./coordinator.md) の "Mixed runtime workflow execution" 節を参照。

### External CLI 実行所有権
Sidecar は `execution_kind=external_cli` の bundle を見たら `delegated_to_external_cli_runtime` marker を返して何もしません。desktop Rust の `consume_external_cli_bundle` Tauri command が同じ execution を fetch して registry 経由で実行し、completion を POST します。これにより Rust = runtime truth の原則を保ちつつ、外部 CLI 実行の所有権が明確に分離されます。

### External CLI capability gate
`ExternalCliAdapter` trait の `supports_capabilities()` が、タスクの `required_capabilities` と adapter の declared capabilities を比較します。mismatch のときは spawn 前に `CapabilityMismatch` ステータスで拒否し、`ExternalCliCapabilityChecked { passed: false, missing_capabilities }` イベントを emit します。これによりシェル実行不可の adapter に shell タスクが流れる、といった事故を型レベルで防ぎます。

## API キー管理

API キーはユーザーごとに暗号化保存されます。サーバー側 `.env` のフォールバックは廃止済み。

詳細は [`api-keys.md`](./api-keys.md) を参照。

## WorkflowRunSession (セッション層)

> 図: [`diagrams/session-state-machine.mmd`](./diagrams/session-state-machine.mmd) — session ステータス遷移  
> 図: [`diagrams/session-approval-flow.mmd`](./diagrams/session-approval-flow.mmd) — session + approval シーケンス図

ワークフロー実行ごとに durable な session record を `WorkflowExecution` 上に作成する。
`CoordinatorPlan` (観測スナップショット) と並行して、実行状態を正規化された形で保持する。

### 設計

- `WorkflowExecution` に session 列を追加 (新テーブルではなく 1:1 の列拡張)
- `CoordinatorEvent` に `session_id` / `step_id` / `event_seq` / `event_namespace` を追加
- `schema_version="2.0"` で新しい正規化イベントを区別

### Session ステータス遷移

```
initializing → running → completed
                  ↓          ↑
            waiting_approval → running (on approve)
                  ↓
               failed (on reject / timeout)
```

### 正規化イベント体系

| namespace | event types |
|-----------|------------|
| `workflow` | `session.started` / `session.step_entered` / `session.paused` / `session.resumed` / `session.waiting_approval` / `session.completed` / `session.failed` |
| `step` | `planned` / `started` / `completed` / `failed` / `retried` / `skipped` |
| `runtime` | `selected` / `fallback` / `capability_check` |
| `workspace` | `created` / `activated` / `promoted` / `cleaned` |
| `approval` | `requested` / `granted` / `rejected` / `timed_out` |
| `artifact` | `created` / `promoted` |

### API

| method | path | 内容 |
|--------|------|------|
| GET | `/api/user/workflow-executions/{id}/session` | session state (status / bindings / refs) |
| GET | `/api/user/workflow-executions/{id}/events?namespace=` | 正規化イベント一覧 |
| GET | `/api/user/workflow-executions/{id}/approvals` | 承認リクエスト一覧 |
| POST | `/api/user/workflow-executions/{id}/approvals/{approval_id}/respond` | 承認応答 (granted / rejected) |

### 関連ファイル

| ファイル | 役割 |
|---------|------|
| `backend/app/services/session_service.py` | session 作成・status 遷移・binding 操作 |
| `backend/app/services/session_events.py` | 正規化イベント定数 + emit_session_event |
| `backend/app/services/approval_service.py` | 承認リクエスト CRUD + idempotent resolve |

## ask_before_shell 承認フロー

### フロー

```
Runner (Rust)                Frontend (JS)              Backend (Python)
     │                            │                          │
     ├─ approval_requested ──────→│                          │
     │   (Tauri event)           │← SweetAlert modal        │
     │                           │                           │
     │                           │─ approve/reject ─────────→│
     │                           │  submit_workflow_         │
     │                           │  approval_response        │
     │←── oneshot resolved ──────│  (Tauri command)          │
     │                           │                    create_and_resolve()
     │                           │                    session events emit
     ▼                           │                           │
  spawn CLI (if approved)        │                           │
  or fail (if rejected)          │                           │
```

### Adapter hardening

`CoordinatorAdapter` に以下の列を追加:

| 列 | 型 | 説明 |
|---|---|---|
| `risk_level` | string | low / medium / high / critical |
| `requires_workspace` | bool | true の場合、workspace_policy=none を自動で temp_dir に昇格 |
| `default_approval_policy` | string | step に明示設定がないときのデフォルト |
| `auth_mechanism` | string | none / api_key / oauth / local_session |
| `supported_capabilities` | JSON | capability 配列 |

Rust 側 `ExternalCliAdapterConfig` にも `risk_level` / `requires_workspace` / `default_approval_policy` を追加。
Claude Code = medium risk / workspace required / ask_before_shell、Codex = medium / workspace / allow_write、Generic = high / no workspace / ask_before_shell。
