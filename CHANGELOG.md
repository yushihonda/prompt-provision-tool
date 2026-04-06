# Changelog

## [3.0.0] - 2026-04-06

### Breaking Changes
- **NexMAGI リブランディング** — アプリ名を「Prompt Provision Tool」から「NexMAGI」に変更
  - Tauri productName, bundle identifier: `com.nexmagi.desktop`
  - Cargo crate: `nexmagi-desktop`
  - 全HTMLタイトル、ヘッダーロゴ
- **WEB版廃止** — ブラウザ直接アクセスを廃止、Tauri デスクトップアプリ専用に
  - runtime-adapter.js: ブラウザフォールバック削除、デスクトップ固定
  - HTML初期化: `window.__TAURI__` 分岐削除
  - 認証: sessionStorage 廃止、Keychain/ファイル認証のみ
  - Docker: nginx webコンテナをコメントアウト

### Added
- **3Dアクリルキューブ** — ワークフロー実行パイプラインに preserve-3d + 3面キューブ表示
  - ロール別色分け（Explore=青, Plan=橙, Implement=緑, Verification=桃, Leader=紫）
  - ステータス連動（pending/processing/success/error で枠色・アニメーション変化）
  - ガラス風半透明エフェクト（color-mix + inset shadow）
- **切り抜きカードデザイン** — card-cutout + card-cutout-circle の再利用可能コンポーネント
  - ワークフロー実行の戻るボタン、入力パネルの実行ボタン、出力パネルのコピーボタン
  - バックグラウンドパネルの詳細へ/完了タスク
- **管理画面赤アクセント** — admin-theme に `--accent: #dc3545` を独立設定
- **ミニ3Dキューブ** — ダッシュボード、実行履歴、管理画面の実行ログで共通使用
  - mini-cube.js に共通関数として分離
- **モデルバッジ** — Deep Think / Pro / Thinking / NEW バッジを全表示箇所で統一
  - `formatModelDisplay` でスキル情報（enable_deep_think）を参照
  - バッジ色: 8px, !important で親要素の色継承を上書き
- **実行データ不変性** — `skill_name_snapshot`, `workflow_name_snapshot` カラム追加
  - 実行時点のスキル名/ワークフロー名をスナップショット保存
  - 編集後も過去の実行履歴が変わらない
- **ワークフロー実行詳細ポップアップ共通化** — `showWorkflowDetailPopup` を exec-detail-modal.js に集約
- **SweetAlert2共通設定** — swal-defaults.js で全ポップアップに×ボタン左上表示、閉じるボタン自動非表示
- **Verification UI** — 品質ゲート検証中/リトライ中のバッジ表示（検証中=オレンジ、再試行=#N）
- **ステータスインジケーター** — STEPラベル横にチェック/×アイコン（ドットからアイコンに変更）

### Changed
- **ポップアップデザイン統一** — border-radius 24px、入力フィールド 12px角丸、ボタン 20px角丸
- **フォーム要素統一** — 白背景、アクセント色フォーカスglow、カスタムselect矢印
- **ページネーション** — 丸いボタンデザイン
- **バッジサイズ** — 全バッジ 8px に統一（モデル名より小さく）
- **バックグラウンドパネル** — 完了検知改善、staleデータ自動クリア、復帰時ポーリング
- **実行履歴ステータス** — 特殊ロール（quality_gate等）のエラーをWF全体のエラーから除外

### Fixed
- **FINAL完了しない問題** — リーダーステータスを `handleWorkflowComplete` で確実に設定
- **バックグラウンドパネル完了しない問題** — ID不一致チェック緩和、catchでもmarkAsCompleted
- **詳細へ遷移で表示されない問題** — Stageメタデータ復元、ポーリング再開
- **実行中レイアウト崩れ** — wf-node-output を position:absolute に変更

## [2.0.1] - 2026-04-03

### Added
- **Desktop ネイティブ HTTP** — Tauri コマンド `native_http_request`（Rust `reqwest` + rustls）。リクエスト/レスポンスは JSON（本文は base64）でやり取りし、WebView 経由の `fetch` との差分を吸収
- **認証セッションのファイルミラー** — app data 直下に `auth_session.json` を書き込み（Unix は `0o600`）。未署名パッケージ等で keychain が不安定でもログイン状態を維持しやすくする
- **frontend** — `runtime-adapter.js` の desktop 分岐で `fetchWithRuntime` が `native_http_request` を使う。`FormData`（文字列フィールドのみ）/`URLSearchParams`/`Blob`/`ArrayBuffer`/TypedArray などを正規化

### Changed
- **認証セッション読み取り** — `auth_session.json` を優先し、無ければ keychain
- **keychain 書き込み** — `set_auth_session` 時はファイル必須・keychain はベストエフォート（失敗時はログのみ）
- **desktop Cargo** — `base64`, `reqwest`（`blocking`, `rustls-tls`）を追加

## [2.0.0] - 2026-04-02

### Added
- **自動オーケストレーション** — ワークフロー構造から品質ゲート・エラーリトライ・出力キー・ジャッジを自動推論（手動設定不要）
- **リーダー自動生成** — 親スキル内容をワークフロー名・説明から自動生成
- **永続メモリ** — workflow × profile 単位の長期記憶（`workflow_memories` テーブル）、実行をまたいで蓄積
- **Starter Seed** — ワークフロー初回実行時のみ適用される初期記憶
- **Coordinator View** — リアルタイム進捗表示（waiting_on, next_expected_action, latest_summary, why）
- **Synthesis Events** — 各ステップ完了・エラー・ジャッジ・品質ゲートのタイムラインをDB保存
- **Follow-up Continuation** — retry/reflection 時の継続メタデータ（_ppt_continuation）
- **Structured Result Envelope** — 出力から summary/key_points/next_action_hint を抽出
- **Profile 固定色** — Explore=青, Plan=橙, Implement=緑, Verification=桃, Leader=紫
- **Override 可視化** — profile 解決元（skill_default/workflow_override）を詳細モーダルに表示
- **Verification 証跡フォーマット** — コード検証用（Command run/Output observed）+ コンテンツ検証用（根拠）
- **Adversarial Probe** — PASS 前に最低1つの壊しテストを必須化
- **ワークフロー一括有効化/無効化** — アカウント管理でWF単位でスキルを一括操作
- **管理者用 WF 実行ステータス API** — `/api/admin/workflow-executions/{id}/status`
- **ダッシュボード統計** — ワークフロー数・スキル数の分割表示
- **ワークフロー実行履歴にモデル表示** — 親スキルのモデルを全画面で統一表示
- **Profile フロー表示** — ユーザーダッシュボードのWFカードに Explore → Plan → Implement → Verification を表示

### Changed
- **管理画面URL** — `admin/skills.html` → `admin/dashboard.html` にリネーム
- **親スキルモード** — `required` 固定に簡素化（optional/disabled 廃止）
- **Agent Profile 選択** — スキル作成時は「未指定」がデフォルト、Leader はWF専用で選択不可
- **ステージ表示** — 「Default」→「Leader」に変更（紫色）
- **実行履歴フィルタ** — 特殊ロール（ジャッジ等）を totalTime/totalTokens から適切に除外/包含
- **マイグレーション** — 001-006 を 001 に統合（新規セットアップは1ファイルで完了）
- **coordinator_view 文言** — 「empty dict」廃止、日本語を自然化
- **入力フォーム** — ワークフロー共通入力と重複するフィールドを自動除外

### Removed
- `enable_web_search` / `enable_code_interpreter` / `enable_file_search` — 全59箇所から完全削除
- 管理画面のオーケストレーション手動設定UI（品質ゲート・出力キー・エラー時・ジャッジ・SV）
- リーダースキル内容の手動入力欄
- スキル編集ポップアップの「新しいワークフローを作成」セクション
- OpenAI/Gemini サービスの tools 死んだコード

### Fixed
- `worker.py`: Workflow ローカルインポートによる UnboundLocalError
- `worker.py`: 自動ジャッジのバンドル生成時 404 エラー
- `worker.py`: wf_j 変数スコープ問題
- `execution_tasks.py`: ジャッジ/SVエラー時の無限retryループ防止
- `admin/skills.html`: WFテーブル colspan 修正
- `style.css`: execute-output-panel の display:flex 復元
- フロントエンド全体: `getModelDisplayName` → `formatModelDisplay` 統一
- HTML: 3ファイルの `</body>` 閉じタグ欠落修正
- Gemini サービス: 空 tools 配列が API に渡される問題

### Testing
- テスト数: 14 → 28 に倍増
- extract_verdict edge case（mixed case, whitespace, 複数VERDICT）
- _extract_structured_envelope（JSON/```json/malformed）
- append_synthesis_event（追記/100件制限/破損ログ復旧）
- handoff_summary 必須フィールド検証
- verdict fallback to FAIL
- verification 以外は verdict 未設定を確認

## [1.0.0] - 2026-03-31

### Added
- 初期リリース
- ワークフローオーケストレーション（グループ・並列・直列）
- Agent Profile（explore/plan/implement/verification/default）
- Blackboard（共有メモリ）
- 品質ゲート・Reflection
- Supervisor・Judge・Dynamic Decomposition
- ローカルワーカー実行
- SSE ストリーミング
- JWT 認証（PARENT/CHILD）
- スキル暗号化保存
