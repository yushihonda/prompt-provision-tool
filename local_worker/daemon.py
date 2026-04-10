"""
常駐ワーカーデーモン

ターミナルで起動しておくと:
  1. サーバーを定期ポーリング (GET /api/worker/claim)
  2. pending_local の Job を自動取得
  3. ローカルで並列実行
  4. 結果をサーバーに送信 → UI に反映 (SSE)
  5. ワークフローの場合、サーバーが次ステップを自動生成 → デーモンがまた拾う

つまり: UIで実行ボタン → デーモンが自動処理 → UIに結果表示
"""
import asyncio
import logging
import signal
import time
from typing import Optional

import httpx

from .config import config
from .executor import execute_bundle, ExecutionResult

logger = logging.getLogger(__name__)

BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
RED = "\033[31m"


class WorkerDaemon:
    """常駐ワーカー"""

    def __init__(
        self,
        token: str,
        max_concurrent: int = 8,
        poll_interval: float = 2.0,
    ):
        self.token = token
        self.max_concurrent = max_concurrent
        self.poll_interval = poll_interval
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.running = True
        self.active_count = 0
        self.completed_count = 0
        self.error_count = 0
        self._is_worker_key = token.startswith("wpk_")
        self._headers = {"X-Worker-Key": token} if self._is_worker_key else {"Authorization": f"Bearer {token}"}

    async def start(self):
        """デーモン開始"""
        print(f"\n{BOLD}{'='*60}")
        print(f"  ローカルワーカー常駐モード")
        print(f"{'='*60}{RESET}")
        print(f"  サーバー:     {config.server_url}")
        print(f"  最大同時実行: {self.max_concurrent}")
        print(f"  ポーリング:   {self.poll_interval}s")
        print(f"\n  {GREEN}待機中... UIから実行すると自動で処理されます{RESET}")
        print(f"  {DIM}(Ctrl+C で停止){RESET}\n")

        # Ctrl+C で graceful shutdown
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._shutdown)

        while self.running:
            try:
                jobs = await self._claim_jobs()
                if jobs:
                    # 並列で処理
                    tasks = [self._process_job(job) for job in jobs]
                    await asyncio.gather(*tasks, return_exceptions=True)
                else:
                    # ジョブなし → 待機
                    await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Polling error: {e}")
                await asyncio.sleep(self.poll_interval * 2)

        print(f"\n{YELLOW}シャットダウン中...{RESET}")
        # 実行中のタスクの完了を待つ
        while self.active_count > 0:
            print(f"  {DIM}実行中: {self.active_count} 件の完了を待機中...{RESET}")
            await asyncio.sleep(1)

        print(f"\n{BOLD}ワーカー停止{RESET}")
        print(f"  完了: {self.completed_count}, エラー: {self.error_count}")

    def _shutdown(self):
        self.running = False

    async def _refresh_token(self) -> bool:
        """dev-login で JWT を再取得する。成功なら True。"""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{config.server_url}/api/auth/dev-login?role=user",
                )
                if resp.status_code == 200:
                    new_token = resp.json().get("access_token")
                    if new_token:
                        self.token = new_token
                        self._headers = {"Authorization": f"Bearer {new_token}"}
                        print(f"  {GREEN}トークンを再取得しました{RESET}")
                        return True
        except Exception as e:
            logger.error(f"Token refresh failed: {e}")
        return False

    async def _claim_jobs(self) -> list:
        """サーバーから pending_local ジョブを取得"""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{config.server_url}/api/worker/claim?limit={self.max_concurrent}",
                    headers=self._headers,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("jobs", [])
                elif resp.status_code == 401:
                    if self._is_worker_key:
                        print(f"  {RED}認証エラー: Worker API Key が無効です{RESET}")
                        self.running = False
                    else:
                        print(f"  {YELLOW}JWT 期限切れ — 再取得を試みます...{RESET}")
                        refreshed = await self._refresh_token()
                        if not refreshed:
                            print(f"  {RED}トークン再取得に失敗しました。停止します{RESET}")
                            self.running = False
                    return []
                else:
                    return []
        except httpx.ConnectError:
            logger.debug("Server not reachable, retrying...")
            return []
        except Exception as e:
            logger.error(f"Claim error: {e}")
            return []

    async def _process_job(self, job: dict):
        """1つのジョブを処理"""
        execution_id = job["execution_id"]
        job_token = job["job_token"]
        model = job.get("model", "?")
        wf_id = job.get("workflow_execution_id")
        step = job.get("skill_order")
        auth = {"Authorization": f"Bearer {job_token}"}

        async with self.semaphore:
            self.active_count += 1
            ts = time.strftime("%H:%M:%S")

            wf_info = f" (WF:{wf_id} Step:{step})" if wf_id else ""
            print(f"  {ts} {CYAN}[#{execution_id}]{RESET} 開始{wf_info} model={model} {DIM}(active:{self.active_count}){RESET}")

            try:
                # 1. バンドル取得
                async with httpx.AsyncClient(base_url=config.server_url, timeout=config.request_timeout) as client:
                    resp = await client.get(
                        f"/api/worker/executions/{execution_id}/bundle",
                        headers=auth,
                    )
                    if resp.status_code != 200:
                        raise RuntimeError(f"Bundle error: {resp.status_code}")
                    bundle = resp.json()

                # 2. ローカル LLM 実行（チャンクを Redis に送信）
                start = time.time()
                long_running_warned = False

                async def _send_chunk(chunk_text):
                    """チャンクをサーバー経由で Redis Stream に送信 + 長時間警告"""
                    nonlocal long_running_warned
                    try:
                        async with httpx.AsyncClient(base_url=config.server_url, timeout=10) as c:
                            await c.post(
                                f"/api/worker/executions/{execution_id}/chunk",
                                headers={**auth, "Content-Type": "application/json"},
                                json={"chunk": chunk_text},
                            )
                    except Exception as chunk_err:
                        logger.warning(f"[#{execution_id}] Chunk send failed: {chunk_err}")

                    # 長時間実行警告 (30分超)
                    if not long_running_warned and time.time() - start > 1800:
                        long_running_warned = True
                        ts_now = time.strftime("%H:%M:%S")
                        print(f"  {ts_now} {YELLOW}[#{execution_id}] 警告: 30分以上実行中{RESET}")

                result = await execute_bundle(bundle, on_chunk=_send_chunk)
                elapsed = time.time() - start
                result.execution_time_ms = int(elapsed * 1000)

                # 3. 結果送信
                complete_payload = {
                    "output": result.output,
                    "tokens_used": result.tokens_used,
                    "model_used": result.model_used,
                    "execution_time_ms": result.execution_time_ms,
                }
                if getattr(result, "external_cli_meta", None) is not None:
                    complete_payload["external_cli_meta"] = result.external_cli_meta
                if getattr(result, "provider_meta", None) is not None:
                    complete_payload["provider_meta"] = result.provider_meta
                async with httpx.AsyncClient(base_url=config.server_url, timeout=60) as client:
                    resp = await client.post(
                        f"/api/worker/executions/{execution_id}/complete",
                        headers={**auth, "Content-Type": "application/json"},
                        json=complete_payload,
                    )

                self.completed_count += 1
                print(
                    f"  {ts} {GREEN}[#{execution_id}]{RESET} 完了 "
                    f"{len(result.output)} chars, {elapsed:.1f}s "
                    f"{DIM}(total:{self.completed_count}){RESET}"
                )

            except Exception as e:
                self.error_count += 1
                print(f"  {ts} {RED}[#{execution_id}]{RESET} エラー: {e}")

                # 失敗した external_cli 実行（auth_required, timeout,
                # missing_binary, 非ゼロ終了等）は .external_cli_meta 付きの
                # RuntimeError を raise する。worker ログに埋もれず
                # CoordinatorArtifact で監査できるよう backend に転送する。
                err_payload = {
                    "error_message": str(e),
                    "execution_time_ms": 0,
                }
                cli_meta = getattr(e, "external_cli_meta", None)
                if isinstance(cli_meta, dict):
                    err_payload["external_cli_meta"] = cli_meta
                provider_meta = getattr(e, "provider_meta", None)
                if isinstance(provider_meta, dict):
                    err_payload["provider_meta"] = provider_meta

                # エラー報告
                try:
                    async with httpx.AsyncClient(base_url=config.server_url, timeout=10) as client:
                        await client.post(
                            f"/api/worker/executions/{execution_id}/error",
                            headers={**auth, "Content-Type": "application/json"},
                            json=err_payload,
                        )
                except Exception:
                    pass

            finally:
                self.active_count -= 1
