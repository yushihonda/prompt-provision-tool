"""
正規化ワークフローイベント発行レイヤー

coordinator_service.record_event() をラップし、session 対応フィールド
(session_id / step_id / event_seq / event_namespace) を自動付与する。
schema_version="2.0" で旧来イベントと区別される。
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import CoordinatorEvent


# ───────────────────────────────────────────────
#  イベント分類定数
# ───────────────────────────────────────────────

# セッションライフサイクル
SESSION_STARTED = "workflow.session.started"
SESSION_STEP_ENTERED = "workflow.session.step_entered"
SESSION_PAUSED = "workflow.session.paused"
SESSION_RESUMED = "workflow.session.resumed"
SESSION_WAITING_APPROVAL = "workflow.session.waiting_approval"
SESSION_COMPLETED = "workflow.session.completed"
SESSION_FAILED = "workflow.session.failed"
SESSION_CANCELLED = "workflow.session.cancelled"

# ステップライフサイクル
STEP_PLANNED = "step.planned"
STEP_STARTED = "step.started"
STEP_COMPLETED = "step.completed"
STEP_FAILED = "step.failed"
STEP_RETRIED = "step.retried"
STEP_SKIPPED = "step.skipped"

# ランタイム解決
RUNTIME_SELECTED = "runtime.selected"
RUNTIME_FALLBACK = "runtime.fallback"
RUNTIME_CAPABILITY_CHECK = "runtime.capability_check"

# ワークスペースライフサイクル
WORKSPACE_CREATED = "workspace.created"
WORKSPACE_ACTIVATED = "workspace.activated"
WORKSPACE_PROMOTED = "workspace.promoted"
WORKSPACE_CLEANED = "workspace.cleaned"

# 承認ライフサイクル
APPROVAL_REQUESTED = "approval.requested"
APPROVAL_GRANTED = "approval.granted"
APPROVAL_REJECTED = "approval.rejected"
APPROVAL_TIMED_OUT = "approval.timed_out"

# アーティファクトライフサイクル
ARTIFACT_CREATED = "artifact.created"
ARTIFACT_PROMOTED = "artifact.promoted"


def _parse_namespace(event_type: str) -> str:
    """ドット区切りイベント名から namespace を抽出する。

    例: 'workflow.session.started' → 'workflow'
        'step.completed'           → 'step'
    """
    return event_type.split(".")[0]


def _next_event_seq(db: Session, session_id: str) -> int:
    """該当セッション内の次の event_seq を返す (MAX + 1)。"""
    result = (
        db.query(func.max(CoordinatorEvent.event_seq))
        .filter(CoordinatorEvent.session_id == session_id)
        .scalar()
    )
    return (result or 0) + 1


# ───────────────────────────────────────────────
#  コア発行関数
# ───────────────────────────────────────────────

def emit_session_event(
    db: Session,
    session_id: str,
    plan_id: str,
    event_type: str,
    *,
    step_id: Optional[str] = None,
    task_id: Optional[str] = None,
    artifact_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> CoordinatorEvent:
    """正規化セッションイベントを発行する。

    event_seq を自動インクリメントし、namespace をドット接頭辞から解析する。
    schema_version="2.0" で旧来イベントと共存する。
    """
    seq = _next_event_seq(db, session_id)
    namespace = _parse_namespace(event_type)

    event = CoordinatorEvent(
        plan_id=plan_id,
        event_type=event_type,
        task_id=task_id or step_id,
        artifact_id=artifact_id,
        payload=json.dumps(payload, ensure_ascii=False) if payload else None,
        schema_version="2.0",
        session_id=session_id,
        step_id=step_id,
        event_seq=seq,
        event_namespace=namespace,
    )
    db.add(event)
    db.flush()
    return event


# ───────────────────────────────────────────────
#  便利メソッド群
# ───────────────────────────────────────────────

def emit_session_lifecycle(
    db: Session,
    session_id: str,
    plan_id: str,
    event_type: str,
    *,
    step_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> CoordinatorEvent:
    """セッションライフサイクルイベント (workflow.session.*) を発行する。"""
    return emit_session_event(
        db, session_id, plan_id, event_type,
        step_id=step_id, payload=payload,
    )


def emit_step_event(
    db: Session,
    session_id: str,
    plan_id: str,
    event_type: str,
    step_id: str,
    *,
    payload: Optional[Dict[str, Any]] = None,
) -> CoordinatorEvent:
    """ステップライフサイクルイベント (step.*) を発行する。"""
    return emit_session_event(
        db, session_id, plan_id, event_type,
        step_id=step_id, payload=payload,
    )


def emit_runtime_event(
    db: Session,
    session_id: str,
    plan_id: str,
    event_type: str,
    step_id: str,
    *,
    payload: Optional[Dict[str, Any]] = None,
) -> CoordinatorEvent:
    """ランタイム解決イベント (runtime.*) を発行する。"""
    return emit_session_event(
        db, session_id, plan_id, event_type,
        step_id=step_id, payload=payload,
    )


def emit_workspace_event(
    db: Session,
    session_id: str,
    plan_id: str,
    event_type: str,
    step_id: str,
    *,
    payload: Optional[Dict[str, Any]] = None,
) -> CoordinatorEvent:
    """ワークスペースライフサイクルイベント (workspace.*) を発行する。"""
    return emit_session_event(
        db, session_id, plan_id, event_type,
        step_id=step_id, payload=payload,
    )


def emit_approval_event(
    db: Session,
    session_id: str,
    plan_id: str,
    event_type: str,
    step_id: str,
    *,
    approval_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> CoordinatorEvent:
    """承認ライフサイクルイベント (approval.*) を発行する。"""
    full_payload = dict(payload or {})
    if approval_id:
        full_payload["approval_id"] = approval_id
    return emit_session_event(
        db, session_id, plan_id, event_type,
        step_id=step_id, payload=full_payload,
    )


def emit_artifact_event(
    db: Session,
    session_id: str,
    plan_id: str,
    event_type: str,
    step_id: str,
    *,
    artifact_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> CoordinatorEvent:
    """アーティファクトライフサイクルイベント (artifact.*) を発行する。"""
    return emit_session_event(
        db, session_id, plan_id, event_type,
        step_id=step_id, artifact_id=artifact_id, payload=payload,
    )
