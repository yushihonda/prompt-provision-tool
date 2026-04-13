# Coordinator 観測層

## 設計目的

既存の Tauri OrchestrationManager (worker pool) を **置き換えず**、その上に
`plan → role → artifact → review/judge → final synthesis` のセマンティクスを
観測・メタデータレイヤーとして積層する。

- 実行を駆動しない (best-effort 観測層)
- ワークフロー実行が失敗してもメタデータが残る
- 将来的に自律的オーケストレーションに昇格できる構造を保つ

## モジュール構成

| ファイル | 役割 |
|---------|------|
| `backend/app/services/coordinator_service.py` | Plan / Worker / Artifact / Event / Workspace / DAG / Provider Router / `resolve_execution_kind` / step workspace allocation |
| `backend/app/services/coordinator_extensions.py` | Adapter Registry / Task Envelope / Eval Harness / Resume / local adapter health refresh |
| `backend/app/services/workflow_step_schema.py` | `StepExecutionConfig` + `parse_execution_config` (workflow step に execution / workspace / approval を持たせる) |
| `backend/app/services/session_service.py` | WorkflowRunSession 管理 (session 作成 / status 遷移 / binding 操作) |
| `backend/app/services/session_events.py` | 正規化イベント taxonomy (30種) + `emit_session_event` |
| `backend/app/services/approval_service.py` | 承認リクエスト CRUD + idempotent resolve + session 連携 |
| `backend/app/services/external_cli_adapters.py` | external_cli bundle payload 構築 (`build_external_cli_payload`) |
| `backend/app/services/external_cli_capabilities.py` | capability 定数 + `required_capabilities_for_task` |
| `backend/app/services/completion_service.py` | `build_external_cli_provenance` / `build_http_provider_provenance` + artifact metadata 永続化 + session event emit |
| `backend/app/api/adapters.py` | `/api/adapters/*` (health refresh / models) |
| `backend/app/api/user.py` | `/api/user/coordinator/*` エンドポイント |
| `sidecar/app/providers/http_provider.py` | OpenAI互換 HTTP provider (Ollama) + preflight |
| `sidecar/app/providers/discovery.py` | `ping` / `list_models` helpers |
| `sidecar/app/real_execution.py` | runtime fallback + `execution_kind=external_cli` bypass |
| `desktop/src-tauri/src/external_cli_traits.rs` | `ExternalCliAdapter` trait + shared enums/types |
| `desktop/src-tauri/src/external_cli_registry.rs` | `ExternalCliRegistry` |
| `desktop/src-tauri/src/external_cli_runner.rs` | 汎用 runner (pipe モード, capability gate, changed_files) |
| `desktop/src-tauri/src/external_cli_pty.rs` | PTY duplex モード (`portable-pty`) |
| `desktop/src-tauri/src/external_cli_runtime.rs` | `consume_external_cli_bundle` Tauri command |
| `desktop/src-tauri/src/external_cli_approval.rs` | 承認ゲート (oneshot + `submit_workflow_approval_response` Tauri command) |
| `desktop/src-tauri/src/external_cli_adapters/{claude_code,codex,generic}.rs` | concrete adapters (risk/workspace/approval defaults 付き) |
| `desktop/src-tauri/src/local_llm.rs` | `local_llm_ping` / `local_llm_list_models` Tauri commands |
| `frontend/user/js/workflow-execute.js` | `loadCoordinatorPlan` / `renderCoordinatorPlan` |
| `frontend/user/cli-terminal.html` | External CLI ターミナルページ (xterm.js + PTY) |
| `frontend/user/js/cli-terminal-view.js` | パイプモード ストリーミングビューア |
| `frontend/user/js/cli-terminal-pty.js` | PTY duplex ターミナル |
| `frontend/js/runtime-badge.js` | artifact metadata から runtime チップを描画 |
| `frontend/admin/js/execution-config-form.js` | workflow skill 編集の `execution_config` フォーム helper |

## DB テーブル

| テーブル | 主キー | 内容 |
|---------|-------|------|
| `coordinator_plans` | `plan_id` (UUID) | ワークフロー実行ごとの事前計画 |
| `coordinator_workers` | `worker_id` (UUID) | 名前付き論理ワーカー (researcher-1, writer-2 等) |
| `coordinator_artifacts` | `artifact_id` (UUID) | execution 出力を notes / draft / review / score / final として保存 |
| `coordinator_events` | `id` | オーケストレーションイベントの時系列ログ (+session_id / step_id / event_seq / event_namespace) |
| `coordinator_followup_tasks` | `task_id` (UUID) | 既存タスクから派生する追加タスク |
| `coordinator_workspaces` | `workspace_id` (UUID) | writes_files=true なタスクの分離ワークスペース |
| `coordinator_adapters` | `adapter_id` (UUID) | 実行バックエンドのレジストリ (+risk_level / requires_workspace / default_approval_policy / auth_mechanism / supported_capabilities) |
| `coordinator_eval_runs` | `eval_id` (UUID) | 品質メトリクス履歴 |
| `approval_requests` | `approval_id` (UUID) | ask_before_shell の durable 承認リクエスト |

`workflow_executions.coordinator_plan_id` で `CoordinatorPlan` と紐付ける。
`workflow_executions` に session 列 (session_id / session_status / current_step_id / resume_cursor / runtime_bindings / workspace_bindings / approval_summary / artifact_refs) を追加。

## 主要概念

### CoordinatorPlan
ワークフロー実行開始時に `build_coordinator_plan` で生成されるスナップショット。

```python
{
  "plan_id": "uuid",
  "workflow_execution_id": 123,
  "goal": "ワークフローの説明",
  "complexity_level": "low | medium | high",
  "max_parallelism": 4,
  "roles": [{"role": "researcher", "label": "explore", ...}],
  "tasks": [
    {
      "task_id": "task_5",
      "role": "writer",
      "objective": "実装案A: 技術アプローチ",
      "expected_artifact_type": "draft",
      "impact_level": "medium",
      "depends_on": [],
      "workflow_skill_id": 5
    }
  ],
  "provider_policy": {
    "default_mode": "remote_only",
    "escalation_rules": [
      {"when": {"role": "researcher"}, "switch_to": "local_preferred"},
      {"when": {"role": "judge"}, "switch_to": "remote_only"}
    ]
  }
}
```

### Worker Roles

既存の `agent_profile` を Coordinator role にマップする。

| agent_profile | role |
|--------------|------|
| explore | researcher |
| plan | writer |
| implement | writer |
| verification | reviewer |
| (並列グループあり) | judge (自動付与) |
| default | writer |

### Artifact Types

| type | 用途 |
|------|------|
| notes | researcher の調査メモ |
| evidence | 引用・参考データ |
| draft | writer の初稿 |
| review | reviewer の指摘 |
| score | judge のスコア / 判定 |
| final | リーダーが統合した最終出力 |

### Provider Modes

| mode | 説明 |
|------|------|
| `remote_only` | 必ずリモート API を使う |
| `local_only` | 必ずローカル LLM を使う |
| `local_preferred` | ローカルを優先、失敗時にリモートへフォールバック |
| `hybrid_auto` | 状況に応じて自動切替 |

`route_provider_mode(plan, role, ...)` がルールに従って `provider_mode` を決定する。

### Events (Legacy — schema_version="1.0")

| event_type | 発火タイミング |
|-----------|--------------|
| `plan_created` | プラン生成完了 |
| `task_enqueued` | プラン内のタスクキュー化 |
| `task_started` / `task_finished` | task の開始 / 完了 |
| `artifact_created` | アーティファクト記録 |
| `review_requested` | 品質ゲート判定開始 |
| `judge_decision_made` | judge / supervisor が判定 |
| `run_completed` | リーダー (final) 完了 |
| `worker_registered` / `worker_status_changed` | worker のライフサイクル |
| `followup_enqueued` / `followup_resolved` | 派生タスクの発行 / 解決 |
| `workspace_reserved` / `workspace_promoted` / `workspace_cleaned` | workspace 状態遷移 |
| `adapter_registered` / `adapter_health_changed` | adapter のライフサイクル |
| `task_envelope_created` | ポータブルタスク envelope の生成 |
| `eval_recorded` | 品質メトリクスの履歴記録 |
| `plan_resumed` / `plan_replayed` | 中断 plan の再開 |

### Normalized Events (schema_version="2.0")

`session_id` / `step_id` / `event_seq` / `event_namespace` 付きで emit される正規化イベント。
Legacy events と共存し、同じ `coordinator_events` テーブルに格納される。

| namespace | event_type | 発火タイミング |
|-----------|-----------|--------------|
| `workflow` | `workflow.session.started` | session 作成 (plan 生成直後) |
| `workflow` | `workflow.session.step_entered` | current_step_id 更新 |
| `workflow` | `workflow.session.waiting_approval` | 承認待ちに遷移 |
| `workflow` | `workflow.session.resumed` | 承認後に再開 |
| `workflow` | `workflow.session.completed` | ワークフロー正常完了 |
| `workflow` | `workflow.session.failed` | ワークフロー失敗 |
| `step` | `step.planned` | タスク計画時 |
| `step` | `step.started` | Execution 行生成時 |
| `step` | `step.completed` / `step.failed` | finalize_execution 時 |
| `step` | `step.retried` | リトライ発生時 |
| `runtime` | `runtime.selected` | adapter / provider_mode 確定時 |
| `workspace` | `workspace.created` / `workspace.promoted` / `workspace.cleaned` | workspace 状態遷移時 |
| `approval` | `approval.requested` / `approval.granted` / `approval.rejected` / `approval.timed_out` | 承認ライフサイクル |
| `artifact` | `artifact.created` | CoordinatorArtifact 生成時 |

### WorkflowRunSession

> 図: [`diagrams/session-state-machine.mmd`](./diagrams/session-state-machine.mmd)  
> 図: [`diagrams/session-approval-flow.mmd`](./diagrams/session-approval-flow.mmd)

ワークフロー実行ごとの durable session。`WorkflowExecution` 上の列として実装。

```
session_id         — "sess_<hex16>"
session_status     — initializing | running | waiting_approval | paused | completed | failed | cancelled
current_step_id    — 現在処理中の task_id
resume_cursor      — JSON {step_id, attempt_no, position}
runtime_bindings   — JSON {step_id: {adapter_id, runtime, execution_kind, ...}}
workspace_bindings — JSON {step_id: {workspace_id, mode, path, status}}
approval_summary   — JSON {pending: [id], granted: [id], rejected: [id]}
artifact_refs      — JSON {step_id: [artifact_id]}
```

`session_service.py` が操作を提供:
- `create_session` / `update_session_status` / `bind_runtime` / `bind_workspace`
- `update_resume_cursor` / `add_artifact_ref` / `add_approval_ref` / `move_approval_ref`
- `get_session_state` (API レスポンス用)

### ApprovalRequests (ask_before_shell)

`approval_requests` テーブルで durable に管理。

```
approval_id       — "apr_<hex16>"
session_id        — 紐付く session
step_id           — 対象ステップ
status            — pending | granted | rejected | timed_out
approval_policy   — ask_before_shell
decided_by        — user / system_timeout
decided_at        — 応答日時
attempt_no        — 同一 step の何回目の試行か (冪等キー)
```

`approval_service.py` が操作を提供:
- `create_approval_request` — pending 作成 + session を waiting_approval に遷移
- `resolve_approval` — 冪等な応答 (既に resolved なら現状を返す)
- `create_and_resolve_approval` — Tauri flow 用の atomic 作成+解決
- `get_pending_approvals` / `get_approvals_for_execution`

### DAG

`task.depends_on` を解決して `build_task_dag` で `{nodes, edges}` を返し、
`topological_sort_tasks` で並列実行可能なレイヤーに分解する。
クロスグループ依存・並列最適化に使う。

### Workspace Isolation

`writes_files=true` なタスクには `auto_reserve_workspaces_for_plan` が
`temp_dir` モードのワークスペースを自動予約する。実体ディレクトリは
クライアント側 (Tauri) が管理し、バックエンドは状態とパスのみ保持する。

ステータス遷移: `reserved → active → promoted (or cleaned)`

### Mixed runtime workflow execution

既存の管理画面ワークフロー定義に、**ステップ単位の実行ランタイム metadata** を持たせて mixed runtime 実行を可能にする層。`WorkflowSkill.config_json` の `execution_config` キーに JSON で持たせるだけで、DBマイグレーション無しで利用できる。

```json
{
  "execution_config": {
    "schema_version": "1.0",
    "execution": {
      "execution_kind": "external_cli",
      "preferred_adapter": "claude-code-local",
      "candidate_adapters": ["codex-local"],
      "required_capabilities": ["file_read", "file_write", "shell_exec"],
      "cli_runtime_hint": "claude_code",
      "cwd_hint": "/Users/me/project"
    },
    "workspace": {
      "workspace_policy": "temp_dir",
      "share_with_steps": ["code_step"],
      "promote_on": "accepted",
      "cleanup_on": "failed"
    },
    "approval": {
      "policy": "allow_write",
      "allow_writes": true,
      "allow_shell": false
    },
    "artifact_contract": {
      "expected_type": "patch"
    }
  }
}
```

#### 実行フロー

1. `worker.py` が `WorkflowSkill` 行を読み、`parse_execution_config(config_json)` で `StepExecutionConfig` に正規化
2. parsed config を matched task の `_step_execution_config` にアタッチして `resolve_execution_kind` を呼ぶ
3. `resolve_execution_kind` が step config の `execution.execution_kind` を見て分岐:
   - `external_cli` + 解決可能な adapter + `cwd` あり → `external_cli_payload` を返す
   - `provider` または `auto` → 既存の HTTP / internal ルーティングへ
4. `_maybe_allocate_step_workspace` が `workspace_policy != "none"` のとき `CoordinatorWorkspace` を予約。`share_with_steps` に上流 task_id があれば既存の workspace を再利用 (cleaned 行はスキップ)
5. capability mismatch (step の `required_capabilities` が adapter の declared capabilities を超えるとき) は **planner時点で fail-fast** し、`selection_reason=step_capability_mismatch:NAME:missing=...` で http_provider に fall back
6. judge ロールは `execution_kind=external_cli` でも **強制的に remote http_provider** (hard rule)

#### selection_reason 語彙 (artifact 監査用)

- `judge_forced_remote` — judge ハードルール
- `step_pref:external_cli:NAME` — `preferred_adapter` ヒット
- `step_candidate:external_cli:NAME` — `candidate_adapters` 内の最初のヒット
- `prefer_external_cli:RUNTIME` — `cli_runtime_hint` のみで解決
- `step_capability_mismatch:NAME:missing=cap1,cap2` — capability 不足で fall back
- `low_impact_local` / `cheap_local` 等 — 既存 HTTP provider ルーティングの reason

#### 後方互換

`execution_config` キーが無い `WorkflowSkill` 行は `default_step_execution_config()` を返し、`execution_kind=auto` / `workspace_policy=none` / `approval=read_only` となる。これは既存ルーティングと完全に同じ動作で、何も書き換えなくても旧ワークフローが壊れない。

### Adapter Registry

起動時に既定アダプターが seed される:

| name | type | transport | provider_mode | impl |
|------|------|-----------|---------------|------|
| internal-sidecar | internal | process_stdio | remote_only | sidecar.main |
| local-llm-ollama | local_llm | http | local_preferred | http://localhost:11434/v1 |
| remote-api-openai-compat | remote_api | http | remote_only | user_api_keys |
| claude-code-local | external_cli | external_cli | remote_only | claude |
| codex-local | external_cli | external_cli | remote_only | codex |

`find_adapter_for_task(role, provider_mode)` で HTTP provider 系の lookup をする。external_cli は `resolve_execution_kind()` で `cli_runtime_hint` を見て選択される (別経路)。

`update_adapter_health()` + `refresh_local_adapter_health()` で Ollama 系 adapter の health を probe し、adapter row の `config.last_health_detail` に models 一覧 / latency / 最終 error を書き込む。

#### Adapter hardening (PR C)

`coordinator_adapters` に以下の列を追加:

| 列 | 型 | 説明 | 例 |
|---|---|---|---|
| `risk_level` | string(20) | adapter のリスクレベル | low / medium / high / critical |
| `requires_workspace` | bool | workspace 必須フラグ | true → workspace_policy=none を自動で temp_dir に昇格 |
| `default_approval_policy` | string(30) | step 未設定時のデフォルト | ask_before_shell / allow_shell |
| `auth_mechanism` | string(30) | 認証方式 | none / api_key / local_session |
| `supported_capabilities` | JSON | capability 配列 | ["file_read", "shell_exec", ...] |

`resolve_execution_provider()` が adapter を選択した後、`_get_adapter_defaults(adapter)` で上記を取得し:
- `requires_workspace=true` かつ step に workspace_policy 未設定 → `temp_dir` に自動昇格
- `default_approval_policy` が設定されていて step に approval 未設定 → adapter のデフォルトを適用

Rust 側 `ExternalCliAdapterConfig` にも `risk_level` / `requires_workspace` / `default_approval_policy` を追加。各 adapter のデフォルト値:
- Claude Code: medium / workspace=true / ask_before_shell
- Codex: medium / workspace=true / allow_write
- Generic: high / workspace=false / ask_before_shell

`POST /api/worker/adapters/{adapter_id}/health` で Tauri runtime から adapter の health status を sync 可能。

#### External CLI adapter (Claude Code / Codex / Generic)

External CLI adapter は **Rust 側の `ExternalCliRegistry`** に独立して登録される。バックエンドの `CoordinatorAdapter` row は bundle payload 生成と UI 表示用のメタデータであり、実行は Rust の `ExternalCliAdapter` trait 実装が担当する。

- `ExternalCliAdapter` trait: `validate_environment()` / `supports_capabilities()` / `build_command()` / `build_prompt()` / `classify_failure()` / `normalize_result()`
- `ExternalCliCapability` enum (12種): `FileRead` / `FileWrite` / `ShellExec` / `DiffReview` / `LocalAuthSession` / `StructuredPatchSummary` / `BackgroundTask` / `StreamingStdout` / `StreamingStderr` / `WorkspaceAware` / `JsonOutput` / `Pty`
- `ExternalCliExecutionStatus` enum: `Pending` / `Running` / `Succeeded` / `Failed` / `TimedOut` / `Cancelled` / `MissingBinary` / `AuthRequired` / `CapabilityMismatch` / `Unsupported`
- concrete adapters: `ClaudeCodeAdapter` (完全実装) / `CodexAdapter` (scaffold、`codex --help` で flag 検証予定) / `GenericAdapter` (config-driven、テスト/任意 CLI)

generic runner (`external_cli_runner::run_external_cli_with_adapter`) が runtime非依存の処理を担当:
- cwd 検証 (home 配下のみ許可)
- subprocess spawn (`tokio::process::Command` = pipe / `portable-pty` = PTY duplex)
- line-buffered stdout/stderr capture → `external_cli:stdout_chunk` / `stderr_chunk` イベント
- timeout / cancel
- changed files diff (top-level snapshot)
- output truncation (1 MiB cap)
- `ExternalCliCapabilityChecked` / `Planned` / `Started` / `Finished` / `Failed` イベント emit

### Task Envelope

`build_task_envelope` がアダプター間で受け渡し可能なポータブル JSON を生成する。

```python
{
  "envelope_version": "1.0",
  "envelope_id": "uuid",
  "plan_id": "uuid",
  "task": {...},
  "context": {"goal", "prior_tasks", "summaries"},
  "artifacts": [...],
  "constraints": {"deadline_ms", "max_turns", "writes_files"},
  "budget": {"class", "provider_mode"},
  "expected_output": {"schema", "artifact_type"},
  "return_channel": {"event_stream", "artifact_sink"}
}
```

### Eval Harness

`compute_eval_metrics` が plan の状態から下記を算出:

- `completeness` — 完了 artifact / total task
- `factuality` — quality_gate 通過率 (ヒューリスティック)
- `revision_rate` — reflection_loop > 0 の割合
- `judge_pass_rate` — judge_decision の pass 率
- `local_usage_rate` — local_* な provider_mode の artifact 比率
- `remote_escalation_rate` — researcher/writer で remote に escalate された比率
- `overhead_ms` — plan 開始から最終 artifact までの経過時間

`record_eval_run` で履歴に追記し、後で local 解禁範囲を判断する材料にする。

### Resume / Partial Replay

`list_resumable_plans` が「artifact が一部だけ存在し未完了の plan」を列挙する。
`find_unfinished_tasks` で artifact 未生成の task を取得し、
それらだけを再実行できるようにする (実行ロジックは既存の continue_workflow_execution が担う)。

## API エンドポイント

### Coordinator (`/api/user/coordinator/`)

| method | path | 内容 |
|-------|------|------|
| GET | `/plans/{workflow_execution_id}` | plan + workers + artifacts + events + dag + layers + workspaces + followups |
| GET | `/adapters` | 登録済みアダプター一覧 (risk/workspace/approval defaults 含む) |
| GET | `/eval/{workflow_execution_id}` | 現在のメトリクス + 履歴 |
| POST | `/eval/{workflow_execution_id}/snapshot` | メトリクスを履歴に記録 |
| GET | `/resumable` | 再開可能な plan 一覧 |

### Session + Approval (`/api/user/workflow-executions/`)

| method | path | 内容 |
|-------|------|------|
| GET | `/{id}/session` | session state (status / bindings / refs) |
| GET | `/{id}/events?namespace=` | 正規化イベント一覧 (namespace フィルタ可) |
| GET | `/{id}/approvals` | 承認リクエスト一覧 |
| POST | `/{id}/approvals/{approval_id}/respond` | 承認応答 (granted / rejected) |

### Worker (`/api/worker/`)

| method | path | 内容 |
|-------|------|------|
| POST | `/adapters/{adapter_id}/health` | adapter health sync (Tauri → backend) |

## フロントエンド

`workflow-execute.html` の `coordinator-plan-section` に折りたたみで表示。
`renderCoordinatorPlan` が下記を順に描画:

1. **サマリー** — タスク数 / ワーカー数 / 複雑度 / 並列度 / アーティファクト数
2. **Workers** — 名前付きワーカーを provider lane として色分け表示
3. **DAG レイヤー** — depends_on を解決した実行レイヤー
4. **タスク一覧** — 各タスクの role / objective / resolved provider mode
5. **Artifacts (lineage)** — 生成済みアーティファクトの履歴
6. **Follow-up tasks** — 派生タスク
7. **Workspaces** — 予約済みワークスペースの状態
8. **Eval Metrics** — 評価メトリクスチップ
9. **Registered Adapters** — 登録アダプター
10. **直近イベント** — 最大10件

## 既存システムとの境界

| 既存 | 変更なし |
|------|--------|
| `WorkflowExecution / Execution` | スキーマ・進行ロジックそのまま |
| `WorkflowGroup` (serial/parallel) | そのまま |
| 品質ゲート / Judge / Supervisor | そのまま |
| Tauri OrchestrationManager (worker pool) | そのまま |
| sidecar の LLM 呼び出し | そのまま |

| 追加 | 役割 |
|------|------|
| `CoordinatorPlan` | 観測スナップショット (実行は駆動しない) |
| `CoordinatorArtifact` | execution 出力を構造化保存 |
| `CoordinatorEvent` | synthesis_log と並列のイベントログ + 正規化イベント (schema_version="2.0") |
| `CoordinatorWorker` | worker pool の論理投影 |
| `CoordinatorAdapter` | 実行先抽象化 (risk / workspace / approval defaults 付き) |
| Session 列 on `WorkflowExecution` | durable session (status / bindings / resume) |
| `ApprovalRequest` | ask_before_shell の承認リクエスト lifecycle |

Coordinator + Session 層は観測 + メタデータ + 承認制御で、抜いても既存実行は動きます (session 列は全て nullable)。
