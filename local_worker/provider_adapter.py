from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from .executor import classify_executor_failure, execute_bundle_once


async def _run(payload: dict[str, Any]) -> dict[str, Any]:
    bundle = {
        "final_prompt": payload.get("prompt") or "",
        "model": payload.get("model") or "",
        "enable_deep_think": bool(payload.get("enable_deep_think", True)),
        "api_keys": payload.get("api_keys") or {},
    }
    model_override = payload.get("model_override")
    try:
        result = await execute_bundle_once(bundle, model_override=model_override)
        return {
            "status": "success",
            "output": result.output,
            "model_used": result.model_used,
            "tokens_used": result.tokens_used,
            "execution_time_ms": result.execution_time_ms,
            "token_accounting_source": result.token_accounting_source,
        }
    except Exception as exc:  # pragma: no cover - subprocess boundary
        return {
            "status": "error",
            "raw_error_kind": classify_executor_failure(exc),
            "raw_error_message": str(exc),
        }


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception as exc:  # pragma: no cover - subprocess boundary
        sys.stdout.write(
            json.dumps(
                {
                    "status": "error",
                    "raw_error_kind": "parse_failure",
                    "raw_error_message": str(exc),
                },
                ensure_ascii=True,
            )
        )
        return 1

    result = asyncio.run(_run(payload))
    sys.stdout.write(json.dumps(result, ensure_ascii=True))
    sys.stdout.flush()
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
