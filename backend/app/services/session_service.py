"""
WorkflowRunSession 管理サービス

WorkflowExecution 上の session 列を操作するヘルパー群。
JSON blob は Text 列に格納し、Python 側で逐次マージする。
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models import WorkflowExecution


# ── セッションステータス定数 ──
SESSION_INITIALIZING = "initializing"
SESSION_RUNNING = "running"
SESSION_WAITING_APPROVAL = "waiting_approval"
SESSION_PAUSED = "paused"
SESSION_COMPLETED = "completed"
SESSION_FAILED = "failed"
SESSION_CANCELLED = "cancelled"

VALID_SESSION_STATUSES = {
    SESSION_INITIALIZING,
    SESSION_RUNNING,
    SESSION_WAITING_APPROVAL,
    SESSION_PAUSED,
    SESSION_COMPLETED,
    SESSION_FAILED,
    SESSION_CANCELLED,
}


def _load_json(text: Optional[str], default: Any = None) -> Any:
    """JSON テキストをパースする。None や不正値はデフォルトを返す。"""
    if text is None:
        return default if default is not None else {}
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else {}


def _dump_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


# ───────────────────────────────────────────────
#  セッションライフサイクル
# ───────────────────────────────────────────────

def create_session(db: Session, wf_exec: WorkflowExecution) -> str:
    """session_id を発行し、セッション列を初期化する。"""
    session_id = f"sess_{uuid.uuid4().hex[:16]}"
    wf_exec.session_id = session_id
    wf_exec.session_status = SESSION_INITIALIZING
    wf_exec.runtime_bindings = _dump_json({})
    wf_exec.workspace_bindings = _dump_json({})
    wf_exec.approval_summary = _dump_json({"pending": [], "granted": [], "rejected": []})
    wf_exec.artifact_refs = _dump_json({})
    db.add(wf_exec)
    db.flush()
    return session_id


def update_session_status(
    db: Session,
    wf_exec: WorkflowExecution,
    new_status: str,
    *,
    step_id: Optional[str] = None,
) -> None:
    """セッションステータスを遷移する。step_id を指定すると current_step_id も更新。"""
    if new_status not in VALID_SESSION_STATUSES:
        raise ValueError(f"不正なセッションステータス: {new_status}")
    wf_exec.session_status = new_status
    if step_id is not None:
        wf_exec.current_step_id = step_id
    db.add(wf_exec)
    db.flush()


# ───────────────────────────────────────────────
#  ランタイムバインディング
# ───────────────────────────────────────────────

def bind_runtime(
    db: Session,
    wf_exec: WorkflowExecution,
    step_id: str,
    binding: Dict[str, Any],
) -> None:
    """ステップのランタイムバインディングを追加・上書きする。"""
    bindings = _load_json(wf_exec.runtime_bindings, {})
    bindings[step_id] = binding
    wf_exec.runtime_bindings = _dump_json(bindings)
    db.add(wf_exec)
    db.flush()


# ───────────────────────────────────────────────
#  ワークスペースバインディング
# ───────────────────────────────────────────────

def bind_workspace(
    db: Session,
    wf_exec: WorkflowExecution,
    step_id: str,
    binding: Dict[str, Any],
) -> None:
    """ステップのワークスペースバインディングを追加・上書きする。"""
    bindings = _load_json(wf_exec.workspace_bindings, {})
    bindings[step_id] = binding
    wf_exec.workspace_bindings = _dump_json(bindings)
    db.add(wf_exec)
    db.flush()


# ───────────────────────────────────────────────
#  レジュームカーソル
# ───────────────────────────────────────────────

def update_resume_cursor(
    db: Session,
    wf_exec: WorkflowExecution,
    cursor: Dict[str, Any],
) -> None:
    """再開位置カーソルを設定する。"""
    wf_exec.resume_cursor = _dump_json(cursor)
    db.add(wf_exec)
    db.flush()


# ───────────────────────────────────────────────
#  アーティファクト参照
# ───────────────────────────────────────────────

def add_artifact_ref(
    db: Session,
    wf_exec: WorkflowExecution,
    step_id: str,
    artifact_id: str,
) -> None:
    """ステップのアーティファクト参照を追加する（重複無視）。"""
    refs = _load_json(wf_exec.artifact_refs, {})
    step_refs: List[str] = refs.get(step_id, [])
    if artifact_id not in step_refs:
        step_refs.append(artifact_id)
    refs[step_id] = step_refs
    wf_exec.artifact_refs = _dump_json(refs)
    db.add(wf_exec)
    db.flush()


# ───────────────────────────────────────────────
#  承認サマリーヘルパー
# ───────────────────────────────────────────────

def add_approval_ref(
    db: Session,
    wf_exec: WorkflowExecution,
    approval_id: str,
    bucket: str = "pending",
) -> None:
    """承認リクエスト参照をサマリーに追加する。"""
    summary = _load_json(wf_exec.approval_summary, {"pending": [], "granted": [], "rejected": []})
    if bucket not in summary:
        summary[bucket] = []
    if approval_id not in summary[bucket]:
        summary[bucket].append(approval_id)
    wf_exec.approval_summary = _dump_json(summary)
    db.add(wf_exec)
    db.flush()


def move_approval_ref(
    db: Session,
    wf_exec: WorkflowExecution,
    approval_id: str,
    from_bucket: str,
    to_bucket: str,
) -> None:
    """承認リクエスト参照をバケット間で移動する。"""
    summary = _load_json(wf_exec.approval_summary, {"pending": [], "granted": [], "rejected": []})
    for b in (from_bucket, to_bucket):
        if b not in summary:
            summary[b] = []
    if approval_id in summary.get(from_bucket, []):
        summary[from_bucket].remove(approval_id)
    if approval_id not in summary[to_bucket]:
        summary[to_bucket].append(approval_id)
    wf_exec.approval_summary = _dump_json(summary)
    db.add(wf_exec)
    db.flush()


# ───────────────────────────────────────────────
#  セッション状態の読み取り
# ───────────────────────────────────────────────

def get_session_state(db: Session, wf_exec: WorkflowExecution) -> Optional[Dict[str, Any]]:
    """API レスポンス用のセッション状態を返す。

    session_id 未設定（レガシー実行）の場合は None を返す。
    """
    if not wf_exec.session_id:
        return None
    return {
        "session_id": wf_exec.session_id,
        "session_status": wf_exec.session_status,
        "current_step_id": wf_exec.current_step_id,
        "resume_cursor": _load_json(wf_exec.resume_cursor),
        "runtime_bindings": _load_json(wf_exec.runtime_bindings, {}),
        "workspace_bindings": _load_json(wf_exec.workspace_bindings, {}),
        "approval_summary": _load_json(wf_exec.approval_summary, {}),
        "artifact_refs": _load_json(wf_exec.artifact_refs, {}),
        "workflow_execution_id": wf_exec.id,
        "workflow_id": wf_exec.workflow_id,
        "coordinator_plan_id": wf_exec.coordinator_plan_id,
        "started_at": wf_exec.started_at.isoformat() if wf_exec.started_at else None,
        "completed_at": wf_exec.completed_at.isoformat() if wf_exec.completed_at else None,
    }
