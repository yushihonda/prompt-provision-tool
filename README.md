# Prompt Provision Tool

スキルを秘匿したまま、AI 実行機能を提供する **次世代AIオーケストレーションフレームワーク**。

現在は既存の Web アプリに加えて、`desktop/` + `sidecar/` を用いた **Tauri ベースの desktop preview** を段階導入しています。直近のマイルストーンは `Observable Local Execution` で、desktop 側に `workflow_run_events` の永続ログ、continuation 重複防止、frontend runtime adapter を追加しました。

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

## Desktop Preview

desktop preview は、既存 `frontend/` をそのまま流用しつつ、Tauri shell と Python sidecar で local execution を観測可能にするための実験実装です。

```bash
# 前提: Rust toolchain / npm / Python 3.11+
cd desktop
npm install

# Tauri dev 起動
npm run tauri:dev
```

現時点の desktop preview で確認できるもの:

- SQLite 初期化
- engine mode (`api_key` / `cli`) の保存
- Python sidecar の stdio 起動と health check
- demo workflow 実行
- sidecar 経由の real skill 実行
- sidecar 経由の real workflow 実行
- `workflow_run_events` の event 永続化
- continuation dedupe の最小確認

desktop local execution の最小仕様:

- desktop では `frontend -> Tauri -> sidecar -> backend(bundle/complete/error)` を real 実行導線とする
- `workflow_run_events` への append は引き続き Tauri 単一路
- current milestone の local execution は result-first で、token/chunk streaming はまだ sidecar 正本へ移していない
- `configured_engine_mode=cli` の real path では `sidecar` が `provider_error_code` / `retry_reason` / `token_accounting_source` の canonical source になる
- `local_worker` は CLI provider adapter として使うが、provider-level failure を再解釈しない
- app restart 後の復元は backend 側 `executions` / `workflow_executions` の状態再読込を正本とする
- sidecar failure 時は Tauri 側 `workflow_runs.status = error` に落とし、完了前の中間 event は保証しない

最小 event 列:

- `ui.single_skill_execute_clicked` または `ui.workflow_execute_clicked`
- `workflow_run_created`
- `node_execution_started`
- `provider_request_started`
- `provider_request_finished`
- `retry_decision_made`
- `node_execution_finished`

continuation 検証時の追加 event:

- `continuation_candidate_detected`
- `continuation_lock_acquired` または `continuation_lock_rejected`
- `continuation_spawned` または `duplicate_suppressed`

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
  index.html              Desktop home (Tauri preview)
  admin/                  管理画面 (ワークフロー/スキル管理)
  user/                   ユーザー画面 (実行, 履歴, ダウンロード)
  js/runtime-adapter.js   browser / desktop 差分吸収
desktop/                  Tauri shell
  src-tauri/              Rust commands, SQLite, sidecar process 管理
sidecar/                  Desktop sidecar (Python)
  main.py                 stdio JSON RPC, demo workflow stub
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
- desktop preview: prompt は memory-only decryption 前提、`workflow_run_events` は payload を持つが plaintext prompt 保存先にはしない

## Observable Local Execution

desktop preview の現在地です。設計意図は「動く土台」から「壊れない土台」へ進めることにあります。

- 正本: 実行イベントの正本は `workflow_run_events`
- スナップショット: `workflow_runs` は一覧表示用の補助テーブル
- 単一ライタ: SQLite は desktop 側のみが書き込む
- dedupe: continuation は DB 制約で active lock を 1 件に制限
- adapter: frontend の `apiBase`, `workerUrl`, `navigate()` を `frontend/js/runtime-adapter.js` に集約

event 共通フィールド:

- `event_id`
- `event_type`
- `run_id`
- `node_id`
- `attempt_no`
- `occurred_at`
- `correlation_id`
- `causation_id`
- `root_event_id`
- `trigger_event_id`
- `origin_layer`
- `idempotency_key`
- `schema_version`
- `payload_json`

provider lifecycle 観測の現時点の境界:

- 正本は desktop の `append_workflow_run_event` command を通る `workflow_run_events`
- desktop local execution の real skill / workflow 実行では、`provider_request_*` / `retry_decision_made` は `sidecar/main.py` が返す engine-origin batch を正本とする
- real path の `observation_source` は `engine_origin_batch`、demo preview の `observation_source` は `demo_sidecar_preview` として分離する
- browser / server path の既存 SSE/stream 観測は残すが、desktop local path では proxy producer を使わない

次の packaging 前提条件:

- provider 観測の正本を sidecar / local engine 側へ寄せる
- `workflow_run_events` の append 単一路を Tauri command のまま維持する
- sidecar bundling 後も prompt 本文は plaintext で event payload に入れない

desktop real execution の runtime 語彙:

- `configured_engine_mode`: desktop 設定に保存された値
- `effective_engine_mode`: 実行時に sidecar が採用した経路
- `provider_mode`: `api_key` または `cli`
- `provider_transport`: `sdk` / `subprocess`
- `provider_adapter`: `none` / `local_worker`
- `provider_runtime`: `python` / `binary`
- `provider_impl`: `sdk_execute_bundle` / `local_worker.provider_adapter` / `ppt-provider-adapter` などの診断用詳細
- `auth_key_source`: `bundle_api_keys` / `local_env` / `bundle_or_local_env` / `not_applicable` / `none`
- `token_accounting_source`: `provider_usage` / `tiktoken_estimate` / `char_estimate` / `unavailable`
- `provider_error_code`: provider 固有の canonical error code
- `retry_reason`: retry policy に渡す canonical reason
- 集計・履歴比較は `provider_mode` を主軸にし、障害解析は detail fields を使う
- diagnostics と `run_local_skill_execution` / `run_local_workflow_execution` の result payload は同じ語彙を返す
- packaged CLI binary へ差し替える場合も `provider_mode=cli` は不変で、主に `provider_runtime` / `provider_impl` を更新する
- subprocess 継続で bundled executable を呼ぶ場合、`provider_transport=subprocess` は変えない

provider field の命名ルール:

| Field | Role | Layer | Example Values | Change When | Do Not Change When |
|------|------|------|------|------|------|
| `provider_mode` | 実行経路の意味 | stable / semantic | `api_key`, `cli` | API key 実行と CLI 実行のように意味上の経路が変わるとき | Python module -> binary、adapter 差し替え、impl 名変更など内部実装だけが変わるとき |
| `provider_transport` | provider 実装への到達方式 | diagnostic / implementation | `sdk`, `subprocess`, `http`, `grpc`, `ipc` | subprocess -> SDK 直呼び、HTTP 常駐化など呼び出し方式が変わるとき | subprocess 呼び出しのままで対象だけが module -> binary に変わるとき |
| `provider_adapter` | 仲介層 | diagnostic / implementation | `none`, `local_worker`, `embedded_adapter` | 仲介層を追加・削除・差し替えするとき | 仲介層を保ったまま runtime / impl だけが変わるとき |
| `provider_runtime` | 実装の実行環境 | diagnostic / implementation | `python`, `binary`, `node`, `rust` | Python -> binary のように実行環境が変わるとき | runtime は同じで impl 名だけが変わるとき |
| `provider_impl` | 具体的実装識別子 | diagnostic / implementation | `sdk_execute_bundle`, `local_worker.provider_adapter`, `ppt-provider-adapter` | 実際に呼ぶ対象が変わるとき | 同じ target を呼び続けるとき |

短い判断ルール:

- 意味が変わらないなら `provider_mode` は変えない
- 接続方式が変わったときだけ `provider_transport` を変える
- 仲介層が変わったときだけ `provider_adapter` を変える
- 実行環境が変わったときだけ `provider_runtime` を変える
- 具体的に呼ぶ対象が変わったとき `provider_impl` を変える

anti-pattern:

- `cli_subprocess_provider`
- `python_cli_provider`
- `local_worker_cli`
- `ppt-provider-adapter`

これらは `provider_mode` に入れない。理由は意味ではなく実装詳細だから。

packaged CLI binary build:

```bash
python3 -m pip install -r local_worker/requirements-build.txt
npm --prefix desktop run sidecar:build
npm --prefix desktop run cli-provider:build
npm --prefix desktop run tauri:build
```

期待成果物:

- `desktop/src-tauri/resources/bin/ppt-provider-adapter`
- `desktop/src-tauri/resources/bin/ppt-sidecar`

packaged build verification の最小確認:

```bash
npm --prefix desktop ci
cd desktop/src-tauri && cargo check
cd ../../
CARGO_TARGET_DIR="$PWD/desktop/.cargo-target" \
npm --prefix desktop run tauri:build

CARGO_TARGET_DIR="$PWD/desktop/.cargo-target" \
npm --prefix desktop run verify:packaged:health

CARGO_TARGET_DIR="$PWD/desktop/.cargo-target" \
npm --prefix desktop run verify:packaged:storage
```

ここで期待すること:

- `provider_mode=cli`
- `provider_transport=subprocess`
- `provider_runtime=binary`
- `provider_impl=ppt-provider-adapter`

optional な real skill verification:

```bash
PPT_DESKTOP_API_BASE="<backend base url>" \
PPT_VERIFY_AUTH_TOKEN="<dev-login or user token>" \
PPT_VERIFY_SKILL_ID=17 \
PPT_VERIFY_SKILL_NAME="総合リサーチ＆戦略立案（単体版）" \
PPT_VERIFY_ENABLE_DEEP_THINK=true \
PPT_VERIFY_INPUT_JSON='{"topic":"clean machine packaged verification","objective":"assert bundled sidecar and cli provider semantics"}' \
CARGO_TARGET_DIR="$PWD/desktop/.cargo-target" \
npm --prefix desktop run verify:packaged:skill
```

補足:

- `desktop/scripts/run_packaged_verification.mjs` が macOS `.app` と Windows `.exe` の packaged executable path を吸収する
- runtime truth の正本は Rust/Tauri 側で、helper は Rust が返した contract / JSON を読んで assert するだけに留める
- artifact path を手動指定したい場合は `PPT_VERIFY_EXECUTABLE_PATH` で override できる
- real skill verification の最小 fixture contract は `PPT_DESKTOP_API_BASE`, `PPT_VERIFY_AUTH_TOKEN`, `PPT_VERIFY_SKILL_ID`
- `desktop/src-tauri/tauri.release.conf.json` は release build 専用で、updater artifact・macOS entitlements・Windows sign command を通常 build から分離する
- `.github/workflows/desktop-release.yml` は sign / notarize / updater manifest / GitHub Release publish を担当し、`.github/workflows/desktop-clean-machine-verify.yml` は runtime truth verification だけを担当する
- release workflow は build 前に `desktop/scripts/check_release_prereqs.mjs` を通し、updater/signing/notarization secrets の不足を fail-fast する
- release workflow は build 後に `verify:packaged:storage:strict` を通し、signed runtime でだけ `authSessionRoundTripOk=true` を要求する
- release workflow は artifact upload 前後に `desktop/scripts/check_release_artifacts.mjs` を通し、metadata / asset / signature の整合を fail-fast する
- desktop auth session は OS keychain 経由で保持し、SQLite は workflow/event/engine_mode の永続化に限定する

今回確認できた事実:

- `cargo check` は通過
- `npm --prefix desktop run tauri:build` は通過
- `CARGO_TARGET_DIR="$PWD/desktop/.cargo-target"` を固定すると packaged executable path を再現的に解決できる
- `npm --prefix desktop run verify:packaged:health` は通過
- `npm --prefix desktop run verify:packaged:storage` は通過し、`authSessionWriteOk=true`, `tokenFoundInDb=false`, `usernameFoundInDb=false` を返す
- `npm --prefix desktop run verify:packaged:skill:optional` は fixture 未設定時に skip できる
- unsigned/local packaged build では `authSessionRoundTripOk` が false になり得るため、secure storage の最終 round-trip 確認は signed release run で行う
- release artifact sanity check は `metadata.json` / asset / `.sig` の存在と targetKey 重複を fail-fast する
- packaged verification report は `contract.truthOwner=rust_tauri`, `contract.helperPolicy=discover_launch_read_assert_only` を返す
- packaged app は `Contents/Resources/resources/bin/ppt-provider-adapter` を解決
- packaged app は `Contents/Resources/resources/bin/ppt-sidecar` を解決
- packaged `runtime_config.sidecarScriptPath` と `resolvedSidecarPath` は bundle 内の `ppt-sidecar` を返す
- packaged `sidecar_health` は `provider_mode=cli`, `provider_transport=subprocess`, `provider_runtime=binary`, `provider_impl=ppt-provider-adapter`
- packaged real skill 1 本は `success` で完了し、`token_accounting_source=provider_usage` / `provider_error_code=null` / `retry_reason=null`
- packaged real skill の `workflow_run_events` は 7 件 (`workflow_run_created` → `workflow_run_finished`) で stable/detail fields が payload と result で一致

Completion gate:

internal-distribution-ready:

- `.github/workflows/desktop-clean-machine-verify.yml` の `packaged-health` を macOS / Windows 両方で green にし、その中の `verify:packaged:storage` で `tokenFoundInDb=false` を維持すること
- `packaged-real-skill` は optional gate とし、fixture 未設定時は skip、設定時のみ追加 E2E として扱うこと
- 社内向け package を `npm --prefix desktop run tauri:build` で再現的に生成できること
- 社内ユーザー向けに macOS / Windows 初回起動手順を説明できること

commercial-release-ready:

- `.github/workflows/desktop-release.yml` で `release preflight -> signed build -> verify:packaged:storage:strict -> artifact sanity -> updater manifest publish -> GitHub Release upload` が通ること
- signed release run で desktop auth session の `authSessionRoundTripOk=true` を確認し、token を SQLite に保存しないこと

社内配布 runbook:

- package 生成:
  `npm --prefix desktop ci`
  `python3 -m pip install -r local_worker/requirements-build.txt`
  `CARGO_TARGET_DIR="$PWD/desktop/.cargo-target" npm --prefix desktop run tauri:build`
- macOS 配布:
  `.app` または `.dmg` を社内配布し、初回起動は `右クリック -> 開く` を案内する
- macOS で quarantine が強く残る場合:
  `xattr -dr com.apple.quarantine "Prompt Provision Tool Desktop.app"`
- Windows 配布:
  `prompt-provision-tool-desktop.exe` または installer を社内共有し、unsigned 警告が出る前提を案内する
- 期待値:
  社内配布版は runtime truth / secure storage non-SQLite proof を required にし、OS trust chain は commercial-release-ready に残す

commercial-release-ready 後に残る運用領域:

- updater endpoint / public key の本番値確定
- 配布チャネル運用（draft / promote / rollback）

残見積もり:

- clean machine verification workflow 定義まで含めた PC アプリ化はおよそ `94-96%`
- hosted runner での初回 green run 確認で追加 `0.5-1営業日`
- release secrets を使った初回 signed release 検証で追加 `1-2営業日`
- 署名 / notarization / updater / 配布導線まで含めると `1週間弱`

## 詳細資料

- [docs/README_FULL.md](docs/README_FULL.md) - 全仕様 (API, DB, 運用手順)
- [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) - 要件定義
- [docs/DEPLOYMENT_CHECKLIST.md](docs/DEPLOYMENT_CHECKLIST.md) - デプロイチェックリスト
