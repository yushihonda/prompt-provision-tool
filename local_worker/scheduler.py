"""
Scheduler: asyncio.Semaphore で同時実行数を制御し、
バンドル取得 → 実行 → アップロードの全フローを管理する。
"""
import asyncio
import logging
import time
from typing import Optional

from .config import config
from .poller import fetch_bundle
from .executor import execute_bundle
from .uploader import upload_result, upload_error

logger = logging.getLogger(__name__)


class WorkerScheduler:
    """ローカルワーカースケジューラ"""

    def __init__(self, max_concurrent: Optional[int] = None):
        self.max_concurrent = max_concurrent or config.max_concurrent
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        self._active_count = 0
        self._completed_count = 0
        self._error_count = 0

    async def run_single(
        self,
        execution_id: int,
        auth_override: Optional[dict] = None,
    ) -> bool:
        """
        単一の実行を処理する（セマフォで同時実行制御）。

        Args:
            execution_id: 実行 ID
            auth_override: 認証ヘッダー

        Returns:
            成功なら True
        """
        async with self._semaphore:
            self._active_count += 1
            logger.info(
                f"Starting execution {execution_id} "
                f"(active={self._active_count}/{self.max_concurrent})"
            )

            try:
                # 1. バンドル取得
                bundle = await fetch_bundle(execution_id, auth_override)

                # 2. LLM 実行
                result = await execute_bundle(bundle)

                # 3. 結果アップロード
                await upload_result(execution_id, result, auth_override)

                self._completed_count += 1
                logger.info(
                    f"Execution {execution_id} completed successfully "
                    f"(total_completed={self._completed_count})"
                )
                return True

            except Exception as e:
                self._error_count += 1
                logger.error(f"Execution {execution_id} failed: {e}")

                # エラーをサーバーに報告
                try:
                    await upload_error(
                        execution_id,
                        str(e),
                        auth_override=auth_override,
                    )
                except Exception as upload_err:
                    logger.error(
                        f"Failed to report error for {execution_id}: {upload_err}"
                    )

                return False
            finally:
                self._active_count -= 1

    async def run_batch(
        self,
        execution_ids: "list[int]",
        auth_override: Optional[dict] = None,
    ) -> dict:
        """
        複数の実行を並列処理する。

        Args:
            execution_ids: 実行 ID のリスト
            auth_override: 認証ヘッダー

        Returns:
            {"completed": int, "errors": int, "total": int}
        """
        start = time.time()
        logger.info(
            f"Starting batch: {len(execution_ids)} executions, "
            f"max_concurrent={self.max_concurrent}"
        )

        tasks = [
            self.run_single(eid, auth_override) for eid in execution_ids
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        completed = sum(1 for r in results if r is True)
        errors = sum(1 for r in results if r is not True)
        elapsed = time.time() - start

        logger.info(
            f"Batch complete: {completed}/{len(execution_ids)} succeeded, "
            f"{errors} errors, {elapsed:.1f}s elapsed"
        )

        return {
            "completed": completed,
            "errors": errors,
            "total": len(execution_ids),
            "elapsed_seconds": round(elapsed, 1),
        }

    @property
    def stats(self) -> dict:
        return {
            "active": self._active_count,
            "completed": self._completed_count,
            "errors": self._error_count,
            "max_concurrent": self.max_concurrent,
        }
