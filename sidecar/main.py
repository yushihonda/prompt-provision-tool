from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from typing import Any

from app.execution import RetryPolicy, RetryReason
from app.providers import ProviderRequest, ProviderResponse, create_provider
from app.real_execution import (
    OBSERVATION_SOURCE_ENGINE_ORIGIN_BATCH,
    preview_runtime_info,
    run_skill_execution,
    run_workflow_execution,
)
from app.security import PromptProtectionPolicy


@dataclass(slots=True)
class RequestEnvelope:
    request_id: int
    command: str
    payload: dict[str, Any]


@dataclass(slots=True)
class EventDraft:
    event_key: str
    event_type: str
    node_id: str | None
    attempt_no: int
    correlation_id: str
    causation_key: str | None
    root_event_key: str | None
    trigger_event_key: str | None
    origin_layer: str
    event_idempotency_key: str
    payload_json: dict[str, Any]

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class NodeEventState:
    node_id: str
    attempt_no: int
    last_event_key: str | None = None


class EventBatchBuilder:
    def __init__(self, correlation_id: str, command_id: str) -> None:
        self.correlation_id = correlation_id
        self.command_id = command_id
        self.root_event_key: str | None = None
        self.sequence = 0
        self._events: list[EventDraft] = []
        self._node_states: dict[tuple[str, int], NodeEventState] = {}

    def _next_event_key(self, event_type: str) -> str:
        event_key = f"{event_type}:{self.sequence}"
        self.sequence += 1
        return event_key

    def _node_state(self, node_id: str, attempt_no: int) -> NodeEventState:
        key = (node_id, attempt_no)
        if key not in self._node_states:
            self._node_states[key] = NodeEventState(node_id=node_id, attempt_no=attempt_no)
        return self._node_states[key]

    def append_event(
        self,
        event_type: str,
        *,
        node_id: str | None = None,
        attempt_no: int = 0,
        origin_layer: str = "engine",
        payload_json: dict[str, Any] | None = None,
        causation_key: str | None = None,
        root_event_key: str | None = None,
        trigger_event_key: str | None = None,
        event_idempotency_key: str | None = None,
    ) -> EventDraft:
        event_key = self._next_event_key(event_type)
        node_state = self._node_state(node_id, attempt_no) if node_id is not None else None
        resolved_causation_key = causation_key if causation_key is not None else (
            node_state.last_event_key if node_state is not None else None
        )
        resolved_trigger_key = (
            trigger_event_key if trigger_event_key is not None else resolved_causation_key
        )
        resolved_root_key = root_event_key if root_event_key is not None else self.root_event_key
        payload = {
            "command_id": self.command_id,
            **(payload_json or {}),
        }
        draft = EventDraft(
            event_key=event_key,
            event_type=event_type,
            node_id=node_id,
            attempt_no=attempt_no,
            correlation_id=self.correlation_id,
            causation_key=resolved_causation_key,
            root_event_key=resolved_root_key,
            trigger_event_key=resolved_trigger_key,
            origin_layer=origin_layer,
            event_idempotency_key=event_idempotency_key or event_key,
            payload_json=payload,
        )
        self._events.append(draft)
        if self.root_event_key is None:
            self.root_event_key = event_key
        if node_state is not None:
            node_state.last_event_key = event_key
        return draft

    def export(self) -> list[dict[str, Any]]:
        return [event.as_payload() for event in self._events]


def parse_retry_reason(value: Any) -> RetryReason | None:
    if value is None:
        return None
    try:
        return RetryReason(str(value))
    except ValueError:
        return RetryReason.LOCAL_ENVIRONMENT_ERROR


def retry_reason_from_response(response: ProviderResponse) -> RetryReason | None:
    if response.status == "success":
        return None
    return (
        parse_retry_reason(response.retry_reason)
        or parse_retry_reason(response.error_code)
        or RetryReason.LOCAL_ENVIRONMENT_ERROR
    )


class SidecarApp:
    def __init__(self) -> None:
        self.started_at = time.time()
        self.pid = os.getpid()
        self.prompt_policy = PromptProtectionPolicy()
        self.retry_policy = RetryPolicy()

    def handle(self, envelope: RequestEnvelope) -> dict[str, Any]:
        handlers = {
            "ping": self._ping,
            "health": self._health,
            "run_demo_workflow": self._run_demo_workflow,
            "run_skill_execution": self._run_skill_execution,
            "run_workflow_execution": self._run_workflow_execution,
            "shutdown": self._shutdown,
        }

        if envelope.command not in handlers:
            raise ValueError(f"unsupported command: {envelope.command}")

        payload = dict(envelope.payload)
        payload.setdefault("request_id", envelope.request_id)
        return handlers[envelope.command](payload)

    def _ping(self, _: dict[str, Any]) -> dict[str, Any]:
        return {"status": "ok", "message": "pong", "pid": self.pid}

    def _health(self, _: dict[str, Any]) -> dict[str, Any]:
        uptime_seconds = round(time.time() - self.started_at, 3)
        return {
            "status": "ok",
            "pid": self.pid,
            "uptime_seconds": uptime_seconds,
            "commands": [
                "ping",
                "health",
                "run_demo_workflow",
                "run_skill_execution",
                "run_workflow_execution",
                "shutdown",
            ],
            "retry_taxonomy": [reason.value for reason in RetryReason],
            "memory_only_decryption": self.prompt_policy.memory_only_decryption,
        }

    def _append_retry_chain(
        self,
        builder: EventBatchBuilder,
        *,
        command_id: str,
        node_id: str,
        attempt_no: int,
        configured_engine_mode: str,
        effective_engine_mode: str,
        provider_mode: str,
        provider_transport: str,
        provider_adapter: str,
        provider_runtime: str,
        provider_impl: str,
        auth_key_source: str,
        model: str,
        token_accounting_source: str,
        status: str,
        provider_output: str,
        error_code: str | None,
        retry_reason: str | None,
        error_message: str | None,
        started_from: str,
    ) -> EventDraft:
        provider_started = builder.append_event(
            "provider_request_started",
            node_id=node_id,
            attempt_no=attempt_no,
            origin_layer="provider",
            causation_key=started_from,
            trigger_event_key=started_from,
            event_idempotency_key=f"{command_id}:{node_id}:provider_request_started:{attempt_no}",
            payload_json={
                "configured_engine_mode": configured_engine_mode,
                "effective_engine_mode": effective_engine_mode,
                "provider_mode": provider_mode,
                "provider_transport": provider_transport,
                "provider_adapter": provider_adapter,
                "provider_runtime": provider_runtime,
                "provider_impl": provider_impl,
                "auth_key_source": auth_key_source,
                "model": model,
                "token_accounting_source": token_accounting_source,
                "observation_source": OBSERVATION_SOURCE_ENGINE_ORIGIN_BATCH,
            },
        )
        provider_finished = builder.append_event(
            "provider_request_finished",
            node_id=node_id,
            attempt_no=attempt_no,
            origin_layer="provider",
            causation_key=provider_started.event_key,
            trigger_event_key=provider_started.event_key,
            event_idempotency_key=f"{command_id}:{node_id}:provider_request_finished:{attempt_no}",
            payload_json={
                "configured_engine_mode": configured_engine_mode,
                "effective_engine_mode": effective_engine_mode,
                "status": status,
                "provider_output": provider_output,
                "provider_mode": provider_mode,
                "provider_transport": provider_transport,
                "provider_adapter": provider_adapter,
                "provider_runtime": provider_runtime,
                "provider_impl": provider_impl,
                "auth_key_source": auth_key_source,
                "model": model,
                "token_accounting_source": token_accounting_source,
                "error_code": error_code,
                "provider_error_code": error_code,
                "retry_reason": retry_reason,
                "error_message": error_message,
                "observation_source": OBSERVATION_SOURCE_ENGINE_ORIGIN_BATCH,
            },
        )
        parsed_retry_reason = parse_retry_reason(retry_reason) if status != "success" else None
        if parsed_retry_reason is None:
            retry_payload = {
                "should_retry": False,
                "layer": "transport",
                "reason": None,
                "next_delay_seconds": 0.0,
                "observation_source": OBSERVATION_SOURCE_ENGINE_ORIGIN_BATCH,
            }
        else:
            retry_decision = self.retry_policy.decide(parsed_retry_reason, attempt_no)
            retry_payload = {
                "should_retry": retry_decision.should_retry,
                "layer": retry_decision.layer.value,
                "reason": retry_decision.reason.value,
                "next_delay_seconds": retry_decision.next_delay_seconds,
                "observation_source": OBSERVATION_SOURCE_ENGINE_ORIGIN_BATCH,
            }
        retry_payload.update(
            {
                "configured_engine_mode": configured_engine_mode,
                "effective_engine_mode": effective_engine_mode,
                "provider_mode": provider_mode,
                "provider_transport": provider_transport,
                "provider_adapter": provider_adapter,
                "provider_runtime": provider_runtime,
                "provider_impl": provider_impl,
                "auth_key_source": auth_key_source,
                "token_accounting_source": token_accounting_source,
                "error_code": error_code,
                "provider_error_code": error_code,
            }
        )
        return builder.append_event(
            "retry_decision_made",
            node_id=node_id,
            attempt_no=attempt_no,
            origin_layer="retry",
            causation_key=provider_finished.event_key,
            trigger_event_key=provider_finished.event_key,
            event_idempotency_key=f"{command_id}:{node_id}:retry_decision_made:{attempt_no}",
            payload_json=retry_payload,
        )

    def _run_skill_execution(self, payload: dict[str, Any]) -> dict[str, Any]:
        correlation_id = str(payload.get("correlation_id") or f"sidecar-corr-{payload['request_id']}")
        command_id = str(payload.get("command_id") or f"sidecar-request-{payload['request_id']}")
        api_base = str(payload["api_base"])
        auth_token = str(payload["auth_token"])
        configured_engine_mode = str(payload.get("configured_engine_mode") or "api_key")
        skill_id = int(payload["skill_id"])
        skill_name = str(payload.get("skill_name") or f"Skill {skill_id}")
        output_format = str(payload.get("output_format") or "txt")
        input_data = dict(payload.get("input_data") or {})
        enable_deep_think = payload.get("enable_deep_think")
        preview_runtime = preview_runtime_info(configured_engine_mode)
        builder = EventBatchBuilder(correlation_id=correlation_id, command_id=command_id)
        workflow_created = builder.append_event(
            "workflow_run_created",
            attempt_no=0,
            origin_layer="engine",
            event_idempotency_key=f"{command_id}:workflow_run_created",
            payload_json={
                "workflow_name": skill_name,
                "skill_id": skill_id,
                "kind": "skill",
                "configured_engine_mode": configured_engine_mode,
                "effective_engine_mode": preview_runtime.effective_engine_mode,
                "provider_mode": preview_runtime.provider_mode,
                "provider_transport": preview_runtime.provider_transport,
                "provider_adapter": preview_runtime.provider_adapter,
                "provider_runtime": preview_runtime.provider_runtime,
                "provider_impl": preview_runtime.provider_impl,
                "auth_key_source": preview_runtime.auth_key_source,
                "observation_source": OBSERVATION_SOURCE_ENGINE_ORIGIN_BATCH,
            },
        )
        outcome = asyncio.run(
            run_skill_execution(
                api_base=api_base,
                auth_token=auth_token,
                skill_id=skill_id,
                input_data=input_data,
                output_format=output_format,
                enable_deep_think=enable_deep_think if isinstance(enable_deep_think, bool) else None,
                configured_engine_mode=configured_engine_mode,
            )
        )
        node_id = f"execution:{outcome.execution_id}"
        node_started = builder.append_event(
            "node_execution_started",
            node_id=node_id,
            attempt_no=1,
            origin_layer="engine",
            causation_key=workflow_created.event_key,
            trigger_event_key=workflow_created.event_key,
            event_idempotency_key=f"{command_id}:{node_id}:node_execution_started:1",
            payload_json={
                "execution_id": outcome.execution_id,
                "skill_id": outcome.skill_id or skill_id,
                "skill_name": outcome.skill_name or skill_name,
                "configured_engine_mode": outcome.configured_engine_mode,
                "effective_engine_mode": outcome.effective_engine_mode,
                "provider_mode": outcome.provider_mode,
                "provider_transport": outcome.provider_transport,
                "provider_adapter": outcome.provider_adapter,
                "provider_runtime": outcome.provider_runtime,
                "provider_impl": outcome.provider_impl,
                "auth_key_source": outcome.auth_key_source,
                "observation_source": outcome.observation_source,
            },
        )
        retry_event = self._append_retry_chain(
            builder,
            command_id=command_id,
            node_id=node_id,
            attempt_no=1,
            configured_engine_mode=outcome.configured_engine_mode,
            effective_engine_mode=outcome.effective_engine_mode,
            provider_mode=outcome.provider_mode,
            provider_transport=outcome.provider_transport,
            provider_adapter=outcome.provider_adapter,
            provider_runtime=outcome.provider_runtime,
            provider_impl=outcome.provider_impl,
            auth_key_source=outcome.auth_key_source,
            model=outcome.model_used or "",
            token_accounting_source=outcome.token_accounting_source,
            status=outcome.status,
            provider_output=outcome.output,
            error_code=outcome.provider_error_code,
            retry_reason=outcome.retry_reason,
            error_message=outcome.provider_error_message or outcome.error_message,
            started_from=node_started.event_key,
        )
        node_finished = builder.append_event(
            "node_execution_finished",
            node_id=node_id,
            attempt_no=1,
            origin_layer="engine",
            causation_key=retry_event.event_key,
            trigger_event_key=retry_event.event_key,
            event_idempotency_key=f"{command_id}:{node_id}:node_execution_finished:1",
            payload_json={
                "status": outcome.status,
                "execution_id": outcome.execution_id,
                "error_message": outcome.error_message,
                "configured_engine_mode": outcome.configured_engine_mode,
                "effective_engine_mode": outcome.effective_engine_mode,
                "provider_mode": outcome.provider_mode,
                "provider_transport": outcome.provider_transport,
                "provider_adapter": outcome.provider_adapter,
                "provider_runtime": outcome.provider_runtime,
                "provider_impl": outcome.provider_impl,
                "auth_key_source": outcome.auth_key_source,
                "token_accounting_source": outcome.token_accounting_source,
                "provider_error_code": outcome.provider_error_code,
                "retry_reason": outcome.retry_reason,
                "observation_source": outcome.observation_source,
            },
        )
        builder.append_event(
            "workflow_run_finished",
            attempt_no=0,
            origin_layer="engine",
            causation_key=node_finished.event_key,
            trigger_event_key=node_finished.event_key,
            event_idempotency_key=f"{command_id}:workflow_run_finished",
            payload_json={
                "status": outcome.status,
                "execution_id": outcome.execution_id,
                "configured_engine_mode": outcome.configured_engine_mode,
                "effective_engine_mode": outcome.effective_engine_mode,
                "provider_mode": outcome.provider_mode,
                "provider_transport": outcome.provider_transport,
                "provider_adapter": outcome.provider_adapter,
                "provider_runtime": outcome.provider_runtime,
                "provider_impl": outcome.provider_impl,
                "auth_key_source": outcome.auth_key_source,
                "token_accounting_source": outcome.token_accounting_source,
                "provider_error_code": outcome.provider_error_code,
                "retry_reason": outcome.retry_reason,
                "observation_source": outcome.observation_source,
            },
        )
        return {
            "status": outcome.status,
            "execution_id": outcome.execution_id,
            "output": outcome.output,
            "model_used": outcome.model_used,
            "tokens_used": outcome.tokens_used,
            "execution_time_ms": outcome.execution_time_ms,
            "output_format": outcome.output_format,
            "error_message": outcome.error_message,
            "configured_engine_mode": outcome.configured_engine_mode,
            "effective_engine_mode": outcome.effective_engine_mode,
            "provider_mode": outcome.provider_mode,
            "provider_transport": outcome.provider_transport,
            "provider_adapter": outcome.provider_adapter,
            "provider_runtime": outcome.provider_runtime,
            "provider_impl": outcome.provider_impl,
            "auth_key_source": outcome.auth_key_source,
            "token_accounting_source": outcome.token_accounting_source,
            "provider_error_code": outcome.provider_error_code,
            "provider_error_message": outcome.provider_error_message,
            "retry_reason": outcome.retry_reason,
            "observation_source": outcome.observation_source,
            "events": builder.export(),
        }

    def _run_workflow_execution(self, payload: dict[str, Any]) -> dict[str, Any]:
        correlation_id = str(payload.get("correlation_id") or f"sidecar-corr-{payload['request_id']}")
        command_id = str(payload.get("command_id") or f"sidecar-request-{payload['request_id']}")
        api_base = str(payload["api_base"])
        auth_token = str(payload["auth_token"])
        configured_engine_mode = str(payload.get("configured_engine_mode") or "api_key")
        workflow_id = int(payload["workflow_id"])
        workflow_name = str(payload.get("workflow_name") or f"Workflow {workflow_id}")
        output_format = str(payload.get("output_format") or "txt")
        global_input_data = dict(payload.get("global_input_data") or {})
        per_skill_input = dict(payload.get("per_skill_input") or {})
        preview_runtime = preview_runtime_info(configured_engine_mode)
        builder = EventBatchBuilder(correlation_id=correlation_id, command_id=command_id)
        workflow_created = builder.append_event(
            "workflow_run_created",
            attempt_no=0,
            origin_layer="engine",
            event_idempotency_key=f"{command_id}:workflow_run_created",
            payload_json={
                "workflow_name": workflow_name,
                "workflow_id": workflow_id,
                "kind": "workflow",
                "configured_engine_mode": configured_engine_mode,
                "effective_engine_mode": preview_runtime.effective_engine_mode,
                "provider_mode": preview_runtime.provider_mode,
                "provider_transport": preview_runtime.provider_transport,
                "provider_adapter": preview_runtime.provider_adapter,
                "provider_runtime": preview_runtime.provider_runtime,
                "provider_impl": preview_runtime.provider_impl,
                "auth_key_source": preview_runtime.auth_key_source,
                "observation_source": OBSERVATION_SOURCE_ENGINE_ORIGIN_BATCH,
            },
        )
        outcome = asyncio.run(
            run_workflow_execution(
                api_base=api_base,
                auth_token=auth_token,
                workflow_id=workflow_id,
                global_input_data=global_input_data,
                per_skill_input=per_skill_input,
                output_format=output_format,
                configured_engine_mode=configured_engine_mode,
            )
        )
        last_event_key = workflow_created.event_key
        for step in outcome.steps:
            node_id = f"execution:{step['execution_id']}"
            attempt_no = 1
            node_started = builder.append_event(
                "node_execution_started",
                node_id=node_id,
                attempt_no=attempt_no,
                origin_layer="engine",
                causation_key=workflow_created.event_key,
                trigger_event_key=workflow_created.event_key,
                event_idempotency_key=f"{command_id}:{node_id}:node_execution_started:{attempt_no}",
                payload_json={
                    "execution_id": step["execution_id"],
                    "workflow_execution_id": outcome.workflow_execution_id,
                    "workflow_skill_id": step.get("workflow_skill_id"),
                    "skill_order": step.get("skill_order"),
                    "skill_name": step.get("skill_name"),
                    "execution_role": step.get("execution_role"),
                    "configured_engine_mode": step.get("configured_engine_mode"),
                    "effective_engine_mode": step.get("effective_engine_mode"),
                    "provider_mode": step.get("provider_mode"),
                    "provider_transport": step.get("provider_transport"),
                    "provider_adapter": step.get("provider_adapter"),
                    "provider_runtime": step.get("provider_runtime"),
                    "provider_impl": step.get("provider_impl"),
                    "auth_key_source": step.get("auth_key_source"),
                    "observation_source": step.get("observation_source", OBSERVATION_SOURCE_ENGINE_ORIGIN_BATCH),
                },
            )
            retry_event = self._append_retry_chain(
                builder,
                command_id=command_id,
                node_id=node_id,
                attempt_no=attempt_no,
                configured_engine_mode=str(step.get("configured_engine_mode") or configured_engine_mode),
                effective_engine_mode=str(step.get("effective_engine_mode") or preview_runtime.effective_engine_mode),
                provider_mode=str(step.get("provider_mode") or preview_runtime.provider_mode),
                provider_transport=str(step.get("provider_transport") or preview_runtime.provider_transport),
                provider_adapter=str(step.get("provider_adapter") or preview_runtime.provider_adapter),
                provider_runtime=str(step.get("provider_runtime") or preview_runtime.provider_runtime),
                provider_impl=str(step.get("provider_impl") or preview_runtime.provider_impl),
                auth_key_source=str(step.get("auth_key_source") or preview_runtime.auth_key_source),
                model=str(step.get("model_used") or ""),
                token_accounting_source=str(step.get("token_accounting_source") or "unavailable"),
                status=str(step.get("status") or "error"),
                provider_output=str(step.get("output") or ""),
                error_code=step.get("provider_error_code"),
                retry_reason=step.get("retry_reason"),
                error_message=step.get("provider_error_message") or step.get("error_message"),
                started_from=node_started.event_key,
            )
            node_finished = builder.append_event(
                "node_execution_finished",
                node_id=node_id,
                attempt_no=attempt_no,
                origin_layer="engine",
                causation_key=retry_event.event_key,
                trigger_event_key=retry_event.event_key,
                event_idempotency_key=f"{command_id}:{node_id}:node_execution_finished:{attempt_no}",
                payload_json={
                    "status": step.get("status"),
                    "execution_id": step["execution_id"],
                    "workflow_execution_id": outcome.workflow_execution_id,
                    "error_message": step.get("error_message"),
                    "configured_engine_mode": step.get("configured_engine_mode"),
                    "effective_engine_mode": step.get("effective_engine_mode"),
                    "provider_mode": step.get("provider_mode"),
                    "provider_transport": step.get("provider_transport"),
                    "provider_adapter": step.get("provider_adapter"),
                    "provider_runtime": step.get("provider_runtime"),
                    "provider_impl": step.get("provider_impl"),
                    "auth_key_source": step.get("auth_key_source"),
                    "token_accounting_source": step.get("token_accounting_source"),
                    "provider_error_code": step.get("provider_error_code"),
                    "retry_reason": step.get("retry_reason"),
                    "observation_source": step.get("observation_source", OBSERVATION_SOURCE_ENGINE_ORIGIN_BATCH),
                },
            )
            last_event_key = node_finished.event_key
        builder.append_event(
            "workflow_run_finished",
            attempt_no=0,
            origin_layer="engine",
            causation_key=last_event_key,
            trigger_event_key=last_event_key,
            event_idempotency_key=f"{command_id}:workflow_run_finished",
            payload_json={
                "status": outcome.status,
                "workflow_execution_id": outcome.workflow_execution_id,
                "leader_execution_id": outcome.leader_execution_id,
                "configured_engine_mode": outcome.configured_engine_mode,
                "effective_engine_mode": outcome.effective_engine_mode,
                "provider_mode": outcome.provider_mode,
                "provider_transport": outcome.provider_transport,
                "provider_adapter": outcome.provider_adapter,
                "provider_runtime": outcome.provider_runtime,
                "provider_impl": outcome.provider_impl,
                "auth_key_source": outcome.auth_key_source,
                "token_accounting_source": outcome.token_accounting_source,
                "provider_error_code": outcome.provider_error_code,
                "retry_reason": outcome.retry_reason,
                "observation_source": outcome.observation_source,
            },
        )
        return {
            "status": outcome.status,
            "workflow_execution_id": outcome.workflow_execution_id,
            "execution_ids": outcome.execution_ids,
            "leader_execution_id": outcome.leader_execution_id,
            "output": outcome.output,
            "error_message": outcome.error_message,
            "configured_engine_mode": outcome.configured_engine_mode,
            "effective_engine_mode": outcome.effective_engine_mode,
            "provider_mode": outcome.provider_mode,
            "provider_transport": outcome.provider_transport,
            "provider_adapter": outcome.provider_adapter,
            "provider_runtime": outcome.provider_runtime,
            "provider_impl": outcome.provider_impl,
            "auth_key_source": outcome.auth_key_source,
            "token_accounting_source": outcome.token_accounting_source,
            "provider_error_code": outcome.provider_error_code,
            "provider_error_message": outcome.provider_error_message,
            "retry_reason": outcome.retry_reason,
            "observation_source": outcome.observation_source,
            "events": builder.export(),
        }

    def _run_demo_workflow(self, payload: dict[str, Any]) -> dict[str, Any]:
        topic = str(payload.get("topic") or "Desktop orchestration bootstrap")
        engine_mode = str(payload.get("engine_mode") or "api_key")
        runtime_info = preview_runtime_info(engine_mode)
        observation_source = "demo_sidecar_preview"
        correlation_id = str(payload.get("correlation_id") or f"sidecar-corr-{payload['request_id']}")
        command_id = str(payload.get("command_id") or f"sidecar-request-{payload['request_id']}")
        workflow_name = str(payload.get("workflow_name") or "Desktop Demo Workflow")
        node_id = str(payload.get("node_id") or "demo-node")
        attempt_no = int(payload.get("attempt_no") or 1)
        builder = EventBatchBuilder(correlation_id=correlation_id, command_id=command_id)
        workflow_created = builder.append_event(
            "workflow_run_created",
            attempt_no=0,
            origin_layer="engine",
            event_idempotency_key=f"{command_id}:workflow_run_created",
            payload_json={
                "workflow_name": workflow_name,
                "configured_engine_mode": runtime_info.configured_engine_mode,
                "effective_engine_mode": runtime_info.effective_engine_mode,
                "provider_mode": runtime_info.provider_mode,
                "provider_transport": runtime_info.provider_transport,
                "provider_adapter": runtime_info.provider_adapter,
                "provider_runtime": runtime_info.provider_runtime,
                "provider_impl": runtime_info.provider_impl,
                "auth_key_source": runtime_info.auth_key_source,
                "observation_source": observation_source,
            },
        )
        node_started = builder.append_event(
            "node_execution_started",
            node_id=node_id,
            attempt_no=attempt_no,
            origin_layer="engine",
            causation_key=workflow_created.event_key,
            trigger_event_key=workflow_created.event_key,
            event_idempotency_key=f"{command_id}:{node_id}:node_execution_started:{attempt_no}",
            payload_json={
                "node_id": node_id,
                "attempt_no": attempt_no,
                "configured_engine_mode": runtime_info.configured_engine_mode,
                "effective_engine_mode": runtime_info.effective_engine_mode,
                "provider_mode": runtime_info.provider_mode,
                "provider_transport": runtime_info.provider_transport,
                "provider_adapter": runtime_info.provider_adapter,
                "provider_runtime": runtime_info.provider_runtime,
                "provider_impl": runtime_info.provider_impl,
                "auth_key_source": runtime_info.auth_key_source,
                "observation_source": observation_source,
            },
        )
        provider_started = builder.append_event(
            "provider_request_started",
            node_id=node_id,
            attempt_no=attempt_no,
            origin_layer="provider",
            causation_key=node_started.event_key,
            trigger_event_key=node_started.event_key,
            event_idempotency_key=f"{command_id}:{node_id}:provider_request_started:{attempt_no}",
            payload_json={
                "configured_engine_mode": runtime_info.configured_engine_mode,
                "effective_engine_mode": runtime_info.effective_engine_mode,
                "provider_mode": runtime_info.provider_mode,
                "provider_transport": runtime_info.provider_transport,
                "provider_adapter": runtime_info.provider_adapter,
                "provider_runtime": runtime_info.provider_runtime,
                "provider_impl": runtime_info.provider_impl,
                "auth_key_source": runtime_info.auth_key_source,
                "model": "demo-model",
                "observation_source": observation_source,
            },
        )
        provider = create_provider(engine_mode)
        provider_response = provider.run(
            ProviderRequest(
                prompt=f"Summarize desktop migration kickoff for: {topic}",
                model="demo-model",
                metadata={
                    "topic": topic,
                    "command_id": command_id,
                    "correlation_id": correlation_id,
                },
            )
        )
        forced_retry_reason = parse_retry_reason(payload.get("force_retry_reason"))
        if forced_retry_reason is not None:
            provider_response = ProviderResponse(
                status="error",
                output_text="",
                provider_mode=provider_response.provider_mode,
                model=provider_response.model,
                error_code=forced_retry_reason.value,
                error_message=f"forced {forced_retry_reason.value}",
            )
        provider_finished = builder.append_event(
            "provider_request_finished",
            node_id=node_id,
            attempt_no=attempt_no,
            origin_layer="provider",
            causation_key=provider_started.event_key,
            trigger_event_key=provider_started.event_key,
            event_idempotency_key=f"{command_id}:{node_id}:provider_request_finished:{attempt_no}",
            payload_json={
                "status": provider_response.status,
                "provider_output": provider_response.output_text,
                "configured_engine_mode": runtime_info.configured_engine_mode,
                "effective_engine_mode": runtime_info.effective_engine_mode,
                "provider_mode": runtime_info.provider_mode,
                "provider_transport": provider_response.provider_transport,
                "provider_adapter": provider_response.provider_adapter,
                "provider_runtime": provider_response.provider_runtime,
                "provider_impl": provider_response.provider_impl,
                "auth_key_source": runtime_info.auth_key_source,
                "model": provider_response.model,
                "error_code": provider_response.error_code,
                "error_message": provider_response.error_message,
                "observation_source": observation_source,
            },
        )
        retry_reason = forced_retry_reason or retry_reason_from_response(provider_response)
        if retry_reason is None:
            retry_payload = {
                "should_retry": False,
                "layer": "transport",
                "reason": None,
                "next_delay_seconds": 0.0,
                "configured_engine_mode": runtime_info.configured_engine_mode,
                "effective_engine_mode": runtime_info.effective_engine_mode,
                "provider_mode": runtime_info.provider_mode,
                "provider_transport": runtime_info.provider_transport,
                "provider_adapter": runtime_info.provider_adapter,
                "provider_runtime": runtime_info.provider_runtime,
                "provider_impl": runtime_info.provider_impl,
                "auth_key_source": runtime_info.auth_key_source,
                "observation_source": observation_source,
            }
        else:
            retry_decision = self.retry_policy.decide(retry_reason, attempt_no)
            retry_payload = {
                "should_retry": retry_decision.should_retry,
                "layer": retry_decision.layer.value,
                "reason": retry_decision.reason.value,
                "next_delay_seconds": retry_decision.next_delay_seconds,
                "configured_engine_mode": runtime_info.configured_engine_mode,
                "effective_engine_mode": runtime_info.effective_engine_mode,
                "provider_mode": runtime_info.provider_mode,
                "provider_transport": runtime_info.provider_transport,
                "provider_adapter": runtime_info.provider_adapter,
                "provider_runtime": runtime_info.provider_runtime,
                "provider_impl": runtime_info.provider_impl,
                "auth_key_source": runtime_info.auth_key_source,
                "observation_source": observation_source,
            }
        retry_event = builder.append_event(
            "retry_decision_made",
            node_id=node_id,
            attempt_no=attempt_no,
            origin_layer="retry",
            causation_key=provider_finished.event_key,
            trigger_event_key=provider_finished.event_key,
            event_idempotency_key=f"{command_id}:{node_id}:retry_decision_made:{attempt_no}",
            payload_json=retry_payload,
        )
        builder.append_event(
            "node_execution_finished",
            node_id=node_id,
            attempt_no=attempt_no,
            origin_layer="engine",
            causation_key=retry_event.event_key,
            trigger_event_key=retry_event.event_key,
            event_idempotency_key=f"{command_id}:{node_id}:node_execution_finished:{attempt_no}",
            payload_json={
                "status": provider_response.status,
                "summary": (
                    "Demo workflow completed via sidecar. "
                    f"mode={runtime_info.provider_mode}, topic={topic}"
                ),
                "error_message": provider_response.error_message,
                "configured_engine_mode": runtime_info.configured_engine_mode,
                "effective_engine_mode": runtime_info.effective_engine_mode,
                "provider_mode": runtime_info.provider_mode,
                "provider_transport": runtime_info.provider_transport,
                "provider_adapter": runtime_info.provider_adapter,
                "provider_runtime": runtime_info.provider_runtime,
                "provider_impl": runtime_info.provider_impl,
                "auth_key_source": runtime_info.auth_key_source,
                "observation_source": observation_source,
            },
        )

        return {
            "status": provider_response.status,
            "summary": (
                "Demo workflow completed via sidecar. "
                f"mode={runtime_info.provider_mode}, topic={topic}"
            ),
            "provider_output": provider_response.output_text,
            "engine_mode_hint": runtime_info.effective_engine_mode,
            "configured_engine_mode": runtime_info.configured_engine_mode,
            "effective_engine_mode": runtime_info.effective_engine_mode,
            "provider_mode": runtime_info.provider_mode,
            "provider_transport": runtime_info.provider_transport,
            "provider_adapter": runtime_info.provider_adapter,
            "provider_runtime": runtime_info.provider_runtime,
            "provider_impl": runtime_info.provider_impl,
            "auth_key_source": runtime_info.auth_key_source,
            "observation_source": observation_source,
            "events": builder.export(),
        }

    def _shutdown(self, _: dict[str, Any]) -> dict[str, Any]:
        return {"status": "ok", "message": "shutdown"}


def parse_request(line: str) -> RequestEnvelope:
    payload = json.loads(line)
    return RequestEnvelope(
        request_id=int(payload["id"]),
        command=str(payload["command"]),
        payload=dict(payload.get("payload") or {}),
    )


def emit_response(request_id: int, ok: bool, result: dict[str, Any] | None = None, error: str | None = None) -> None:
    response = {
        "id": request_id,
        "ok": ok,
        "result": result or {},
        "error": error,
    }
    sys.stdout.write(json.dumps(response, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def main() -> int:
    app = SidecarApp()

    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue

        try:
            envelope = parse_request(line)
            result = app.handle(envelope)
            emit_response(envelope.request_id, True, result=result)

            if envelope.command == "shutdown":
                return 0
        except Exception as exc:  # pragma: no cover - defensive IPC boundary
            request_id = 0
            try:
                request_id = json.loads(line).get("id", 0)
            except Exception:
                pass
            emit_response(int(request_id), False, error=str(exc))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
