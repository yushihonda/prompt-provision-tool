"""
Uploader: 実行結果をサーバーに送信する
"""
import logging
from typing import Optional

import httpx

from .config import config
from .executor import ExecutionResult

logger = logging.getLogger(__name__)


async def upload_result(
    execution_id: int,
    result: ExecutionResult,
    auth_override: Optional[dict] = None,
) -> dict:
    """
    実行結果をサーバーの complete API に送信する。

    Args:
        execution_id: 実行 ID
        result: 実行結果
        auth_override: 認証ヘッダー上書き

    Returns:
        サーバーレスポンス
    """
    url = f"{config.server_url}/api/worker/executions/{execution_id}/complete"
    headers = auth_override or config.auth_headers

    payload = {
        "output": result.output,
        "tokens_used": result.tokens_used,
        "model_used": result.model_used,
        "execution_time_ms": result.execution_time_ms,
    }
    # external_cli 実行は構造化された meta dict を持ち、backend が
    # build_external_cli_provenance() で利用する。実際に値がある場合のみ
    # キーを含め、HTTP 実行のペイロード形状を従来と完全に同一に保つ。
    if getattr(result, "external_cli_meta", None) is not None:
        payload["external_cli_meta"] = result.external_cli_meta
    if getattr(result, "provider_meta", None) is not None:
        payload["provider_meta"] = result.provider_meta

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    logger.info(f"Result uploaded for execution {execution_id}: status={data.get('status')}")
    return data


async def upload_error(
    execution_id: int,
    error_message: str,
    execution_time_ms: int = 0,
    auth_override: Optional[dict] = None,
    external_cli_meta: Optional[dict] = None,
    provider_meta: Optional[dict] = None,
) -> dict:
    """
    エラーをサーバーに報告する。

    external_cli_meta が渡された場合は failure artifact に来歴情報を
    残せるよう backend に転送する。
    """
    url = f"{config.server_url}/api/worker/executions/{execution_id}/error"
    headers = auth_override or config.auth_headers

    payload = {
        "error_message": error_message,
        "execution_time_ms": execution_time_ms,
    }
    if external_cli_meta is not None:
        payload["external_cli_meta"] = external_cli_meta
    if provider_meta is not None:
        payload["provider_meta"] = provider_meta

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    logger.info(f"Error reported for execution {execution_id}: {error_message[:100]}")
    return data
