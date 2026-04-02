from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .base import LLMProvider, ProviderRequest, ProviderResponse

REPO_ROOT = Path(__file__).resolve().parents[3]
# `provider_mode` stays semantic (`cli`) while these fields capture implementation detail.
# Replace only the detail fields when the internal execution target changes.
DEFAULT_CLI_PROVIDER_IMPL = "local_worker.provider_adapter"
DEFAULT_CLI_PROVIDER_ADAPTER = "local_worker"
DEFAULT_CLI_PROVIDER_RUNTIME = "python"
DEFAULT_CLI_PROVIDER_TRANSPORT = "subprocess"
PACKAGED_CLI_PROVIDER_BINARY_ID = "ppt-provider-adapter"


@dataclass(frozen=True, slots=True)
class CliInvocation:
    argv: list[str]
    env: dict[str, str]
    cwd: str | None
    provider_transport: str
    provider_adapter: str
    provider_runtime: str
    provider_impl: str


def _canonicalize_cli_error(raw_kind: str, raw_message: str) -> tuple[str, str]:
    message = raw_message.lower()
    if raw_kind == "timeout":
        return "cli_provider_timeout", "provider_timeout"
    if raw_kind == "connection_error":
        return "cli_provider_transport_error", "transport_error"
    if raw_kind == "unsupported_model":
        return "cli_provider_model_unsupported", "local_environment_error"
    if raw_kind == "missing_credentials":
        return "cli_provider_authentication_failed", "local_environment_error"
    if raw_kind == "dependency_missing":
        return "cli_provider_dependency_missing", "local_environment_error"
    if raw_kind == "parse_failure":
        return "cli_provider_output_malformed", "malformed_output"
    if "rate limit" in message or "resource exhausted" in message:
        return "cli_provider_rate_limited", "provider_rate_limit"
    if "timeout" in message or "timed out" in message:
        return "cli_provider_timeout", "provider_timeout"
    if "connection" in message or "unreachable" in message:
        return "cli_provider_transport_error", "transport_error"
    return "cli_provider_local_environment_error", "local_environment_error"


def _env_or_default(name: str, default: str) -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


def resolve_cli_invocation() -> CliInvocation:
    # Naming contract:
    # - keep `provider_mode=cli` while the semantic path remains CLI
    # - change `provider_transport` only when the reachability method changes
    # - change `provider_adapter` only when the intermediary layer changes
    # - change `provider_runtime` only when the execution environment changes
    # - change `provider_impl` when the concrete target changes
    command = os.getenv("PPT_CLI_PROVIDER_COMMAND")
    binary_path = os.getenv("PPT_CLI_PROVIDER_BINARY_PATH")
    provider_runtime = _env_or_default("PPT_CLI_PROVIDER_RUNTIME", DEFAULT_CLI_PROVIDER_RUNTIME)
    provider_adapter = _env_or_default("PPT_CLI_PROVIDER_ADAPTER", DEFAULT_CLI_PROVIDER_ADAPTER)
    provider_impl = _env_or_default("PPT_CLI_PROVIDER_IMPL", DEFAULT_CLI_PROVIDER_IMPL)
    env = os.environ.copy()

    if command:
        return CliInvocation(
            argv=shlex.split(command),
            env=env,
            cwd=None if provider_runtime == "binary" else str(REPO_ROOT),
            provider_transport=DEFAULT_CLI_PROVIDER_TRANSPORT,
            provider_adapter=provider_adapter,
            provider_runtime=provider_runtime,
            provider_impl=provider_impl,
        )

    if binary_path:
        return CliInvocation(
            argv=[binary_path],
            env=env,
            cwd=None,
            provider_transport=DEFAULT_CLI_PROVIDER_TRANSPORT,
            provider_adapter=provider_adapter,
            provider_runtime="binary",
            provider_impl=_env_or_default("PPT_CLI_PROVIDER_IMPL", PACKAGED_CLI_PROVIDER_BINARY_ID),
        )

    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return CliInvocation(
        argv=[sys.executable, "-m", "local_worker.provider_adapter"],
        env=env,
        cwd=str(REPO_ROOT),
        provider_transport=DEFAULT_CLI_PROVIDER_TRANSPORT,
        provider_adapter=DEFAULT_CLI_PROVIDER_ADAPTER,
        provider_runtime=DEFAULT_CLI_PROVIDER_RUNTIME,
        provider_impl=DEFAULT_CLI_PROVIDER_IMPL,
    )


class CliProvider(LLMProvider):
    mode = "cli"

    def run(self, request: ProviderRequest) -> ProviderResponse:
        payload = {
            "prompt": request.prompt,
            "model": request.model,
            "enable_deep_think": request.metadata.get("enable_deep_think", True),
            "api_keys": request.metadata.get("api_keys") or {},
            "model_override": request.metadata.get("model_override"),
        }
        invocation = resolve_cli_invocation()
        timeout_seconds = float(os.getenv("PPT_CLI_PROVIDER_TIMEOUT_SECONDS", "120"))

        try:
            completed = subprocess.run(
                invocation.argv,
                input=json.dumps(payload, ensure_ascii=True),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                cwd=invocation.cwd,
                env=invocation.env,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return ProviderResponse(
                status="error",
                output_text="",
                provider_mode=self.mode,
                provider_transport=invocation.provider_transport,
                provider_adapter=invocation.provider_adapter,
                provider_runtime=invocation.provider_runtime,
                provider_impl=invocation.provider_impl,
                model=request.model,
                tokens_used=0,
                token_accounting_source="unavailable",
                error_code="cli_provider_timeout",
                error_message=str(exc),
                retry_reason="provider_timeout",
            )
        except OSError as exc:
            return ProviderResponse(
                status="error",
                output_text="",
                provider_mode=self.mode,
                provider_transport=invocation.provider_transport,
                provider_adapter=invocation.provider_adapter,
                provider_runtime=invocation.provider_runtime,
                provider_impl=invocation.provider_impl,
                model=request.model,
                tokens_used=0,
                token_accounting_source="unavailable",
                error_code="cli_provider_spawn_failed",
                error_message=str(exc),
                retry_reason="local_environment_error",
            )

        raw_stdout = completed.stdout.strip()
        if not raw_stdout:
            error_code, retry_reason = _canonicalize_cli_error(
                "parse_failure",
                completed.stderr.strip() or "empty stdout",
            )
            return ProviderResponse(
                status="error",
                output_text="",
                provider_mode=self.mode,
                provider_transport=invocation.provider_transport,
                provider_adapter=invocation.provider_adapter,
                provider_runtime=invocation.provider_runtime,
                provider_impl=invocation.provider_impl,
                model=request.model,
                tokens_used=0,
                token_accounting_source="unavailable",
                error_code=error_code,
                error_message=completed.stderr.strip() or "empty stdout",
                retry_reason=retry_reason,
            )

        try:
            result = json.loads(raw_stdout)
        except json.JSONDecodeError as exc:
            error_code, retry_reason = _canonicalize_cli_error("parse_failure", str(exc))
            return ProviderResponse(
                status="error",
                output_text="",
                provider_mode=self.mode,
                provider_transport=invocation.provider_transport,
                provider_adapter=invocation.provider_adapter,
                provider_runtime=invocation.provider_runtime,
                provider_impl=invocation.provider_impl,
                model=request.model,
                tokens_used=0,
                token_accounting_source="unavailable",
                error_code=error_code,
                error_message=f"{exc}: {raw_stdout[:300]}",
                retry_reason=retry_reason,
            )

        if result.get("status") == "success":
            return ProviderResponse(
                status="success",
                output_text=str(result.get("output") or ""),
                provider_mode=self.mode,
                provider_transport=invocation.provider_transport,
                provider_adapter=invocation.provider_adapter,
                provider_runtime=invocation.provider_runtime,
                provider_impl=invocation.provider_impl,
                model=str(result.get("model_used") or request.model),
                tokens_used=int(result.get("tokens_used") or 0),
                token_accounting_source=str(result.get("token_accounting_source") or "unavailable"),
                error_code=None,
                error_message=None,
                retry_reason=None,
            )

        raw_error_kind = str(result.get("raw_error_kind") or "unknown_error")
        raw_error_message = str(
            result.get("raw_error_message")
            or completed.stderr.strip()
            or "CLI provider failed"
        )
        error_code, retry_reason = _canonicalize_cli_error(raw_error_kind, raw_error_message)
        return ProviderResponse(
            status="error",
            output_text="",
            provider_mode=self.mode,
            provider_transport=invocation.provider_transport,
            provider_adapter=invocation.provider_adapter,
            provider_runtime=invocation.provider_runtime,
            provider_impl=invocation.provider_impl,
            model=request.model,
            tokens_used=0,
            token_accounting_source="unavailable",
            error_code=error_code,
            error_message=raw_error_message,
            retry_reason=retry_reason,
        )
