# ユーザー API キー設定

## 概要

NexMAGI では各ユーザーが自分の OpenAI / Gemini / Anthropic API キーを設定して
LLM を呼び出します。サーバー側 `.env` のフォールバックは廃止され、キーが未設定の
ユーザーはワークフローを実行できません。

## ストレージ

- テーブル: `api_configs` (account_id にユニーク制約)
- カラム: `openai_api_key`, `gemini_api_key`, `anthropic_api_key` (Fernet 暗号化)
- 暗号化キー: バックエンドの `ENCRYPTION_KEY` 環境変数 (32 byte)
- 関連サービス: `app/encryption.py` (`encryption_service.encrypt_api_key` / `decrypt_api_key` / `mask_api_key`)

## ユーザー API

### GET `/api/user/settings/api-config`

自分の API 設定をマスク表示で取得。

```json
{
  "openai_api_key": "sk-p****abcd",
  "gemini_api_key": null,
  "anthropic_api_key": "sk-a****wxyz",
  "is_enabled": true,
  "rate_limit_per_hour": 100,
  "rate_limit_per_day": 1000
}
```

`is_enabled` / `rate_limit_*` は管理者設定で読み取り専用。

### PATCH `/api/user/settings/api-config`

自分のキーを更新 (upsert 対応)。

```json
{
  "openai_api_key": "sk-...",
  "gemini_api_key": "AIza...",
  "anthropic_api_key": "sk-ant-..."
}
```

- 値が `null` のフィールドは無視 (既存キー保持)
- 空文字列を渡すとクリア
- ユーザーは `rate_limit_*` や `is_enabled` を変更できない (管理者権限)
- 行が無ければ自動作成 (upsert)

## 管理者 API

既存の `/api/admin/accounts` および `/api/admin/accounts/{id}` (PATCH) で管理者は
任意のユーザーの API キー・レート制限・有効状態を上書き可能。

## ワーカー側のキー受け取り

`GET /api/worker/executions/{id}/bundle` がユーザーの暗号化キーを復号して bundle に含めて返す。
sidecar は bundle の `api_keys` を直接プロバイダー SDK に渡す。

```python
api_keys = {}
api_config = db.query(APIConfig).filter(
    APIConfig.account_id == execution.account_id,
    APIConfig.is_enabled == True,
).first()
if api_config:
    if api_config.openai_api_key:
        api_keys["openai"] = encryption_service.decrypt_api_key(api_config.openai_api_key)
    ...
# サーバー側 .env のフォールバックは廃止
bundle_data["api_keys"] = api_keys if api_keys else None
```

ユーザーがキー未設定でワークフロー実行を試みると、worker 側で
「APIキーが設定されていません」エラーが返り、フロントで失敗扱いになります。

## フロントエンド

`frontend/user/settings.html` (ナビ「API設定」)
- OpenAI / Gemini / Anthropic の3つのパスワード入力
- 各キーの設定状態 (✓ / ✗) と masked 値の表示
- 管理者設定のレート制限・有効状態は読み取り専用表示
- 入力欄が空のフィールドは送信されない (既存キー保持)

## セキュリティ

- 平文キーは DB に保存しない (Fernet で暗号化)
- マスク表示: 先頭 4 文字 + `****` + 末尾 4 文字
- 管理者の閲覧時もマスク (生キーはサーバー外に出ない)
- ワーカー bundle 配信時のみ復号 (HMAC 署名対象外)
- フロントエンド入力フィールドは `type="password"`
