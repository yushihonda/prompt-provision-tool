# NexMAGI マルチエージェント・オーケストレーション

> NexMAGI の中核的な強み — 階層的な役割分担・品質制御・自己修正を備えたマルチエージェントワークフローエンジン

---

## 1. 概要

NexMAGI は単なる LLM ラッパーではなく、**複数の AI エージェントが役割を分担し、相互にレビュー・修正しながらタスクを遂行する**オーケストレーションエンジンです。

### 他のツールとの差別化ポイント

| 観点 | 一般的な AI ツール | NexMAGI |
|------|-------------------|---------|
| 実行モデル | 単一エージェント / 単発呼び出し | 複数エージェントの階層的協調 |
| 品質保証 | 人間が確認 | Quality Gate + Reflection Loop で自動修正 |
| 並列実行 | なし | 並列グループ + Judge による合意形成 |
| 監督機能 | なし | Supervisor がグループ単位でやり直し判定 |
| 共有記憶 | なし | Blackboard（共有メモリ）で全ステップが連携 |
| 実行環境 | クラウド API のみ | HTTP Provider + ローカル CLI（Claude Code 等）のデュアルランタイム |
| 承認制御 | なし | Plan Approval + Shell 実行前承認ゲート |

---

## 2. 役割一覧

NexMAGI には **5 つのエージェントプロファイル**（実行時の振る舞い）と **3 つのオーケストレーション役割**（制御用の特殊実行）、そして **1 つの統合リーダー**が存在します。

### 2.1 エージェントプロファイル（Agent Profiles）

各ステップに割り当てられ、プロンプト構成・制約・出力形式を決定します。

#### Explorer（探索エージェント）
- **責任**: コード・依存関係・リスクの調査
- **制約**: **読み取り専用**（diff/patch/git 操作を検出すると即座に失敗）
- **出力形式**: 調査サマリー / 重要ファイル / リスク / 再利用ポイント / ハンドオフ
- **典型的な位置**: ワークフローの最初のステップ

#### Planner（計画エージェント）
- **責任**: 実装方針・変更対象・テスト戦略の策定
- **制約**: **読み取り専用**
- **出力形式**: 実装戦略 / 変更対象 / 非変更対象 / 実装順序 / テスト戦略
- **典型的な位置**: Explorer の後、Implementer の前

#### Implementer（実装エージェント）
- **責任**: ファイルの作成・変更・削除の実行
- **制約**: 書き込み可。計画に矛盾があれば安全側に倒す
- **出力形式**: 実行結果 / 主な変更 / 前提・制約 / 残課題
- **実行環境**: HTTP Provider **または** External CLI（Claude Code / Codex 等）

#### Verifier（検証エージェント）
- **責任**: **敵対的テスト** — 壊すつもりで検証する
- **制約**: `VERDICT: PASS / FAIL / PARTIAL` の判定が必須
- **出力形式**: 検証サマリー / 発見事項（証跡付き） / 敵対的プローブ / 契約チェック / 最終判定
- **特徴**: 証跡フォーマット（コマンド実行結果 or ドキュメント引用）が必須

#### Default（汎用エージェント）
- **責任**: 特定の役割に当てはまらない汎用タスク
- **制約**: なし

### 2.2 オーケストレーション役割（Execution Roles）

ワークフロー制御のために自動生成される特殊な Execution です。

#### Quality Gate（品質ゲート）
- **介入タイミング**: 各ステップ実行**直後**
- **種類**: Inline（regex / JSON Schema）または LLM ベース
- **判定**: `approve` / `revise` / `stop` / `manual_review`
- **失敗時**: Reflection Loop（critique 付きで同じステップを再実行、最大 N 回）

#### Supervisor（監督者）
- **介入タイミング**: グループ内の全ステップ完了**後**
- **判定と効果**:
  - `approve` → 次グループへ進む
  - `revise` → 指定ステップを再実行
  - `repeat_group` → グループ全体をやり直し
  - `stop` → ワークフロー停止
  - `manual_review` → 人間の判断を待つ

#### Judge（審判）
- **介入タイミング**: **並列グループ**の全ステップ完了**後**
- **責任**: 複数の並列出力を比較し、最良の結果を選択 or 合意形成
- **結果**: Blackboard に判定を書き込み、後続ステップが参照可能

### 2.3 Parent Skill（統合リーダー）

- **介入タイミング**: **全グループ + 全 Supervisor/Judge 完了後**
- **常に実行**（`parent_skill_mode = "required"` 固定）
- **責任**: 全ステップの出力 + Blackboard を受け取り、最終統合結果を生成
- **位置**: ワークフローの最終ステップ（合成 Execution として自動生成）

---

## 3. 実行フロー

### 3.1 基本フロー

```
ユーザーが実行ボタンを押す
  │
  ▼
POST /api/execute/workflow
  │ WorkflowExecution + CoordinatorPlan 生成
  │ 最初のグループの最初のステップ用 Execution 生成
  ▼
┌─────────────────────────────────────────────┐
│  Group 1 (serial)                           │
│                                             │
│  [Explorer] → [Planner] → [Implementer]    │
│       │            │            │           │
│       ▼            ▼            ▼           │
│  Quality Gate  Quality Gate  Quality Gate   │
│  (pass/fail)   (pass/fail)   (pass/fail)   │
│       │            │            │           │
│       └────────────┴────────────┘           │
│                    │                        │
│                    ▼                        │
│              [Supervisor]                   │
│           approve / revise / stop           │
└─────────────────┬───────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────┐
│  Group 2 (parallel)                         │
│                                             │
│  [Agent A] ──┬── [Agent B] ──┬── [Agent C] │
│              │               │              │
│              ▼               ▼              │
│           全ステップ完了                     │
│              │                              │
│              ▼                              │
│           [Judge]                           │
│        最良の結果を選択                      │
└─────────────────┬───────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────┐
│  Group 3 (serial)                           │
│  [Verifier]                                 │
│       │                                     │
│       ▼                                     │
│  Quality Gate → VERDICT: PASS/FAIL/PARTIAL  │
│       │ FAIL → Reflection Loop (再実行)     │
└─────────────────┬───────────────────────────┘
                  │
                  ▼
        [Parent Skill（リーダー）]
          全出力 + Blackboard を統合
                  │
                  ▼
            最終結果を出力
```

### 3.2 Reflection Loop（自己修正）

```
ステップ実行 → 出力
      │
      ▼
 Quality Gate 評価
      │
   ┌──┴──┐
   │     │
  PASS  FAIL
   │     │
   │     ▼
   │  critique（改善指摘）生成
   │     │
   │     ▼
   │  同じステップを再実行
   │  入力に追加:
   │    - previous_attempt_output（前回出力）
   │    - quality_critique（改善指摘）
   │    - reflection_loop = N（何回目か）
   │     │
   │     ▼
   │  再び Quality Gate 評価
   │     │
   │  (最大 max_reflection_loops 回繰り返し)
   │     │
   └──┬──┘
      │
      ▼
   次のステップへ
```

### 3.3 Supervisor によるグループ制御

```
Group 内の全ステップ完了
      │
      ▼
 Supervisor が全出力を評価
      │
   ┌──┴──────────┬──────────────┬────────────┐
   │             │              │            │
 approve      revise      repeat_group     stop
   │             │              │            │
   ▼             ▼              ▼            ▼
 次グループ   指定ステップ    グループ全体  ワークフロー
   へ進む     のみ再実行     をリセット    を停止
                              して再実行
```

### 3.4 不合格時の挙動 — そのまま進むことはない

**全てのチェックポイントで不合格の場合、ワークフローは停止またはやり直しになります。**
「チェックに落ちたけどそのまま次に進む」というパスは存在しません。

#### Quality Gate が不合格の場合

```
Quality Gate 評価
      │
    FAIL
      │
      ▼
┌─ action を判定 ─────────────────────────────────────────────┐
│                                                              │
│  "revise"         → Reflection Loop（critique 付きで再実行） │
│                     最大 max_reflection_loops 回             │
│                     ↓ 回数を使い切ったら                      │
│                     → ワークフロー ERROR で停止               │
│                                                              │
│  "stop"           → ワークフロー ERROR で即座に停止           │
│                                                              │
│  "manual_review"  → ワークフロー manual_review_required       │
│                     人間の判断待ちで一時停止                   │
└──────────────────────────────────────────────────────────────┘
```

**コード根拠**: [execution_tasks.py:745-752](backend/app/tasks/execution_tasks.py#L745-L752) — Reflection Loop 上限超過で `wf_exec.status = "error"` に設定。

#### Supervisor が不承認の場合

```
Supervisor 判定
      │
   ┌──┴──────────────────────────────────────────────────────┐
   │                                                          │
   │  "approve"       → 次グループへ進む                       │
   │                                                          │
   │  "revise"        → 指定ステップの Execution を cancelled  │
   │                    にして再実行                            │
   │                    Blackboard に critique を記録           │
   │                                                          │
   │  "repeat_group"  → グループ内の全 Execution を cancelled  │
   │                    にしてグループ全体を再実行              │
   │                                                          │
   │  "stop"          → ワークフロー ERROR で即座に停止         │
   │                                                          │
   │  "manual_review" → ワークフロー manual_review_required     │
   │                    人間の判断待ちで一時停止                 │
   └──────────────────────────────────────────────────────────┘
```

**コード根拠**: [execution_tasks.py:965-1003](backend/app/tasks/execution_tasks.py#L965-L1003) — `revise`/`repeat_group` では対象 Execution を `cancelled` に更新し、`continue_workflow_execution` が再起動。

#### Judge が不承認の場合

```
Judge 判定
      │
   ┌──┴──────────────────────────────────────────────────────┐
   │                                                          │
   │  (通常)          → Blackboard に判定を書き込み            │
   │                    後続グループへ進む                      │
   │                                                          │
   │  "stop"          → ワークフロー ERROR で即座に停止         │
   │                                                          │
   │  "manual_review" → ワークフロー manual_review_required     │
   │                    人間の判断待ちで一時停止                 │
   └──────────────────────────────────────────────────────────┘
```

**コード根拠**: [completion_service.py:822-831](backend/app/services/completion_service.py#L822-L831) — Judge が `stop` を返すと `wf_exec.status = "error"` に設定。

#### Verifier の VERDICT が FAIL / PARTIAL の場合

```
Verifier 出力
      │
      ▼
VERDICT 抽出（正規表現 or JSON）
      │
   ┌──┴──────────────────────────────────────────────────────┐
   │                                                          │
   │  PASS            → final_verdict = "PASS"                │
   │                    → Quality Gate も PASS なら次へ         │
   │                                                          │
   │  FAIL / PARTIAL  → final_verdict = "FAIL" or "PARTIAL"   │
   │                    → ワークフロー自体は「完了」するが      │
   │                      final_verdict に記録される            │
   │                                                          │
   │  ※ Verifier に Quality Gate が設定されている場合:          │
   │    VERDICT: FAIL が Quality Gate の regex にマッチすると   │
   │    → Reflection Loop 発動（critique 付きで Verifier 再実行）│
   │    → 上限超過で ERROR 停止                                 │
   │                                                          │
   │  ※ Verifier に Quality Gate が未設定の場合:                │
   │    → FAIL/PARTIAL でも Execution 自体は success            │
   │    → final_verdict に記録されるが、ワークフローは続行       │
   │    → Parent Skill が FAIL verdict を含む情報で最終統合     │
   └──────────────────────────────────────────────────────────┘
```

**コード根拠**: [completion_service.py:148-153](backend/app/services/completion_service.py#L148-L153) — `verdict or "FAIL"` を `wf_exec.final_verdict` に保存。Verifier の Execution 自体は `status=success` になるため、Quality Gate が無ければワークフローは続行する。

#### まとめ: 不合格時のフォールバック一覧

| チェックポイント | 不合格時の挙動 | そのまま進む？ |
|:---|:---|:---:|
| **Quality Gate** (revise) | Reflection Loop → 上限超過で **ERROR 停止** | **進まない** |
| **Quality Gate** (stop) | **即座に ERROR 停止** | **進まない** |
| **Quality Gate** (manual_review) | **人間待ちで一時停止** | **進まない** |
| **Supervisor** (revise/repeat) | ステップ/グループ **再実行** | **進まない** |
| **Supervisor** (stop) | **即座に ERROR 停止** | **進まない** |
| **Supervisor** (manual_review) | **人間待ちで一時停止** | **進まない** |
| **Judge** (stop) | **即座に ERROR 停止** | **進まない** |
| **Judge** (manual_review) | **人間待ちで一時停止** | **進まない** |
| **Verifier** FAIL (Quality Gate あり) | Reflection Loop → 上限超過で **ERROR 停止** | **進まない** |
| **Verifier** FAIL (Quality Gate なし) | `final_verdict=FAIL` を記録して **続行** | **進む（※）** |

> **※ 唯一の例外**: Verifier に Quality Gate が設定されていない場合のみ、VERDICT: FAIL でも Parent Skill まで到達します。ただし `final_verdict` には FAIL が記録され、Parent Skill はこの情報を含めて最終統合を行います。これは設計上の意図であり、「Verifier が FAIL と判定した事実を含めた最終レポートを生成する」ためのパスです。

---

## 4. 干渉マップ — 誰がどこに介入するか

### 4.1 直接的な介入

| 役割 | 介入対象 | 介入タイミング | 介入方法 |
|------|---------|---------------|---------|
| **Quality Gate** | 個別ステップ | ステップ実行直後 | Reflection Loop で再実行を強制 |
| **Supervisor** | グループ全体 | グループ完了後 | approve / revise / repeat / stop |
| **Judge** | 並列ステップ群 | 並列グループ完了後 | 最良結果の選択・合意形成 |
| **Parent Skill** | ワークフロー全体 | 全グループ完了後 | 全出力の最終統合 |

### 4.2 間接的な介入（Blackboard 経由）

Blackboard（共有メモリ）を通じて、各役割は後続ステップの振る舞いに影響を与えます。

| 書き込み元 | Blackboard キー | 参照者 | 影響 |
|-----------|----------------|--------|------|
| 各ステップ | `{output_key}` | 後続の全ステップ | 出力データの共有 |
| Supervisor | `supervisor_group_{id}` | 再実行ステップ / 後続グループ | 改善指摘・判定理由の伝達 |
| Judge | `judge_group_{id}` | 後続グループ | 最良結果・合意内容の伝達 |

### 4.3 制御の階層構造

```
レイヤー 4: Parent Skill（最終統合）
    ▲ 全グループ完了後に介入
    │
レイヤー 3: Supervisor / Judge（グループ制御）
    ▲ グループ完了後に介入、やり直し可能
    │
レイヤー 2: Quality Gate（ステップ品質制御）
    ▲ 各ステップ完了後に介入、Reflection Loop
    │
レイヤー 1: Agent Profile（実行時制約）
    ▲ プロンプト構成・読み取り専用制約・出力形式
    │
レイヤー 0: Execution（実際の AI 実行）
    各ステップの LLM 呼び出し or CLI 実行
```

---

## 5. デュアルランタイム

各ステップは **2 つの実行環境** のいずれかで実行されます。

| 環境 | 用途 | 実行者 | 例 |
|------|------|--------|-----|
| **HTTP Provider** | クラウド LLM API 呼び出し | ローカルワーカー（Python sidecar） | OpenAI / Anthropic / Gemini |
| **External CLI** | ローカル CLI ツール実行 | Tauri デスクトップアプリ（Rust） | Claude Code / Codex / Generic |

ルーティングは **4 階層の設定チェーン** で決定されます:

```
Workflow.config_json
  └─ WorkflowGroup.config_json
       └─ Skill.config_json
            └─ WorkflowSkill.config_json  ← 最優先
```

External CLI ステップには **承認ゲート** が設けられ、shell 実行前にユーザーの許可を求めることができます。

---

## 6. 観測レイヤー

ワークフロー実行の全過程は以下の仕組みで可視化されます。

| コンポーネント | 内容 |
|---------------|------|
| **CoordinatorPlan** | 実行前のスナップショット（役割・タスク・レビュー方針） |
| **CoordinatorArtifact** | 各ステップの成果物記録（notes / draft / review / score） |
| **synthesis_log** | 時系列イベントログ（workflow_start → step_complete → leader_complete） |
| **WorkflowRunSession** | 永続セッション（状態遷移・ランタイムバインディング・承認サマリー） |
| **current_stage** | リアルタイムのステージ表示（explore → plan → implement → verification → leader） |
| **final_verdict** | 検証エージェントの最終判定（PASS / FAIL / PARTIAL） |

---

## 7. フロー図

以下のフロー図は `docs/diagrams/` ディレクトリに Mermaid ソースと PNG 画像として格納されています。

- **メインフロー**: [`multi-agent-orchestration-flow.mmd`](diagrams/multi-agent-orchestration-flow.png) — ワークフロー全体の実行フロー
- **役割干渉マップ**: [`role-intervention-map.mmd`](diagrams/role-intervention-map.png) — 各役割がどこに介入するかの関係図
