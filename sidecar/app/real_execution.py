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
    return await _request_json(
        "GET",
        api_base,
        f"/api/worker/executions/{execution_id}/bundle",
        auth_token,
        timeout=60.0,
    )


async def _complete_execution(
    api_base: str,
    auth_token: str,
    execution_id: int,
    output: str,
    tokens_used: int,
    model_used: str,
    execution_time_ms: int,
) -> dict[str, Any]:
    return await _request_json(
        "POST",
        api_base,
        f"/api/worker/executions/{execution_id}/complete",
        auth_token,
        {
            "output": output,
            "tokens_used": tokens_used,
            "model_used": model_used,
            "execution_time_ms": execution_time_ms,
        },
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
) -> SkillRunResult:
    started_at = time.time()
    runtime_info = preview_runtime_info(configured_engine_mode)
    try:
        bundle = await _fetch_bundle(api_base, auth_token, execution_id)
        runtime_info.auth_key_source = _detect_auth_key_source(bundle)
        if runtime_info.effective_engine_mode == "cli":
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
    steps: list[dict[str, Any]] = []
    idle_rounds = 0

    while True:
        if queue:
            execution_id = queue.pop(0)
            if execution_id in processed:
                continue
            outcome = await _run_existing_execution(
                api_base,
                auth_token,
                execution_id,
                configured_engine_mode,
            )
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
        next_ids = sorted(
            execution["id"]
            for execution in workflow_executions
            if execution.get("id") not in processed
            and execution.get("status") in {"pending_local", "processing"}
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
