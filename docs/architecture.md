# NexMAGI アーキテクチャ

## 全体構成

```
┌─────────────────────────────────────────────┐
│  Tauri Desktop App                          │
│  ├─ Frontend (Vanilla JS, 3D CSS)           │
│  ├─ Keychain Auth + SQLite Local History    │
│  ├─ OrchestrationManager (Rust)             │
│  │   └─ worker pool (max 4 sidecars)        │
│  └─ sidecar (Python) per worker             │
│        └─ OpenAI / Gemini / Anthropic SDK   │
└──────────────┬──────────────────────────────┘
               │ HTTP
               ▼
┌─────────────────────────────────────────────┐
│  Backend (Docker)                           │
│  ├─ FastAPI (auth / admin / user / worker)  │
│  ├─ MySQL 8.0 (永続化)                      │
│  ├─ Redis (SSE ストリーミング)              │
│  └─ ワークフロー継続制御                    │
│       ├─ 品質ゲート / リフレクション        │
│       ├─ ジャッジ / スーパーバイザー        │
│       ├─ 動的タスク分解                     │
│       └─ Coordinator 観測層                 │
└─────────────────────────────────────────────┘
```

## 実行フロー

1. ユーザーがフロントエンドからワークフロー実行ボタンを押下
2. `POST /api/execute/workflow` で `WorkflowExecution` と最初の `Execution` (status=`pending_local`) を生成
3. 同時に `CoordinatorPlan` を生成（観測スナップショット、実行は駆動しない）
4. Tauri 側 `OrchestrationManager` が `pending_local` をポーリングして取得
5. sidecar をサブプロセスとして起動し、LLM API を呼び出し
6. 結果を `POST /api/worker/executions/{id}/complete` に送信
7. `finalize_execution` が `output_data` を保存し、`CoordinatorArtifact` を生成
8. `continue_workflow_execution` が次ステップを起動（直列なら次のスキル、並列なら次のグループ）
9. 全ステップ完了後、リーダースキルが結果を統合

## レイヤーと責務

| レイヤー | 責務 |
|---------|------|
| Tauri Desktop | UI / 認証 / ワーカー pool / sidecar 起動 |
| sidecar | 単一 execution の LLM 実行 |
| FastAPI | ワークフロー継続制御・状態管理・暗号化 |
| MySQL | 永続化 (workflow / execution / coordinator) |
| Redis | SSE ストリーミング |
| Coordinator 観測層 | 観測・メタデータ・評価メトリクス |

## 観測層 (Coordinator) の位置付け

Coordinator 層はワークフロー実行を**観測してメタデータを蓄積するだけ**で、実行を駆動しません。
既存の `WorkflowExecution / Execution + OrchestrationManager` が実行のソース・オブ・トゥルースです。
将来的に Coordinator 自身が adapter を呼び出す自律的オーケストレーションへ移行する余地を残しています。

詳細は [`coordinator.md`](./coordinator.md) を参照。

## API キー管理

API キーはユーザーごとに暗号化保存されます。サーバー側 `.env` のフォールバックは廃止済み。

詳細は [`api-keys.md`](./api-keys.md) を参照。
