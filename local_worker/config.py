"""
ローカルワーカー設定

環境変数または .env.worker から読み込む。
"""
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

# .env.worker を読み込む
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env.worker"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        # フォールバック: .env.local
        env_local = Path(__file__).parent.parent / ".env.local"
        if env_local.exists():
            load_dotenv(env_local)
except ImportError:
    pass


@dataclass
class WorkerConfig:
    """ローカルワーカー設定"""

    # サーバー接続
    server_url: str = os.getenv("WORKER_SERVER_URL", "http://localhost:8000")

    # 認証（どちらか一方を使用）
    worker_api_key: Optional[str] = os.getenv("WORKER_API_KEY")
    job_token: Optional[str] = os.getenv("WORKER_JOB_TOKEN")

    # AI API キー（ローカル実行用）
    openai_api_key: Optional[str] = os.getenv("OPENAI_API_KEY")
    gemini_api_key: Optional[str] = os.getenv("GEMINI_API_KEY")
    anthropic_api_key: Optional[str] = os.getenv("ANTHROPIC_API_KEY")

    # 実行制御
    max_concurrent: int = int(os.getenv("WORKER_MAX_CONCURRENT", "8"))
    poll_interval_seconds: float = float(os.getenv("WORKER_POLL_INTERVAL", "2.0"))
    request_timeout: int = int(os.getenv("WORKER_REQUEST_TIMEOUT", "3600"))

    # ログ
    log_level: str = os.getenv("WORKER_LOG_LEVEL", "INFO")

    @property
    def auth_headers(self) -> dict:
        """認証ヘッダーを生成"""
        if self.job_token:
            return {"Authorization": f"Bearer {self.job_token}"}
        if self.worker_api_key:
            return {"X-Worker-Key": self.worker_api_key}
        return {}


config = WorkerConfig()
