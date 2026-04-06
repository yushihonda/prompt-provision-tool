# NexMAGI

**次世代AIオーケストレーションデスクトップアプリ** — マルチエージェントワークフローを3Dビジュアルパイプラインで実行・管理。

## 概要

NexMAGI は Tauri ベースのデスクトップアプリケーションで、複数のAIエージェント（Explore / Plan / Implement / Verification）を組み合わせたワークフローを実行します。

- **3Dアクリルキューブ** による直感的なパイプライン表示
- **マルチモデル対応** — OpenAI GPT-5.x / Gemini 3.x / Claude 4.x
- **品質ゲート** — Verification ステップで自動品質検証・リトライ
- **リアルタイム進捗** — ステップごとのローディング表示とステータス管理

## 構成

```
NexMAGI Desktop (Tauri)          バックエンド (Docker)
  フロントエンド配信                スキル暗号化保存
  Keychain 認証                   バンドル配信 (復号+署名)
  Sidecar AI実行                  結果保存・課金
  ローカルSQLite                   ワークフロー継続制御
```

## クイックスタート

```bash
# 1. Docker 起動 (バックエンド)
cd deployment
docker compose -f docker-compose.local.yml up -d

# 2. マイグレーション
docker exec ppt-backend alembic upgrade head

# 3. デスクトップアプリ起動
cd desktop
npm install
npm run tauri:dev
```

## 主な機能

### ワークフロー実行
- マルチステップ AI ワークフロー（直列・並列）
- 3D アクリルキューブによるリアルタイムパイプライン表示
- 品質ゲート（Quality Gate）による自動検証・リフレクション
- ステップごとの入出力表示

### 管理画面
- スキル作成・編集（プロンプトテンプレート管理）
- ワークフロー作成・編集（グループ構造、並列実行）
- アカウント管理（API キー、レート制限）
- 実行ログ（ミニ3Dキューブで可視化）

### デスクトップ機能
- Tauri + Rust によるネイティブアプリ
- macOS Keychain による安全な認証
- Python Sidecar によるローカル AI 実行
- マルチワーカーオーケストレーション

## 技術スタック

| レイヤー | 技術 |
|---------|------|
| デスクトップ | Tauri 2.x + Rust |
| フロントエンド | Vanilla JS + CSS (3D transforms) |
| バックエンド | FastAPI + SQLAlchemy |
| データベース | MySQL 8.0 + Redis |
| AI実行 | Python (OpenAI / Gemini / Claude SDK) |

## ライセンス

Proprietary
