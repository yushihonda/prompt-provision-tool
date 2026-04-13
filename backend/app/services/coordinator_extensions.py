"""
Coordinator Extensions — Adapter Registry / Task Envelope / Eval Harness / Resume

coordinator_service.py が持つ Plan / Artifact / Worker / Workspace の上に、
外部実行環境を扱うアダプターレジストリ、ポータブルなタスクエンベロープ、
品質評価メトリクス、再開・部分リプレイの仕組みを追加する。

- Adapter Registry: 内部 sidecar / ローカル LLM / 外部 API / 外部 CLI を統一して登録・検索
- Task Envelope: アダプター間で受け渡し可能なポータブル JSON タスク表現
- Eval Harness: 完成度・修正率・local/remote 利用比率などの品質メトリクス計算
- Resume: 中断された plan の再開と未完了タスクの抽出
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models import (
    CoordinatorPlan,
    CoordinatorAdapter,
    CoordinatorArtifact,
    CoordinatorEvent,
    CoordinatorWorker,
    CoordinatorEvalRun,
    Execution,
)
from app.services.coordinator_service import (
    record_event,
    PROVIDER_REMOTE_ONLY,
    PROVIDER_LOCAL_PREFERRED,
)


# ───────────────────────────────────────────────
#  Events
# ───────────────────────────────────────────────

EVENT_ADAPTER_REGISTERED = "adapter_registered"
EVENT_ADAPTER_HEALTH_CHANGED = "adapter_health_changed"
EVENT_TASK_ENVELOPE_CREATED = "task_envelope_created"
EVENT_EVAL_RECORDED = "eval_recorded"
EVENT_PLAN_RESUMED = "plan_resumed"
EVENT_PLAN_REPLAYED = "plan_replayed"


# ───────────────────────────────────────────────
#  Adapter types
# ───────────────────────────────────────────────

ADAPTER_INTERNAL = "internal"
ADAPTER_EXTERNAL_CLI = "external_cli"
ADAPTER_HYBRID = "hybrid"
ADAPTER_LOCAL_LLM = "local_llm"
ADAPTER_REMOTE_API = "remote_api"


def _safe_json_dumps(obj: Any) -> Optional[str]:
    if obj is None:
        return None
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return None


def _safe_json_loads(s: Optional[str]) -> Any:
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return None


# ───────────────────────────────────────────────
#  Adapter Registry
#  実行バックエンド (sidecar / local LLM / remote API / external CLI) を
#  統一インターフェースで登録し、role と provider_mode で検索可能にする。
# ───────────────────────────────────────────────

def register_adapter(
    db: Session,
    *,
    name: str,
    adapter_type: str,
    provider_mode: str,
    transport: str = "process_stdio",
    runtime: Optional[str] = None,
    impl: Optional[str] = None,
    supported_roles: Optional[List[str]] = None,
    capabilities: Optional[List[str]] = None,
    input_schema: Optional[Dict[str, Any]] = None,
    output_schema: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
    plan_id: Optional[str] = None,
) -> CoordinatorAdapter:
    """新しい adapter をレジストリに登録"""
    existing = db.query(CoordinatorAdapter).filter(CoordinatorAdapter.name == name).first()
    if existing:
        # 既存の場合は idempotent に再有効化
        existing.is_enabled = True
        existing.adapter_type = adapter_type
        existing.provider_mode = provider_mode
        existing.transport = transport
        existing.runtime = runtime
        existing.impl = impl
        existing.supported_roles = _safe_json_dumps(supported_roles)
        existing.capabilities = _safe_json_dumps(capabilities)
        existing.input_schema = _safe_json_dumps(input_schema)
        existing.output_schema = _safe_json_dumps(output_schema)
        existing.config = _safe_json_dumps(config)
        db.commit()
        db.refresh(existing)
        if plan_id:
            record_event(db, plan_id, EVENT_ADAPTER_REGISTERED,
                         payload={"adapter_id": existing.adapter_id, "name": name, "type": adapter_type})
        return existing

    adapter = CoordinatorAdapter(
        adapter_id=str(uuid.uuid4()),
        name=name,
        adapter_type=adapter_type,
        provider_mode=provider_mode,
        transport=transport,
        runtime=runtime,
        impl=impl,
        supported_roles=_safe_json_dumps(supported_roles or []),
        capabilities=_safe_json_dumps(capabilities or []),
        input_schema=_safe_json_dumps(input_schema),
        output_schema=_safe_json_dumps(output_schema),
        config=_safe_json_dumps(config),
        is_enabled=True,
        health_status="unknown",
    )
    db.add(adapter)
    db.commit()
    db.refresh(adapter)
    if plan_id:
        record_event(db, plan_id, EVENT_ADAPTER_REGISTERED,
                     payload={"adapter_id": adapter.adapter_id, "name": name, "type": adapter_type})
    return adapter


def list_adapters(db: Session, *, only_enabled: bool = True) -> List[CoordinatorAdapter]:
    q = db.query(CoordinatorAdapter)
    if only_enabled:
        q = q.filter(CoordinatorAdapter.is_enabled == True)  # noqa: E712
    return q.order_by(CoordinatorAdapter.id.asc()).all()


def find_adapter_for_task(
    db: Session,
    *,
    role: str,
    provider_mode: str,
    capability: Optional[str] = None,
) -> Optional[CoordinatorAdapter]:
    """role + provider_mode + (任意の capability) にマッチする adapter を返す"""
    adapters = list_adapters(db, only_enabled=True)
    candidates: List[CoordinatorAdapter] = []
    for a in adapters:
        if a.provider_mode != provider_mode and a.provider_mode != "hybrid_auto":
            continue
        roles = _safe_json_loads(a.supported_roles) or []
        if roles and role not in roles:
            continue
        caps = _safe_json_loads(a.capabilities) or []
        if capability and caps and capability not in caps:
            continue
        candidates.append(a)
    return candidates[0] if candidates else None


def build_provider_payload(
    adapter: Optional[CoordinatorAdapter],
    *,
    model: Optional[str] = None,
    timeout: float = 120.0,
    api_key: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Convert a CoordinatorAdapter row into the sidecar provider_payload dict.

    Returns None for adapters that the sidecar resolves on its own (cli /
    internal sdk). Only http-transport adapters need explicit payloads.
    """
    if adapter is None or adapter.transport != "http":
        return None
    config = _safe_json_loads(adapter.config) or {}
    base_url = adapter.impl or config.get("endpoint")
    if not base_url:
        return None
    selected_model = (
        model
        or config.get("default_model")
        or "qwen2.5-coder:14b"
    )
    return {
        "transport": "http",
        "base_url": base_url,
        "model": selected_model,
        "api_key": api_key,
        "timeout": float(config.get("timeout", timeout)),
        "adapter_id": adapter.adapter_id,
        "adapter_name": adapter.name,
        "provider_mode": adapter.provider_mode,
    }


def update_adapter_health(
    db: Session,
    adapter_id: str,
    health_status: str,
    plan_id: Optional[str] = None,
    *,
    detail: Optional[Dict[str, Any]] = None,
) -> Optional[CoordinatorAdapter]:
    """Update adapter health, optionally storing a detail blob.

    `detail` is merged into adapter.config under the `last_health_detail`
    key so we avoid a schema migration in this PR. Pass keys like
    {"models": [...], "latency_ms": 12, "error": None}.
    """
    adapter = db.query(CoordinatorAdapter).filter(CoordinatorAdapter.adapter_id == adapter_id).first()
    if not adapter:
        return None
    prev = adapter.health_status
    adapter.health_status = health_status
    adapter.last_health_check = datetime.utcnow()
    if detail is not None:
        config = _safe_json_loads(adapter.config) or {}
        config["last_health_detail"] = {
            **detail,
            "checked_at": adapter.last_health_check.isoformat() + "Z",
            "status": health_status,
        }
        adapter.config = _safe_json_dumps(config)
    db.commit()
    db.refresh(adapter)
    if plan_id and prev != health_status:
        record_event(db, plan_id, EVENT_ADAPTER_HEALTH_CHANGED,
                     payload={"adapter_id": adapter_id, "from": prev, "to": health_status})
    return adapter


def refresh_local_adapter_health(
    db: Session,
    adapter_id: str,
    *,
    probe_fn: Optional[Any] = None,
) -> Optional[CoordinatorAdapter]:
    """Probe a local-LLM adapter's HTTP endpoint and persist the result.

    `probe_fn` is an injectable callable taking (base_url) and returning
    {"reachable": bool, "models": list[str], "latency_ms": int|None, "error": str|None}.
    Defaults to `_default_probe_local_endpoint` which uses httpx.

    Health mapping:
        reachable + non-empty models -> "healthy"
        reachable + empty models     -> "degraded"
        unreachable                  -> "unreachable"
    """
    adapter = db.query(CoordinatorAdapter).filter(CoordinatorAdapter.adapter_id == adapter_id).first()
    if adapter is None:
        return None
    if adapter.transport != "http":
        return adapter

    config = _safe_json_loads(adapter.config) or {}
    base_url = adapter.impl or config.get("endpoint")
    if not base_url:
        return update_adapter_health(
            db, adapter_id, "unknown",
            detail={"error": "no_base_url", "models": [], "latency_ms": None},
        )

    probe = probe_fn or _default_probe_local_endpoint
    result = probe(base_url)

    if not result.get("reachable"):
        new_status = "unreachable"
    elif not result.get("models"):
        new_status = "degraded"
    else:
        new_status = "healthy"

    return update_adapter_health(
        db, adapter_id, new_status,
        detail={
            "models": result.get("models") or [],
            "latency_ms": result.get("latency_ms"),
            "error": result.get("error"),
        },
    )


def _default_probe_local_endpoint(base_url: str) -> Dict[str, Any]:
    """Default probe — calls GET {base_url}/models via httpx.

    Mirrors sidecar/app/providers/discovery.list_models() shape so backend
    and sidecar agree on the result schema.
    """
    import time
    import httpx

    url = f"{base_url.rstrip('/')}/models"
    started = time.monotonic()
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(url)
    except httpx.ConnectError as exc:
        return {"reachable": False, "models": [], "latency_ms": None, "error": f"connect_error: {exc}"}
    except httpx.TimeoutException as exc:
        return {"reachable": False, "models": [], "latency_ms": None, "error": f"timeout: {exc}"}
    except httpx.HTTPError as exc:
        return {"reachable": False, "models": [], "latency_ms": None, "error": f"http_error: {exc}"}

    latency_ms = int((time.monotonic() - started) * 1000)
    if resp.status_code >= 400:
        return {
            "reachable": False, "models": [], "latency_ms": latency_ms,
            "error": f"http_{resp.status_code}",
        }
    try:
        data = resp.json()
    except ValueError as exc:
        return {
            "reachable": True, "models": [], "latency_ms": latency_ms,
            "error": f"malformed_json: {exc}",
        }
    raw = data.get("data") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return {
            "reachable": True, "models": [], "latency_ms": latency_ms,
            "error": "malformed_response",
        }
    models: List[str] = []
    for item in raw:
        if isinstance(item, dict):
            mid = item.get("id")
            if isinstance(mid, str):
                models.append(mid)
    return {"reachable": True, "models": models, "latency_ms": latency_ms, "error": None}


def seed_default_adapters(db: Session) -> List[CoordinatorAdapter]:
    """起動時に既定の adapter を投入する。重複は idempotent。"""
    seeded: List[CoordinatorAdapter] = []
    seeded.append(register_adapter(
        db,
        name="internal-sidecar",
        adapter_type=ADAPTER_INTERNAL,
        provider_mode=PROVIDER_REMOTE_ONLY,
        transport="process_stdio",
        runtime="python",
        impl="sidecar.main",
        supported_roles=["researcher", "writer", "reviewer", "judge"],
        capabilities=["streaming", "tools"],
    ))
    seeded.append(register_adapter(
        db,
        name="local-llm-ollama",
        adapter_type=ADAPTER_LOCAL_LLM,
        provider_mode=PROVIDER_LOCAL_PREFERRED,
        transport="http",
        runtime="http",
        impl="http://localhost:11434/v1",
        supported_roles=["researcher", "writer"],
        capabilities=["streaming", "openai_compat"],
        config={
            "endpoint": "http://localhost:11434/v1",
            "default_model": "qwen2.5-coder:14b",
        },
    ))
    seeded.append(register_adapter(
        db,
        name="claude-code-local",
        adapter_type=ADAPTER_EXTERNAL_CLI,
        provider_mode=PROVIDER_REMOTE_ONLY,
        transport="external_cli",
        runtime="claude_code",
        impl="claude",
        supported_roles=["writer", "reviewer", "researcher"],
        capabilities=[
            "file_read", "file_write", "shell_exec",
            "local_auth_session", "workspace_aware",
            "streaming_stdout", "streaming_stderr", "pty",
        ],
        config={
            "runtime": "claude_code",
            "command": "claude",
            "default_args": [],
            "timeout_ms": 900000,
            "requires_local_auth": True,
        },
    ))
    seeded.append(register_adapter(
        db,
        name="codex-local",
        adapter_type=ADAPTER_EXTERNAL_CLI,
        provider_mode=PROVIDER_REMOTE_ONLY,
        transport="external_cli",
        runtime="codex",
        impl="codex",
        supported_roles=["writer", "reviewer", "researcher"],
        capabilities=[
            "file_read", "file_write", "shell_exec",
            "local_auth_session", "workspace_aware",
            "streaming_stdout", "streaming_stderr",
        ],
        config={
            "runtime": "codex",
            "command": "codex",
            "default_args": [],
            "timeout_ms": 900000,
            "requires_local_auth": True,
        },
    ))
    seeded.append(register_adapter(
        db,
        name="remote-api-openai-compat",
        adapter_type=ADAPTER_REMOTE_API,
        provider_mode=PROVIDER_REMOTE_ONLY,
        transport="http",
        runtime="http",
        impl="user_api_keys",
        supported_roles=["researcher", "writer", "reviewer", "judge"],
        capabilities=["streaming", "tools", "thinking"],
    ))
    return seeded


# ───────────────────────────────────────────────
#  Portable Task Envelope
#  task / context / artifacts / constraints / budget / expected_output / return_channel を
#  含む 1 つの JSON にまとめ、どのアダプターからも同じ形で受け取れるようにする。
# ───────────────────────────────────────────────

def build_task_envelope(
    db: Session,
    plan: CoordinatorPlan,
    task_spec: Dict[str, Any],
    *,
    prior_artifacts: Optional[List[CoordinatorArtifact]] = None,
    deadline_ms: Optional[int] = None,
    return_event_stream: Optional[str] = None,
    return_artifact_sink: Optional[str] = None,
) -> Dict[str, Any]:
    """各 adapter で受け渡し可能なポータブルタスクエンベロープを生成する。"""
    summaries = []
    if prior_artifacts:
        for a in prior_artifacts:
            summaries.append({
                "task_id": a.task_id,
                "role": a.role,
                "type": a.artifact_type,
                "summary": (a.summary or "")[:200],
            })

    envelope = {
        "envelope_version": "1.0",
        "envelope_id": str(uuid.uuid4()),
        "plan_id": plan.plan_id,
        "task": task_spec,
        "context": {
            "goal": plan.goal or "",
            "prior_tasks": [a.task_id for a in (prior_artifacts or [])],
            "summaries": summaries,
        },
        "artifacts": [
            {
                "artifact_id": a.artifact_id,
                "task_id": a.task_id,
                "role": a.role,
                "type": a.artifact_type,
                "summary": a.summary,
                "model_hint": a.model_hint,
                "provider_mode": a.provider_mode,
            }
            for a in (prior_artifacts or [])
        ],
        "constraints": {
            "deadline_ms": deadline_ms,
            "max_turns": task_spec.get("retry_budget", 1) + 1,
            "writes_files": task_spec.get("writes_files", False),
        },
        "budget": {
            "class": task_spec.get("budget_class", "standard"),
            "provider_mode": task_spec.get("resolved_provider_mode") or task_spec.get("provider_mode_hint") or PROVIDER_REMOTE_ONLY,
        },
        "expected_output": {
            "schema": task_spec.get("output_schema", "text"),
            "artifact_type": task_spec.get("expected_artifact_type", "draft"),
        },
        "return_channel": {
            "event_stream": return_event_stream or f"plan:{plan.plan_id}:events",
            "artifact_sink": return_artifact_sink or f"plan:{plan.plan_id}:artifacts",
        },
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    record_event(db, plan.plan_id, EVENT_TASK_ENVELOPE_CREATED,
                 task_id=task_spec.get("task_id"),
                 payload={"envelope_id": envelope["envelope_id"]})
    return envelope


# ───────────────────────────────────────────────
#  Evaluation Harness
#  plan の現在状態 (artifacts / events / executions) からメトリクスを算出し、
#  履歴に保存する。後で local 解禁範囲を判断する材料にする。
# ───────────────────────────────────────────────

def compute_eval_metrics(db: Session, plan: CoordinatorPlan) -> Dict[str, Any]:
    """plan の現在の状態からメトリクスを算出する"""
    artifacts = db.query(CoordinatorArtifact).filter(
        CoordinatorArtifact.plan_id == plan.plan_id
    ).all()
    events = db.query(CoordinatorEvent).filter(
        CoordinatorEvent.plan_id == plan.plan_id
    ).all()
    workers = db.query(CoordinatorWorker).filter(
        CoordinatorWorker.plan_id == plan.plan_id
    ).all()

    try:
        tasks = json.loads(plan.tasks or "[]")
    except Exception:
        tasks = []

    total_tasks = len(tasks)
    finished_artifacts = len(artifacts)
    completeness = (finished_artifacts / total_tasks * 100.0) if total_tasks else 0.0

    # revision rate: reflection_loop > 0 の execution の割合
    exec_ids = [a.execution_id for a in artifacts if a.execution_id]
    reflections = 0
    total_execs = 0
    if exec_ids:
        execs = db.query(Execution).filter(Execution.id.in_(exec_ids)).all()
        total_execs = len(execs)
        reflections = sum(1 for e in execs if (e.reflection_loop or 0) > 0)
    revision_rate = (reflections / total_execs * 100.0) if total_execs else 0.0

    # judge pass rate: judge_decision_made イベントが pass を含む割合
    judge_events = [e for e in events if e.event_type == "judge_decision_made"]
    judge_total = len(judge_events)
    judge_pass = sum(1 for e in judge_events if (e.payload or "").find("pass") != -1)
    judge_pass_rate = (judge_pass / judge_total * 100.0) if judge_total else 0.0

    # local usage rate: artifacts のうち provider_mode が local_* な割合
    local_count = sum(1 for a in artifacts if (a.provider_mode or "").startswith("local"))
    local_usage_rate = (local_count / finished_artifacts * 100.0) if finished_artifacts else 0.0

    # remote escalation rate: provider_mode が remote_only な artifact のうち、role が researcher/writer のもの
    remote_count = sum(1 for a in artifacts if (a.provider_mode or "") == "remote_only" and a.role in ("researcher", "writer"))
    remote_escalation_rate = (remote_count / finished_artifacts * 100.0) if finished_artifacts else 0.0

    # overhead: created_at のスパン
    overhead_ms = 0
    if plan.created_at and artifacts:
        last = max((a.created_at for a in artifacts if a.created_at), default=None)
        if last:
            overhead_ms = int((last - plan.created_at).total_seconds() * 1000)

    # artifact_reuse_rate: 現状は未実装 (artifact lineage 解析が必要なためプレースホルダ)
    artifact_reuse_rate = 0.0

    # factuality: ヒューリスティック - quality_gate_pass イベントの割合
    qg_passes = sum(1 for e in events if e.event_type == "review_requested")
    factuality = (qg_passes / total_tasks * 100.0) if total_tasks else 0.0

    return {
        "completeness": round(completeness, 2),
        "factuality": round(factuality, 2),
        "revision_rate": round(revision_rate, 2),
        "judge_pass_rate": round(judge_pass_rate, 2),
        "overhead_ms": overhead_ms,
        "artifact_reuse_rate": round(artifact_reuse_rate, 2),
        "local_usage_rate": round(local_usage_rate, 2),
        "remote_escalation_rate": round(remote_escalation_rate, 2),
    }


def record_eval_run(db: Session, plan: CoordinatorPlan) -> CoordinatorEvalRun:
    metrics = compute_eval_metrics(db, plan)
    eval_run = CoordinatorEvalRun(
        eval_id=str(uuid.uuid4()),
        plan_id=plan.plan_id,
        workflow_execution_id=plan.workflow_execution_id,
        completeness=metrics["completeness"],
        factuality=metrics["factuality"],
        revision_rate=metrics["revision_rate"],
        judge_pass_rate=metrics["judge_pass_rate"],
        overhead_ms=metrics["overhead_ms"],
        artifact_reuse_rate=metrics["artifact_reuse_rate"],
        local_usage_rate=metrics["local_usage_rate"],
        remote_escalation_rate=metrics["remote_escalation_rate"],
        metrics_extra=_safe_json_dumps(metrics),
    )
    db.add(eval_run)
    db.commit()
    db.refresh(eval_run)
    record_event(db, plan.plan_id, EVENT_EVAL_RECORDED, payload=metrics)
    return eval_run


def get_eval_runs_for_plan(db: Session, plan_id: str) -> List[CoordinatorEvalRun]:
    return db.query(CoordinatorEvalRun).filter(
        CoordinatorEvalRun.plan_id == plan_id
    ).order_by(CoordinatorEvalRun.created_at.asc()).all()


# ───────────────────────────────────────────────
#  Resume / Partial Replay
#  途中で中断した plan を再開する。完了済み artifact を再利用し、
#  未完了の task のみを再実行できるようにする。
# ───────────────────────────────────────────────

def list_resumable_plans(db: Session, *, account_id: Optional[int] = None) -> List[CoordinatorPlan]:
    """artifact が一部存在し、まだ完了していない plan を列挙する"""
    plans = db.query(CoordinatorPlan).order_by(CoordinatorPlan.id.desc()).limit(50).all()
    result = []
    for plan in plans:
        try:
            tasks = json.loads(plan.tasks or "[]")
        except Exception:
            tasks = []
        artifact_count = db.query(CoordinatorArtifact).filter(
            CoordinatorArtifact.plan_id == plan.plan_id
        ).count()
        if 0 < artifact_count < len(tasks):
            result.append(plan)
    return result


def find_unfinished_tasks(db: Session, plan: CoordinatorPlan) -> List[Dict[str, Any]]:
    """artifact 未生成の task を返す"""
    try:
        tasks = json.loads(plan.tasks or "[]")
    except Exception:
        tasks = []
    artifacts = db.query(CoordinatorArtifact).filter(
        CoordinatorArtifact.plan_id == plan.plan_id
    ).all()
    finished_task_ids = {a.task_id for a in artifacts}
    return [t for t in tasks if t.get("task_id") not in finished_task_ids]


def mark_plan_resumed(db: Session, plan: CoordinatorPlan, *, reason: str = "manual_resume") -> None:
    record_event(db, plan.plan_id, EVENT_PLAN_RESUMED, payload={"reason": reason})


def mark_plan_replayed(db: Session, plan: CoordinatorPlan, *, target_task_ids: Optional[List[str]] = None) -> None:
    record_event(db, plan.plan_id, EVENT_PLAN_REPLAYED,
                 payload={"target_task_ids": target_task_ids or []})
