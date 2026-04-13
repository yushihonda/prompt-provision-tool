"""
承認リクエスト管理サービス

ask_before_shell をはじめとする承認ポリシーの永続状態管理を提供する。
冪等な解決とセッション層への状態連携を行う。
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models import ApprovalRequest, WorkflowExecution
from app.services.session_service import (
    update_session_status,
    add_approval_ref,
    move_approval_ref,
    SESSION_WAITING_APPROVAL,
    SESSION_RUNNING,
)
from app.services.session_events import (
    emit_approval_event,
    emit_session_lifecycle,
    APPROVAL_REQUESTED,
    APPROVAL_GRANTED,
    APPROVAL_REJECTED,
    APPROVAL_TIMED_OUT,
    SESSION_WAITING_APPROVAL as _SE_WAITING_APPROVAL,
    SESSION_RESUMED,
)

logger = logging.getLogger(__name__)


def create_approval_request(
    db: Session,
    *,
    session_id: Optional[str] = None,
    plan_id: Optional[str] = None,
    step_id: Optional[str] = None,
    execution_id: Optional[int] = None,
    workflow_execution_id: Optional[int] = None,
    adapter_id: Optional[str] = None,
    runtime: Optional[str] = None,
    approval_policy: str = "ask_before_shell",
    prompt_preview: Optional[str] = None,
    cwd: Optional[str] = None,
    attempt_no: int = 1,
) -> ApprovalRequest:
    """pending 状態の承認リクエストを作成し、セッションを waiting_approval に遷移する。"""
    approval_id = f"apr_{uuid.uuid4().hex[:16]}"

    req = ApprovalRequest(
        approval_id=approval_id,
        session_id=session_id,
        plan_id=plan_id,
        step_id=step_id,
        execution_id=execution_id,
        workflow_execution_id=workflow_execution_id,
        adapter_id=adapter_id,
        runtime=runtime,
        approval_policy=approval_policy,
        status="pending",
        prompt_preview=prompt_preview,
        cwd=cwd,
        attempt_no=attempt_no,
    )
    db.add(req)
    db.flush()

    # セッションステータスと承認サマリーを更新
    if workflow_execution_id and session_id:
        try:
            wf_exec = db.query(WorkflowExecution).filter(
                WorkflowExecution.id == workflow_execution_id,
            ).first()
            if wf_exec and wf_exec.session_id:
                update_session_status(db, wf_exec, SESSION_WAITING_APPROVAL, step_id=step_id)
                add_approval_ref(db, wf_exec, approval_id, "pending")
                if plan_id:
                    emit_approval_event(
                        db, session_id, plan_id, APPROVAL_REQUESTED,
                        step_id=step_id or "",
                        approval_id=approval_id,
                        payload={
                            "approval_policy": approval_policy,
                            "adapter_id": adapter_id,
                            "runtime": runtime,
                            "cwd": cwd,
                        },
                    )
                    emit_session_lifecycle(
                        db, session_id, plan_id, _SE_WAITING_APPROVAL,
                        step_id=step_id,
                    )
        except Exception:
            logger.debug("承認リクエスト作成時のセッションイベント発行失敗", exc_info=True)

    db.commit()
    db.refresh(req)
    return req


def resolve_approval(
    db: Session,
    approval_id: str,
    decision: str,
    decided_by: str = "user",
    decision_comment: Optional[str] = None,
) -> Optional[ApprovalRequest]:
    """pending の承認リクエストを解決する（冪等: 解決済みならそのまま返す）。

    decision: "granted" | "rejected" | "timed_out"
    """
    req = db.query(ApprovalRequest).filter(
        ApprovalRequest.approval_id == approval_id,
    ).first()
    if not req:
        return None

    # 冪等: 既に解決済み
    if req.status != "pending":
        return req

    valid_decisions = {"granted", "rejected", "timed_out"}
    if decision not in valid_decisions:
        raise ValueError(f"不正な decision: {decision} (有効値: {valid_decisions})")

    req.status = decision
    req.decided_by = decided_by
    req.decided_at = datetime.now(timezone.utc)
    db.add(req)
    db.flush()

    # セッション連携
    if req.workflow_execution_id and req.session_id:
        try:
            wf_exec = db.query(WorkflowExecution).filter(
                WorkflowExecution.id == req.workflow_execution_id,
            ).first()
            if wf_exec and wf_exec.session_id:
                move_approval_ref(db, wf_exec, approval_id, "pending", decision)
                if decision == "granted":
                    update_session_status(db, wf_exec, SESSION_RUNNING, step_id=req.step_id)
                # rejected / timed_out はステップ失敗ハンドラーが
                # セッションステータスを適切に遷移する

                if req.plan_id:
                    event_map = {
                        "granted": APPROVAL_GRANTED,
                        "rejected": APPROVAL_REJECTED,
                        "timed_out": APPROVAL_TIMED_OUT,
                    }
                    emit_approval_event(
                        db, req.session_id, req.plan_id, event_map[decision],
                        step_id=req.step_id or "",
                        approval_id=approval_id,
                        payload={
                            "decision": decision,
                            "decided_by": decided_by,
                            "comment": decision_comment,
                        },
                    )
                    if decision == "granted":
                        emit_session_lifecycle(
                            db, req.session_id, req.plan_id, SESSION_RESUMED,
                            step_id=req.step_id,
                        )
        except Exception:
            logger.debug("承認解決時のセッションイベント発行失敗", exc_info=True)

    db.commit()
    db.refresh(req)
    return req


def create_and_resolve_approval(
    db: Session,
    *,
    approval_id: str,
    decision: str,
    decided_by: str = "user",
    decision_comment: Optional[str] = None,
    session_id: Optional[str] = None,
    plan_id: Optional[str] = None,
    step_id: Optional[str] = None,
    execution_id: Optional[int] = None,
    workflow_execution_id: Optional[int] = None,
    adapter_id: Optional[str] = None,
    runtime: Optional[str] = None,
    approval_policy: str = "ask_before_shell",
    prompt_preview: Optional[str] = None,
    cwd: Optional[str] = None,
    attempt_no: int = 1,
) -> ApprovalRequest:
    """承認リクエストの作成と解決を同時に行う（Tauri フロー用アトミック操作）。

    Tauri 側でローカルの oneshot チャネルが先に解決され、
    後からバックエンドに最終状態のレコードを同期するケースで使用する。
    """
    # 冪等: 既存チェック
    existing = db.query(ApprovalRequest).filter(
        ApprovalRequest.approval_id == approval_id,
    ).first()
    if existing:
        if existing.status == "pending":
            return resolve_approval(
                db,
                approval_id,
                decision,
                decided_by,
                decision_comment=decision_comment,
            )
        return existing

    req = ApprovalRequest(
        approval_id=approval_id,
        session_id=session_id,
        plan_id=plan_id,
        step_id=step_id,
        execution_id=execution_id,
        workflow_execution_id=workflow_execution_id,
        adapter_id=adapter_id,
        runtime=runtime,
        approval_policy=approval_policy,
        status=decision,
        prompt_preview=prompt_preview,
        cwd=cwd,
        decided_by=decided_by,
        decided_at=datetime.now(timezone.utc),
        attempt_no=attempt_no,
    )
    db.add(req)
    db.flush()

    # セッションサマリーに記録
    if workflow_execution_id and session_id:
        try:
            wf_exec = db.query(WorkflowExecution).filter(
                WorkflowExecution.id == workflow_execution_id,
            ).first()
            if wf_exec and wf_exec.session_id:
                add_approval_ref(db, wf_exec, approval_id, decision)
                if plan_id:
                    emit_approval_event(
                        db, session_id, plan_id, APPROVAL_REQUESTED,
                        step_id=step_id or "",
                        approval_id=approval_id,
                        payload={"approval_policy": approval_policy, "adapter_id": adapter_id},
                    )
                    event_map = {
                        "granted": APPROVAL_GRANTED,
                        "rejected": APPROVAL_REJECTED,
                        "timed_out": APPROVAL_TIMED_OUT,
                    }
                    if decision in event_map:
                        emit_approval_event(
                            db, session_id, plan_id, event_map[decision],
                            step_id=step_id or "",
                            approval_id=approval_id,
                            payload={
                                "decision": decision,
                                "decided_by": decided_by,
                                "comment": decision_comment,
                            },
                        )
        except Exception:
            logger.debug("承認作成+解決時のセッションイベント発行失敗", exc_info=True)

    db.commit()
    db.refresh(req)
    return req


def get_pending_approvals(
    db: Session,
    workflow_execution_id: int,
) -> List[ApprovalRequest]:
    """指定ワークフロー実行の pending 承認リクエスト一覧を返す。"""
    return (
        db.query(ApprovalRequest)
        .filter(
            ApprovalRequest.workflow_execution_id == workflow_execution_id,
            ApprovalRequest.status == "pending",
        )
        .order_by(ApprovalRequest.created_at.asc())
        .all()
    )


def get_approvals_for_execution(
    db: Session,
    workflow_execution_id: int,
) -> List[ApprovalRequest]:
    """指定ワークフロー実行の全承認リクエスト（全ステータス）を返す。"""
    return (
        db.query(ApprovalRequest)
        .filter(ApprovalRequest.workflow_execution_id == workflow_execution_id)
        .order_by(ApprovalRequest.created_at.asc())
        .all()
    )
