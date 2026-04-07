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
│       ├─ resolve_execution_kind │
│       │   (http / external_cli) │
│       └─ Adapter Registry +     │
│         health refresh API      │
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
9. `continue_workflow_execution` が次ステップを起動（直列なら次のスキル、並列なら次のグループ）
10. 全ステップ完了後、リーダースキルが結果を統合

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

### 選択ルール (初期実装、opt-in)
1. `judge` ロールは **強制的に** `http_provider` (remote_only) — 個人サブスクを judge に使わない
2. タスクに `prefer_external_cli=true` + `cli_runtime_hint`(`claude_code`/`codex`/`generic`) があり、対応する adapter が enabled → `external_cli`
3. `cwd` が無いタスクは external_cli に行かない (sandbox 安全確保)
4. それ以外は既存 `resolve_execution_provider` にフォールスルー → `http_provider`

### External CLI 実行所有権
Sidecar は `execution_kind=external_cli` の bundle を見たら `delegated_to_external_cli_runtime` marker を返して何もしません。desktop Rust の `consume_external_cli_bundle` Tauri command が同じ execution を fetch して registry 経由で実行し、completion を POST します。これにより Rust = runtime truth の原則を保ちつつ、外部 CLI 実行の所有権が明確に分離されます。

### External CLI capability gate
`ExternalCliAdapter` trait の `supports_capabilities()` が、タスクの `required_capabilities` と adapter の declared capabilities を比較します。mismatch のときは spawn 前に `CapabilityMismatch` ステータスで拒否し、`ExternalCliCapabilityChecked { passed: false, missing_capabilities }` イベントを emit します。これによりシェル実行不可の adapter に shell タスクが流れる、といった事故を型レベルで防ぎます。

## API キー管理

API キーはユーザーごとに暗号化保存されます。サーバー側 `.env` のフォールバックは廃止済み。

詳細は [`api-keys.md`](./api-keys.md) を参照。
