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
| `backend/app/services/coordinator_service.py` | Plan / Worker / Artifact / Event / Workspace / DAG / Provider Router |
| `backend/app/services/coordinator_extensions.py` | Adapter Registry / Task Envelope / Eval Harness / Resume |
| `backend/app/api/user.py` | `/api/user/coordinator/*` エンドポイント |
| `frontend/user/js/workflow-execute.js` | `loadCoordinatorPlan` / `renderCoordinatorPlan` |

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

| name | type | provider_mode | impl |
|------|------|--------------|------|
| internal-sidecar | internal | remote_only | sidecar.main |
| local-llm-ollama | local_llm | local_preferred | http://localhost:11434/v1 |
| remote-api-openai-compat | remote_api | remote_only | user_api_keys |

`find_adapter_for_task(role, provider_mode)` でルックアップする。

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
