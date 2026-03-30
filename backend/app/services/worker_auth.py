"""
ローカルワーカー認証・署名サービス

- job_token: 実行開始時に発行される短命トークン（ワーカーがバンドルを取得・結果をPOSTする際に使用）
- bundle 署名: HMAC-SHA256 でバンドル全体の完全性を保証
- Worker API Key: アカウント単位の長期認証キー
"""
import hashlib
import hmac
import json
import secrets
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from jose import JWTError, jwt

from app.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Job Token (短命 JWT)
# ---------------------------------------------------------------------------

def create_job_token(execution_id: int, account_id: int) -> str:
    """
    実行用の短命 job_token を生成する。
    ワーカーはこのトークンで bundle GET / complete POST を認証する。
    """
    expire = datetime.utcnow() + timedelta(minutes=settings.WORKER_JOB_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": f"job:{execution_id}",
        "execution_id": execution_id,
        "account_id": account_id,
        "type": "job_token",
        "exp": expire,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def verify_job_token(token: str) -> Optional[dict]:
    """
    job_token を検証し、ペイロードを返す。無効な場合は None。
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("type") != "job_token":
            return None
        return payload
    except JWTError:
        return None


# ---------------------------------------------------------------------------
# Worker API Key
# ---------------------------------------------------------------------------

def generate_worker_api_key() -> Tuple[str, str]:
    """
    ワーカー API キーを生成する。
    Returns:
        (raw_key, key_hash) — raw_key はユーザーに1回だけ表示、key_hash は DB 保存用
    """
    raw_key = f"wpk_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    return raw_key, key_hash


def hash_worker_api_key(raw_key: str) -> str:
    """raw_key から DB 照合用ハッシュを生成"""
    return hashlib.sha256(raw_key.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Bundle 署名 (HMAC-SHA256)
# ---------------------------------------------------------------------------

def sign_bundle(bundle_dict: dict) -> str:
    """
    バンドル辞書を JSON 正規化して HMAC-SHA256 署名を生成する。
    """
    canonical = json.dumps(bundle_dict, sort_keys=True, ensure_ascii=False)
    sig = hmac.new(
        settings.bundle_signing_key.encode(),
        canonical.encode(),
        hashlib.sha256,
    ).hexdigest()
    return sig


def verify_bundle_signature(bundle_dict: dict, signature: str) -> bool:
    """
    バンドルの署名を検証する。
    """
    expected = sign_bundle(bundle_dict)
    return hmac.compare_digest(expected, signature)


# ---------------------------------------------------------------------------
# Lease Token (バンドル取得用ワンタイム)
# ---------------------------------------------------------------------------

def generate_lease_token() -> Tuple[str, str]:
    """
    リース用トークンを生成する。
    Returns:
        (raw_token, token_hash)
    """
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    return raw_token, token_hash


def verify_lease_token(raw_token: str, stored_hash: str) -> bool:
    """リーストークンを検証"""
    computed = hashlib.sha256(raw_token.encode()).hexdigest()
    return hmac.compare_digest(computed, stored_hash)
