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
| `backend/app/services/coordinator_service.py` | Plan / Worker / Artifact / Event / Workspace / DAG / Provider Router / `resolve_execution_kind` |
| `backend/app/services/coordinator_extensions.py` | Adapter Registry / Task Envelope / Eval Harness / Resume / local adapter health refresh |
| `backend/app/services/external_cli_adapters.py` | external_cli bundle payload 構築 (`build_external_cli_payload`) |
| `backend/app/services/external_cli_capabilities.py` | capability 定数 + `required_capabilities_for_task` |
| `backend/app/services/completion_service.py` | `build_external_cli_provenance` + artifact metadata 永続化 |
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
| `desktop/src-tauri/src/external_cli_adapters/{claude_code,codex,generic}.rs` | concrete adapters |
| `desktop/src-tauri/src/local_llm.rs` | `local_llm_ping` / `local_llm_list_models` Tauri commands |
| `frontend/user/js/workflow-execute.js` | `loadCoordinatorPlan` / `renderCoordinatorPlan` |
| `frontend/user/cli-terminal.html` | External CLI ターミナルページ (xterm.js + PTY) |
| `frontend/user/js/cli-terminal-view.js` | パイプモード ストリーミングビューア |
| `frontend/user/js/cli-terminal-pty.js` | PTY duplex ターミナル |

## DB テーブル

| テーブル | 主キー | 内容 |
|---------|-------|------|
| `coordinator_plans` | `plan_id` (UUID) | ワークフロー実行ごとの事前計画 |
| `coordinator_workers` | `worker_id` (UUID) | 名前付き論理ワーカー (researcher-1, writer-2 等) |
| `coordinator_artifacts` | `artifact_id` (UUID) | execution 出力を notes / draft / review / score / final として保存 |
| `coordinator_events` | `id` | オーケストレーションイベントの時系列ログ |
| `coordinator_followup_tasks` | `task_id` (UUID) | 既存タスクから派生する追加タスク |
| `coordinator_workspaces` | `workspace_id` (UUID) | writes_files=true なタスクの分離ワークスペース |
| `coordinator_adapters` | `adapter_id` (UUID) | 実行バックエンドのレジストリ |
| `coordinator_eval_runs` | `eval_id` (UUID) | 品質メトリクス履歴 |

`workflow_executions.coordinator_plan_id` で `CoordinatorPlan` と紐付ける。

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

### Events

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

### DAG

`task.depends_on` を解決して `build_task_dag` で `{nodes, edges}` を返し、
`topological_sort_tasks` で並列実行可能なレイヤーに分解する。
クロスグループ依存・並列最適化に使う。

### Workspace Isolation

`writes_files=true` なタスクには `auto_reserve_workspaces_for_plan` が
`temp_dir` モードのワークスペースを自動予約する。実体ディレクトリは
クライアント側 (Tauri) が管理し、バックエンドは状態とパスのみ保持する。

ステータス遷移: `reserved → active → promoted (or cleaned)`

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

すべて `/api/user/coordinator/` 配下:

| method | path | 内容 |
|-------|------|------|
| GET | `/plans/{workflow_execution_id}` | plan + workers + artifacts + events + dag + layers + workspaces + followups |
| GET | `/adapters` | 登録済みアダプター一覧 |
| GET | `/eval/{workflow_execution_id}` | 現在のメトリクス + 履歴 |
| POST | `/eval/{workflow_execution_id}/snapshot` | メトリクスを履歴に記録 |
| GET | `/resumable` | 再開可能な plan 一覧 |

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
| `CoordinatorEvent` | synthesis_log と並列のイベントログ |
| `CoordinatorWorker` | worker pool の論理投影 |
| `CoordinatorAdapter` | 将来の実行先抽象化 |

Coordinator 層は完全に観測 + メタデータ層で、抜いても既存実行は動きます。
