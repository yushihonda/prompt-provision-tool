from __future__ import annotations

import asyncio
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

from app.providers import ProviderRequest, create_provider  # noqa: E402
from app.providers.cli_provider import resolve_cli_invocation  # noqa: E402
from local_worker.config import config  # noqa: E402
from local_worker.executor import execute_bundle  # noqa: E402

OBSERVATION_SOURCE_ENGINE_ORIGIN_BATCH = "engine_origin_batch"
PROVIDER_MODE_API_KEY = "api_key"
PROVIDER_MODE_CLI = "cli"
AUTH_KEY_SOURCE_BUNDLE_API_KEYS = "bundle_api_keys"
AUTH_KEY_SOURCE_LOCAL_ENV = "local_env"
AUTH_KEY_SOURCE_BUNDLE_OR_LOCAL_ENV = "bundle_or_local_env"
AUTH_KEY_SOURCE_NOT_APPLICABLE = "not_applicable"
AUTH_KEY_SOURCE_NONE = "none"


@dataclass(slots=True)
class ExecutionRuntimeInfo:
    configured_engine_mode: str
    effective_engine_mode: str
    provider_mode: str
    provider_transport: str
    provider_adapter: str
    provider_runtime: str
    provider_impl: str
    auth_key_source: str
    observation_source: str = OBSERVATION_SOURCE_ENGINE_ORIGIN_BATCH

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SkillRunResult:
    execution_id: int
    status: str
    output: str
    model_used: str
    tokens_used: int
    execution_time_ms: int
    output_format: str
    skill_id: int | None = None
    workflow_execution_id: int | None = None
    workflow_skill_id: int | None = None
    skill_order: int | None = None
    skill_name: str | None = None
    workflow_name: str | None = None
    error_message: str | None = None
    execution_role: str | None = None
    configured_engine_mode: str = "api_key"
    effective_engine_mode: str = "api_key"
    provider_mode: str = PROVIDER_MODE_API_KEY
    provider_transport: str = "sdk"
    provider_adapter: str = "none"
    provider_runtime: str = "python"
    provider_impl: str = "sdk_execute_bundle"
    auth_key_source: str = AUTH_KEY_SOURCE_NONE
    observation_source: str = OBSERVATION_SOURCE_ENGINE_ORIGIN_BATCH
    provider_error_code: str | None = None
    provider_error_message: str | None = None
    retry_reason: str | None = None
    token_accounting_source: str = "unavailable"
    # Selected vs actual provider provenance (runtime fallback). Populated by
    # the http execution path. Other paths leave this None.
    provider_meta: dict[str, Any] | None = None

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class WorkflowRunResult:
    workflow_execution_id: int
    status: str
    execution_ids: list[int]
    leader_execution_id: int | None
    output: str
    error_message: str | None
    steps: list[dict[str, Any]]
    configured_engine_mode: str = "api_key"
    effective_engine_mode: str = "api_key"
    provider_mode: str = PROVIDER_MODE_API_KEY
    provider_transport: str = "sdk"
    provider_adapter: str = "none"
    provider_runtime: str = "python"
    provider_impl: str = "sdk_execute_bundle"
    auth_key_source: str = AUTH_KEY_SOURCE_NONE
    observation_source: str = OBSERVATION_SOURCE_ENGINE_ORIGIN_BATCH
    provider_error_code: str | None = None
    provider_error_message: str | None = None
    retry_reason: str | None = None
    token_accounting_source: str = "unavailable"

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


def preview_runtime_info(configured_engine_mode: str) -> ExecutionRuntimeInfo:
    if configured_engine_mode == "cli":
        invocation = resolve_cli_invocation()
        return ExecutionRuntimeInfo(
            configured_engine_mode=configured_engine_mode,
            effective_engine_mode="cli",
            provider_mode=PROVIDER_MODE_CLI,
            provider_transport=invocation.provider_transport,
            provider_adapter=invocation.provider_adapter,
            provider_runtime=invocation.provider_runtime,
            provider_impl=invocation.provider_impl,
            auth_key_source=AUTH_KEY_SOURCE_BUNDLE_OR_LOCAL_ENV,
        )
    return ExecutionRuntimeInfo(
        configured_engine_mode=configured_engine_mode,
        effective_engine_mode="api_key",
        provider_mode=PROVIDER_MODE_API_KEY,
        provider_transport="sdk",
        provider_adapter="none",
        provider_runtime="python",
        provider_impl="sdk_execute_bundle",
        auth_key_source=AUTH_KEY_SOURCE_BUNDLE_OR_LOCAL_ENV,
    )


def _detect_auth_key_source(bundle: dict[str, Any]) -> str:
    bundle_keys = bundle.get("api_keys") or {}
    if any(bundle_keys.get(provider) for provider in ("openai", "gemini", "anthropic")):
        return AUTH_KEY_SOURCE_BUNDLE_API_KEYS
    if any(
        (
            config.openai_api_key,
            config.gemini_api_key,
            config.anthropic_api_key,
        )
    ):
        return AUTH_KEY_SOURCE_LOCAL_ENV
    return AUTH_KEY_SOURCE_NONE


def _classify_provider_failure(error_message: str) -> tuple[str, str]:
    message = (error_message or "").lower()
    if "rate limit" in message or "resource exhausted" in message:
        return "provider_rate_limited", "provider_rate_limit"
    if "timeout" in message or "timed out" in message:
        return "provider_timeout", "provider_timeout"
    if "connection" in message or "unreachable" in message:
        return "provider_transport_error", "transport_error"
    if "api key" in message or "authentication" in message or "認証" in message:
        return "provider_authentication_failed", "local_environment_error"
    if "サポートされていないモデル" in message or "does not exist" in message:
        return "provider_model_unsupported", "local_environment_error"
    if "json" in message or "parse" in message or "malformed" in message:
        return "provider_output_malformed", "malformed_output"
    return "provider_local_environment_error", "local_environment_error"


def _payload_to_actual_meta(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "actual_provider_mode": payload.get("provider_mode_selected") or payload.get("provider_mode"),
        "actual_adapter_id": payload.get("adapter_id"),
        "actual_adapter_name": payload.get("adapter_name"),
        "actual_model": payload.get("model"),
        "actual_base_url": payload.get("base_url"),
        "actual_transport": payload.get("transport"),
    }


def _payload_to_selected_meta(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "selected_provider_mode": payload.get("provider_mode_selected") or payload.get("provider_mode"),
        "selected_adapter_id": payload.get("adapter_id"),
        "selected_adapter_name": payload.get("adapter_name"),
        "selected_model": payload.get("model"),
        "selected_base_url": payload.get("base_url"),
        "provider_selection_reason": payload.get("provider_selection_reason"),
    }


def _execute_http_provider(
    provider_payload: dict[str, Any],
    *,
    final_prompt: str,
    bundle_model: str,
    execution_id: int,
):
    """Run a single HTTP provider attempt and return the ProviderResponse.

    Sync HTTP call wrapped so that runtime-fallback orchestration can drive
    multiple provider attempts uniformly. Kept thin on purpose: any
    provider-side error classification lives in providers.errors.
    """
    provider = create_provider("http", provider_payload)
    return provider.run(
        ProviderRequest(
            prompt=final_prompt,
            model=str(provider_payload.get("model") or bundle_model or ""),
            metadata={"execution_id": execution_id},
        )
    )


async def _run_with_runtime_fallback(
    *,
    provider_payload: dict[str, Any],
    fallback_provider_payload: dict[str, Any] | None,
    final_prompt: str,
    bundle_model: str,
    execution_id: int,
):
    """Execute via the selected HTTP provider, falling back once on
    recoverable failures when policy allows.

    Returns (provider_response, provider_meta) where provider_response is
    the ProviderResponse used for downstream completion, and provider_meta
    is a dict carrying selected vs actual provider provenance + fallback
    diagnostics.
    """
    from app.providers.errors import (
        RecoverableProviderError,
        classify_provider_response,
    )

    selected_meta = _payload_to_selected_meta(provider_payload)
    selected_mode = (
        provider_payload.get("provider_mode_selected")
        or provider_payload.get("provider_mode")
        or "remote_only"
    )
    local_model_requested = str(
        provider_payload.get("model") or bundle_model or ""
    )

    def _preflight_status_from_error(reason: str | None) -> str:
        if reason is None:
            return "ok"
        if reason == "connect_error":
            return "unreachable"
        if reason == "model_not_found":
            return "model_missing"
        return "ok"

    print(
        f"[sidecar-py] provider_attempt execution_id={execution_id} "
        f"adapter={provider_payload.get('adapter_name')} attempt=1",
        file=sys.stderr,
        flush=True,
    )
    primary_response = _execute_http_provider(
        provider_payload,
        final_prompt=final_prompt,
        bundle_model=bundle_model,
        execution_id=execution_id,
    )
    primary_error = classify_provider_response(primary_response)

    if primary_error is None:
        meta = {
            **selected_meta,
            **_payload_to_actual_meta(provider_payload),
            "fallback_applied": False,
            "fallback_from_adapter_id": None,
            "fallback_to_adapter_id": None,
            "fallback_reason": None,
            "provider_attempt_count": 1,
            "preflight_status": "ok",
            "local_error_reason": None,
            "local_model_requested": local_model_requested if selected_mode in ("local_preferred", "local_only") else None,
        }
        return primary_response, meta

    print(
        f"[sidecar-py] provider_runtime_failure execution_id={execution_id} "
        f"adapter={provider_payload.get('adapter_name')} reason={primary_error.reason}",
        file=sys.stderr,
        flush=True,
    )

    fallback_eligible = (
        isinstance(primary_error, RecoverableProviderError)
        and selected_mode == "local_preferred"
        and fallback_provider_payload is not None
    )
    if not fallback_eligible:
        meta = {
            **selected_meta,
            **_payload_to_actual_meta(provider_payload),
            "fallback_applied": False,
            "fallback_from_adapter_id": None,
            "fallback_to_adapter_id": None,
            "fallback_reason": primary_error.reason,
            "provider_attempt_count": 1,
            "preflight_status": _preflight_status_from_error(primary_error.reason),
            "local_error_reason": primary_error.reason if selected_mode in ("local_preferred", "local_only") else None,
            "local_model_requested": local_model_requested if selected_mode in ("local_preferred", "local_only") else None,
        }
        return primary_response, meta

    print(
        f"[sidecar-py] provider_fallback_start execution_id={execution_id} "
        f"from={provider_payload.get('adapter_name')} "
        f"to={fallback_provider_payload.get('adapter_name')}",
        file=sys.stderr,
        flush=True,
    )
    fallback_response = _execute_http_provider(
        fallback_provider_payload,
        final_prompt=final_prompt,
        bundle_model=bundle_model,
        execution_id=execution_id,
    )
    fallback_error = classify_provider_response(fallback_response)

    if fallback_error is None:
        print(
            f"[sidecar-py] provider_fallback_success execution_id={execution_id} "
            f"actual_adapter={fallback_provider_payload.get('adapter_name')} attempts=2",
            file=sys.stderr,
            flush=True,
        )
        meta = {
            **selected_meta,
            **_payload_to_actual_meta(fallback_provider_payload),
            "fallback_applied": True,
            "fallback_from_adapter_id": provider_payload.get("adapter_id"),
            "fallback_to_adapter_id": fallback_provider_payload.get("adapter_id"),
            "fallback_reason": primary_error.reason,
            "provider_attempt_count": 2,
            "preflight_status": _preflight_status_from_error(primary_error.reason),
            "local_error_reason": primary_error.reason,
            "local_model_requested": local_model_requested,
        }
        return fallback_response, meta

    print(
        f"[sidecar-py] provider_fallback_failure execution_id={execution_id} "
        f"first_reason={primary_error.reason} second_reason={fallback_error.reason}",
        file=sys.stderr,
        flush=True,
    )
    # Return the fallback response so the existing error reporting path runs,
    # but augment its message so operators see both attempts in metadata.
    fallback_response.error_message = (
        f"local_failed:{primary_error.reason}; remote_failed:{fallback_error.reason}; "
        f"{fallback_response.error_message or ''}"
    ).strip()
    meta = {
        **selected_meta,
        **_payload_to_actual_meta(fallback_provider_payload),
        "fallback_applied": True,
        "fallback_from_adapter_id": provider_payload.get("adapter_id"),
        "fallback_to_adapter_id": fallback_provider_payload.get("adapter_id"),
        "fallback_reason": primary_error.reason,
        "provider_attempt_count": 2,
        "preflight_status": _preflight_status_from_error(primary_error.reason),
        "local_error_reason": primary_error.reason,
        "local_model_requested": local_model_requested,
    }
    return fallback_response, meta


def _auth_headers(auth_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json",
    }


async def _request_json(
    method: str,
    api_base: str,
    path: str,
    auth_token: str,
    json_body: dict[str, Any] | None = None,
    timeout: float = 120.0,
) -> dict[str, Any]:
    async with httpx.AsyncClient(base_url=api_base, timeout=timeout) as client:
        if method == "GET":
            response = await client.get(path, headers=_auth_headers(auth_token))
        else:
            response = await client.post(path, headers=_auth_headers(auth_token), json=json_body or {})
    if response.status_code != 200:
        raise RuntimeError(f"API error {response.status_code}: {response.text[:300]}")
    return response.json()


async def _fetch_bundle(api_base: str, auth_token: str, execution_id: int) -> dict[str, Any]:
    # bundleエンドポイントは pending/pending_local のみ受け付ける。
    # 品質ゲート再実行時に一瞬 processing になることがあるため、409ならリトライ。
    last_error = None
    for attempt in range(15):
        try:
            return await _request_json(
                "GET",
                api_base,
                f"/api/worker/executions/{execution_id}/bundle",
                auth_token,
                timeout=60.0,
            )
        except Exception as exc:
            if "409" in str(exc) or "status=" in str(exc):
                last_error = exc
                await asyncio.sleep(2)
                continue
            raise
    raise last_error or RuntimeError(f"Failed to fetch bundle for execution {execution_id}")


async def _complete_execution(
    api_base: str,
    auth_token: str,
    execution_id: int,
    output: str,
    tokens_used: int,
    model_used: str,
    execution_time_ms: int,
    provider_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "output": output,
        "tokens_used": tokens_used,
        "model_used": model_used,
        "execution_time_ms": execution_time_ms,
    }
    if provider_meta is not None:
        body["provider_meta"] = provider_meta
    return await _request_json(
        "POST",
        api_base,
        f"/api/worker/executions/{execution_id}/complete",
        auth_token,
        body,
    )


async def _report_execution_error(
    api_base: str,
    auth_token: str,
    execution_id: int,
    error_message: str,
    execution_time_ms: int,
) -> dict[str, Any]:
    return await _request_json(
        "POST",
        api_base,
        f"/api/worker/executions/{execution_id}/error",
        auth_token,
        {
            "error_message": error_message,
            "execution_time_ms": execution_time_ms,
        },
    )


async def _get_execution_detail(
    api_base: str,
    auth_token: str,
    execution_id: int,
) -> dict[str, Any]:
    return await _request_json(
        "GET",
        api_base,
        f"/api/user/executions/{execution_id}",
        auth_token,
        timeout=60.0,
    )


async def _list_account_executions(
    api_base: str,
    auth_token: str,
    limit: int = 500,
) -> list[dict[str, Any]]:
    data = await _request_json(
        "GET",
        api_base,
        f"/api/user/executions?skip=0&limit={limit}",
        auth_token,
        timeout=60.0,
    )
    return data.get("items", data) if isinstance(data, dict) else data


async def _get_workflow_status(
    api_base: str,
    auth_token: str,
    workflow_execution_id: int,
) -> dict[str, Any]:
    return await _request_json(
        "GET",
        api_base,
        f"/api/user/workflow-executions/{workflow_execution_id}/status",
        auth_token,
        timeout=60.0,
    )


async def _run_existing_execution(
    api_base: str,
    auth_token: str,
    execution_id: int,
    configured_engine_mode: str,
    provider_payload: dict[str, Any] | None = None,
) -> SkillRunResult:
    started_at = time.time()
    runtime_info = preview_runtime_info(configured_engine_mode)
    try:
        bundle = await _fetch_bundle(api_base, auth_token, execution_id)

        # Phase 3.5: external_cli bundles are owned by the desktop Rust
        # runtime, not the sidecar. Skip cleanly so the sidecar worker
        # pool moves on to the next bundle and the same execution stays
        # claimable by the Rust side. We do NOT POST a completion here
        # because that would mark the execution finished from the wrong
        # owner.
        if bundle.get("execution_kind") == "external_cli":
            print(
                f"[sidecar-py] external_cli_delegated execution_id={execution_id} "
                f"adapter={(bundle.get('external_cli_payload') or {}).get('adapter_name')} "
                f"runtime={(bundle.get('external_cli_payload') or {}).get('runtime')}",
                file=sys.stderr,
                flush=True,
            )
            return SkillRunResult(
                status="delegated_to_external_cli_runtime",
                output="",
                model_used=str(bundle.get("model") or ""),
                tokens_used=0,
                duration_ms=int((time.time() - started_at) * 1000),
                error_code=None,
                error_message=None,
                provider_mode="external_cli",
                provider_transport="external_cli",
                provider_adapter=(bundle.get("external_cli_payload") or {}).get("adapter_name") or "external_cli",
                provider_runtime=(bundle.get("external_cli_payload") or {}).get("runtime") or "external_cli",
                provider_impl="rust_runtime",
                token_accounting_source="unavailable",
                auth_key_source=AUTH_KEY_SOURCE_LOCAL_ENV,
            )

        # provider_payload precedence: explicit arg > bundle > None
        if provider_payload is None:
            bundle_payload = bundle.get("provider_payload")
            if isinstance(bundle_payload, dict):
                provider_payload = bundle_payload

        # リーダーステップ（workflow_skill_idなし）のbundleに前ステップ出力が含まれていない場合、
        # バックエンドのDB更新を待って再取得する（並列ステップ完了直後のタイミング問題対策）
        if not bundle.get("workflow_skill_id"):
            _prompt = str(bundle.get("final_prompt") or "")
            for _retry in range(10):
                if "all_step_results" in _prompt and "出力" not in _prompt[:50]:
                    # プロンプト内に結果が含まれている可能性が高い
                    break
                # input_data を確認
                _input_data = bundle.get("input_data")
                if isinstance(_input_data, str):
                    try:
                        _input_data = __import__("json").loads(_input_data)
                    except Exception:
                        _input_data = {}
                if isinstance(_input_data, dict):
                    _results = _input_data.get("all_step_results") or []
                    if _results and any(r.get("output") for r in _results if isinstance(r, dict)):
                        break
                await asyncio.sleep(2)
                bundle = await _fetch_bundle(api_base, auth_token, execution_id)
                _prompt = str(bundle.get("final_prompt") or "")
        runtime_info.auth_key_source = _detect_auth_key_source(bundle)
        # Bundle may also carry a runtime fallback payload (remote retry).
        fallback_provider_payload = None
        if isinstance(bundle.get("fallback_provider_payload"), dict):
            fallback_provider_payload = bundle.get("fallback_provider_payload")
        provider_meta_for_result: dict[str, Any] | None = None
        if provider_payload and provider_payload.get("transport") == "http":
            provider_response, provider_meta_for_result = await _run_with_runtime_fallback(
                provider_payload=provider_payload,
                fallback_provider_payload=fallback_provider_payload,
                final_prompt=str(bundle.get("final_prompt") or ""),
                bundle_model=str(bundle.get("model") or ""),
                execution_id=execution_id,
            )
            elapsed_ms = int((time.time() - started_at) * 1000)
            output = provider_response.output_text
            model_used = provider_response.model
            tokens_used = provider_response.tokens_used or 0
            execution_time_ms = elapsed_ms
            token_accounting_source = (
                provider_response.token_accounting_source or "unavailable"
            )
            provider_error_code = provider_response.error_code
            provider_error_message = provider_response.error_message
            retry_reason = provider_response.retry_reason
            runtime_info.provider_transport = provider_response.provider_transport
            runtime_info.provider_adapter = provider_response.provider_adapter
            runtime_info.provider_runtime = provider_response.provider_runtime
            runtime_info.provider_impl = provider_response.provider_impl
            runtime_info.provider_mode = provider_response.provider_mode
            if provider_response.status != "success":
                await _report_execution_error(
                    api_base,
                    auth_token,
                    execution_id,
                    provider_error_message or "HTTP provider failed",
                    execution_time_ms,
                )
                detail = await _get_execution_detail(api_base, auth_token, execution_id)
                return SkillRunResult(
                    execution_id=execution_id,
                    status=detail.get("status", "error"),
                    output=detail.get("output_data") or "",
                    model_used=detail.get("model_used") or model_used,
                    tokens_used=detail.get("tokens_used") or 0,
                    execution_time_ms=detail.get("execution_time") or execution_time_ms,
                    output_format=detail.get("output_format") or bundle.get("output_format") or "txt",
                    skill_id=detail.get("skill_id"),
                    workflow_execution_id=detail.get("workflow_execution_id"),
                    workflow_skill_id=detail.get("workflow_skill_id"),
                    skill_order=detail.get("skill_order"),
                    skill_name=detail.get("skill_display_name") or detail.get("skill_name"),
                    workflow_name=detail.get("workflow_name"),
                    error_message=detail.get("error_message") or provider_error_message,
                    execution_role=detail.get("execution_role"),
                    configured_engine_mode=runtime_info.configured_engine_mode,
                    effective_engine_mode=runtime_info.effective_engine_mode,
                    provider_mode=runtime_info.provider_mode,
                    provider_transport=runtime_info.provider_transport,
                    provider_adapter=runtime_info.provider_adapter,
                    provider_runtime=runtime_info.provider_runtime,
                    provider_impl=runtime_info.provider_impl,
                    auth_key_source=runtime_info.auth_key_source,
                    observation_source=runtime_info.observation_source,
                    provider_error_code=provider_error_code,
                    provider_error_message=provider_error_message,
                    retry_reason=retry_reason,
                    token_accounting_source=token_accounting_source,
                    provider_meta=provider_meta_for_result,
                )
        elif runtime_info.effective_engine_mode == "cli":
            provider = create_provider("cli")
            provider_response = provider.run(
                ProviderRequest(
                    prompt=str(bundle.get("final_prompt") or ""),
                    model=str(bundle.get("model") or ""),
                    metadata={
                        "execution_id": execution_id,
                        "api_keys": bundle.get("api_keys") or {},
                        "enable_deep_think": bundle.get("enable_deep_think", True),
                    },
                )
            )
            elapsed_ms = int((time.time() - started_at) * 1000)
            output = provider_response.output_text
            model_used = provider_response.model
            tokens_used = provider_response.tokens_used or 0
            execution_time_ms = elapsed_ms
            token_accounting_source = (
                provider_response.token_accounting_source or "unavailable"
            )
            provider_error_code = provider_response.error_code
            provider_error_message = provider_response.error_message
            retry_reason = provider_response.retry_reason
            if provider_response.status != "success":
                await _report_execution_error(
                    api_base,
                    auth_token,
                    execution_id,
                    provider_error_message or "CLI provider failed",
                    execution_time_ms,
                )
                detail = await _get_execution_detail(api_base, auth_token, execution_id)
                return SkillRunResult(
                    execution_id=execution_id,
                    status=detail.get("status", "error"),
                    output=detail.get("output_data") or "",
                    model_used=detail.get("model_used") or model_used,
                    tokens_used=detail.get("tokens_used") or 0,
                    execution_time_ms=detail.get("execution_time") or execution_time_ms,
                    output_format=detail.get("output_format") or bundle.get("output_format") or "txt",
                    skill_id=detail.get("skill_id"),
                    workflow_execution_id=detail.get("workflow_execution_id"),
                    workflow_skill_id=detail.get("workflow_skill_id"),
                    skill_order=detail.get("skill_order"),
                    skill_name=detail.get("skill_display_name") or detail.get("skill_name"),
                    workflow_name=detail.get("workflow_name"),
                    error_message=detail.get("error_message") or provider_error_message,
                    execution_role=detail.get("execution_role"),
                    configured_engine_mode=runtime_info.configured_engine_mode,
                    effective_engine_mode=runtime_info.effective_engine_mode,
                    provider_mode=runtime_info.provider_mode,
                    provider_transport=provider_response.provider_transport,
                    provider_adapter=provider_response.provider_adapter,
                    provider_runtime=provider_response.provider_runtime,
                    provider_impl=provider_response.provider_impl,
                    auth_key_source=runtime_info.auth_key_source,
                    observation_source=runtime_info.observation_source,
                    provider_error_code=provider_error_code,
                    provider_error_message=provider_error_message,
                    retry_reason=retry_reason,
                    token_accounting_source=token_accounting_source,
                )
        else:
            result = await execute_bundle(bundle)
            output = result.output
            model_used = result.model_used
            tokens_used = result.tokens_used
            execution_time_ms = result.execution_time_ms
            token_accounting_source = result.token_accounting_source
            provider_error_code = None
            provider_error_message = None
            retry_reason = None
        await _complete_execution(
            api_base,
            auth_token,
            execution_id,
            output,
            tokens_used,
            model_used,
            execution_time_ms,
            provider_meta=provider_meta_for_result,
        )
        detail = await _get_execution_detail(api_base, auth_token, execution_id)
        return SkillRunResult(
            execution_id=execution_id,
            status=detail.get("status", "success"),
            output=detail.get("output_data") or output,
            model_used=detail.get("model_used") or model_used,
            tokens_used=detail.get("tokens_used") or tokens_used,
            execution_time_ms=detail.get("execution_time") or execution_time_ms,
            output_format=detail.get("output_format") or bundle.get("output_format") or "txt",
            skill_id=detail.get("skill_id"),
            workflow_execution_id=detail.get("workflow_execution_id"),
            workflow_skill_id=detail.get("workflow_skill_id"),
            skill_order=detail.get("skill_order"),
            skill_name=detail.get("skill_display_name") or detail.get("skill_name"),
            workflow_name=detail.get("workflow_name"),
            error_message=detail.get("error_message"),
            execution_role=detail.get("execution_role"),
            configured_engine_mode=runtime_info.configured_engine_mode,
            effective_engine_mode=runtime_info.effective_engine_mode,
            provider_mode=runtime_info.provider_mode,
            provider_transport=runtime_info.provider_transport,
            provider_adapter=runtime_info.provider_adapter,
            provider_runtime=runtime_info.provider_runtime,
            provider_impl=runtime_info.provider_impl,
            auth_key_source=runtime_info.auth_key_source,
            observation_source=runtime_info.observation_source,
            provider_error_code=provider_error_code,
            provider_error_message=provider_error_message,
            retry_reason=retry_reason,
            token_accounting_source=token_accounting_source,
            provider_meta=provider_meta_for_result,
        )
    except Exception as exc:
        elapsed_ms = int((time.time() - started_at) * 1000)
        provider_error_code, retry_reason = _classify_provider_failure(str(exc))
        try:
            await _report_execution_error(
                api_base,
                auth_token,
                execution_id,
                str(exc),
                elapsed_ms,
            )
        except Exception:
            pass
        detail = await _get_execution_detail(api_base, auth_token, execution_id)
        return SkillRunResult(
            execution_id=execution_id,
            status=detail.get("status", "error"),
            output=detail.get("output_data") or "",
            model_used=detail.get("model_used") or "",
            tokens_used=detail.get("tokens_used") or 0,
            execution_time_ms=detail.get("execution_time") or elapsed_ms,
            output_format=detail.get("output_format") or "txt",
            skill_id=detail.get("skill_id"),
            workflow_execution_id=detail.get("workflow_execution_id"),
            workflow_skill_id=detail.get("workflow_skill_id"),
            skill_order=detail.get("skill_order"),
            skill_name=detail.get("skill_display_name") or detail.get("skill_name"),
            workflow_name=detail.get("workflow_name"),
            error_message=detail.get("error_message") or str(exc),
            execution_role=detail.get("execution_role"),
            configured_engine_mode=configured_engine_mode,
            effective_engine_mode=runtime_info.effective_engine_mode,
            provider_mode=runtime_info.provider_mode,
            provider_transport=runtime_info.provider_transport,
            provider_adapter=runtime_info.provider_adapter,
            provider_runtime=runtime_info.provider_runtime,
            provider_impl=runtime_info.provider_impl,
            auth_key_source=runtime_info.auth_key_source,
            observation_source=OBSERVATION_SOURCE_ENGINE_ORIGIN_BATCH,
            provider_error_code=provider_error_code,
            provider_error_message=str(exc),
            retry_reason=retry_reason,
            token_accounting_source="unavailable",
        )


async def run_skill_execution(
    *,
    api_base: str,
    auth_token: str,
    skill_id: int,
    input_data: dict[str, Any],
    output_format: str = "txt",
    enable_deep_think: bool | None = None,
    configured_engine_mode: str = "api_key",
) -> SkillRunResult:
    body: dict[str, Any] = {
        "skill_id": skill_id,
        "input_data": input_data,
        "output_format": output_format,
    }
    if enable_deep_think is not None:
        body["enable_deep_think"] = enable_deep_think
    response = await _request_json("POST", api_base, "/api/execute", auth_token, body)
    return await _run_existing_execution(
        api_base,
        auth_token,
        int(response["execution_id"]),
        configured_engine_mode,
    )


async def run_workflow_execution(
    *,
    api_base: str,
    auth_token: str,
    workflow_id: int,
    global_input_data: dict[str, Any],
    per_skill_input: dict[str, Any] | None = None,
    output_format: str = "txt",
    poll_interval_seconds: float = 0.25,
    idle_limit: int = 120,
    configured_engine_mode: str = "api_key",
) -> WorkflowRunResult:
    runtime_info = preview_runtime_info(configured_engine_mode)
    response = await _request_json(
        "POST",
        api_base,
        "/api/execute/workflow",
        auth_token,
        {
            "workflow_id": workflow_id,
            "global_input_data": global_input_data,
            "per_skill_input": per_skill_input or {},
            "output_format": output_format,
        },
    )
    workflow_execution_id = int(response["workflow_execution_id"])
    queue: list[int] = [int(execution_id) for execution_id in response.get("execution_ids", [])]
    processed: set[int] = set()
    in_flight: set[int] = set()  # fetch_bundle 済み (processing に遷移済み) の ID
    steps: list[dict[str, Any]] = []
    idle_rounds = 0

    while True:
        if queue:
            execution_id = queue.pop(0)
            if execution_id in processed or execution_id in in_flight:
                continue
            in_flight.add(execution_id)
            outcome = await _run_existing_execution(
                api_base,
                auth_token,
                execution_id,
                configured_engine_mode,
            )
            in_flight.discard(execution_id)
            processed.add(execution_id)
            steps.append(outcome.as_payload())
            idle_rounds = 0
            continue

        executions = await _list_account_executions(api_base, auth_token)
        workflow_executions = [
            execution
            for execution in executions
            if execution.get("workflow_execution_id") == workflow_execution_id
        ]
        # pending_local のみ対象。processing は既に _fetch_bundle で遷移済みなので
        # 再取得すると 409 になる。
        next_ids = sorted(
            execution["id"]
            for execution in workflow_executions
            if execution.get("id") not in processed
            and execution.get("id") not in in_flight
            and execution.get("status") == "pending_local"
        )
        if next_ids:
            queue.extend(next_ids)
            continue

        workflow_status = await _get_workflow_status(api_base, auth_token, workflow_execution_id)
        if workflow_status.get("status") in {"success", "error", "cancelled"}:
            break

        idle_rounds += 1
        if idle_rounds >= idle_limit:
            raise RuntimeError(
                f"workflow {workflow_execution_id} did not reach terminal state within idle limit"
            )
        await asyncio.sleep(poll_interval_seconds)

    executions = await _list_account_executions(api_base, auth_token)
    workflow_executions = [
        execution
        for execution in executions
        if execution.get("workflow_execution_id") == workflow_execution_id
    ]
    normal_execs = [execution for execution in workflow_executions if not execution.get("execution_role")]
    leader_execution = next(
        (execution for execution in normal_execs if execution.get("workflow_skill_id") is None),
        None,
    )
    workflow_status = await _get_workflow_status(api_base, auth_token, workflow_execution_id)

    return WorkflowRunResult(
        workflow_execution_id=workflow_execution_id,
        status=workflow_status.get("status", "success"),
        execution_ids=[execution["id"] for execution in workflow_executions],
        leader_execution_id=leader_execution.get("id") if leader_execution else None,
        output=(leader_execution or {}).get("output_data") or "",
        error_message=workflow_status.get("error_message"),
        steps=steps,
        configured_engine_mode=configured_engine_mode,
        effective_engine_mode=runtime_info.effective_engine_mode,
        provider_mode=runtime_info.provider_mode,
        provider_transport=runtime_info.provider_transport,
        provider_adapter=runtime_info.provider_adapter,
        provider_runtime=runtime_info.provider_runtime,
        provider_impl=runtime_info.provider_impl,
        auth_key_source=(
            steps[0]["auth_key_source"]
            if steps and steps[0].get("auth_key_source")
            else runtime_info.auth_key_source
        ),
        observation_source=OBSERVATION_SOURCE_ENGINE_ORIGIN_BATCH,
        provider_error_code=next(
            (step.get("provider_error_code") for step in reversed(steps) if step.get("provider_error_code")),
            None,
        ),
        provider_error_message=next(
            (
                step.get("provider_error_message")
                for step in reversed(steps)
                if step.get("provider_error_message")
            ),
            None,
        ),
        retry_reason=next(
            (step.get("retry_reason") for step in reversed(steps) if step.get("retry_reason")),
            None,
        ),
        token_accounting_source=(
            steps[0]["token_accounting_source"]
            if steps and steps[0].get("token_accounting_source")
            else "unavailable"
        ),
    )
