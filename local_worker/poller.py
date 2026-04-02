"""
Poller: サーバーから実行バンドルを取得する

- job_token モード: 特定の execution_id のバンドルを取得
- worker_key モード: 将来的に claim エンドポイントでジョブを取得（Phase 3+）
"""
import logging
from typing import Optional

import httpx

from .config import config

logger = logging.getLogger(__name__)


async def fetch_bundle(
    execution_id: int,
    auth_override: Optional[dict] = None,
) -> dict:
    """
    サーバーから署名付き run bundle を取得する。

    Args:
        execution_id: 実行 ID
        auth_override: 認証ヘッダーの上書き（job_token 直接指定時）

    Returns:
        bundle dict (execution_id, final_prompt, model, input_data, signature, ...)
    """
    url = f"{config.server_url}/api/worker/executions/{execution_id}/bundle"
    headers = auth_override or config.auth_headers

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        bundle = resp.json()

    logger.info(
        f"Bundle fetched: execution_id={bundle['execution_id']}, "
        f"model={bundle['model']}, prompt_len={len(bundle.get('final_prompt', ''))}"
    )
    return bundle
