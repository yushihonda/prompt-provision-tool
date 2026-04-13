"""Read-only discovery helpers for OpenAI-compatible local LLM servers.

These functions are the only place that hits a local provider's discovery
surface (`GET {base_url}/models`). Both `OpenAICompatibleHttpProvider`
preflight and the sidecar `/local/health` route call into here.

All functions swallow exceptions and return structured dicts. They never
raise.
"""
from __future__ import annotations

import time
from typing import Any

import httpx


def _normalize_base(base_url: str) -> str:
    return base_url.rstrip("/")


def ping(base_url: str, timeout: float = 5.0) -> dict[str, Any]:
    """Probe whether `{base_url}/models` is reachable.

    Returns:
        {
            "reachable": bool,
            "latency_ms": int | None,
            "error": str | None,
        }
    """
    url = f"{_normalize_base(base_url)}/models"
    started = time.monotonic()
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(url)
    except httpx.ConnectError as exc:
        return {"reachable": False, "latency_ms": None, "error": f"connect_error: {exc}"}
    except httpx.TimeoutException as exc:
        return {"reachable": False, "latency_ms": None, "error": f"timeout: {exc}"}
    except httpx.HTTPError as exc:
        return {"reachable": False, "latency_ms": None, "error": f"http_error: {exc}"}

    latency_ms = int((time.monotonic() - started) * 1000)
    if resp.status_code >= 400:
        return {
            "reachable": False,
            "latency_ms": latency_ms,
            "error": f"http_{resp.status_code}",
        }
    return {"reachable": True, "latency_ms": latency_ms, "error": None}


def list_models(base_url: str, timeout: float = 5.0) -> dict[str, Any]:
    """Fetch the model list from `{base_url}/models`.

    Returns:
        {
            "reachable": bool,
            "models": list[str],
            "latency_ms": int | None,
            "error": str | None,
        }

    On parse failure, returns reachable=True with empty models and an
    error string so callers can distinguish "server up but malformed" from
    "server unreachable".
    """
    url = f"{_normalize_base(base_url)}/models"
    started = time.monotonic()
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(url)
    except httpx.ConnectError as exc:
        return {
            "reachable": False,
            "models": [],
            "latency_ms": None,
            "error": f"connect_error: {exc}",
        }
    except httpx.TimeoutException as exc:
        return {
            "reachable": False,
            "models": [],
            "latency_ms": None,
            "error": f"timeout: {exc}",
        }
    except httpx.HTTPError as exc:
        return {
            "reachable": False,
            "models": [],
            "latency_ms": None,
            "error": f"http_error: {exc}",
        }

    latency_ms = int((time.monotonic() - started) * 1000)
    if resp.status_code >= 400:
        return {
            "reachable": False,
            "models": [],
            "latency_ms": latency_ms,
            "error": f"http_{resp.status_code}",
        }

    try:
        data = resp.json()
    except ValueError as exc:
        return {
            "reachable": True,
            "models": [],
            "latency_ms": latency_ms,
            "error": f"malformed_json: {exc}",
        }

    raw_models = data.get("data") if isinstance(data, dict) else None
    if not isinstance(raw_models, list):
        return {
            "reachable": True,
            "models": [],
            "latency_ms": latency_ms,
            "error": "malformed_response",
        }

    models: list[str] = []
    for item in raw_models:
        if isinstance(item, dict):
            mid = item.get("id")
            if isinstance(mid, str):
                models.append(mid)

    return {
        "reachable": True,
        "models": models,
        "latency_ms": latency_ms,
        "error": None,
    }
