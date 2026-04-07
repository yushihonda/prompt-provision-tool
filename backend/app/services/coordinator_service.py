"""
Coordinator Service — Plan / Worker / Artifact / Event / Workspace 管理

既存の WorkflowExecution / Execution の上に semantic orchestration の観測層を載せる。
実行を駆動するわけではなく、ワークフロー実行を観測してメタデータを蓄積し、
役割ベースの可視化と将来の自律的オーケストレーションの土台を提供する。

- CoordinatorPlan: ワークフロー実行開始時に生成される事前計画スナップショット
- CoordinatorWorker: 名前付きの論理ワーカー (役割割当の投影)
- CoordinatorArtifact: 各 execution の成果物を構造化保存
- CoordinatorEvent: オーケストレーションイベントの時系列ログ
- CoordinatorFollowUpTask: 既存タスクから派生する追加タスク
- CoordinatorWorkspace: writes_files=true なタスクの分離ワークスペース
- DAG / topological sort: depends_on を解決した実行レイヤー算出
- Provider router: role / impact / retry に応じた provider_mode の決定
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import (
    CoordinatorPlan,
    CoordinatorArtifact,
    CoordinatorEvent,
    CoordinatorWorker,
    CoordinatorFollowUpTask,
    CoordinatorWorkspace,
    WorkflowExecution,
    Workflow,
    WorkflowSkill,
    WorkflowGroup,
    Execution,
)


# ───────────────────────────────────────────────
#  Constants
# ───────────────────────────────────────────────

ROLE_RESEARCHER = "researcher"
ROLE_WRITER = "writer"
ROLE_REVIEWER = "reviewer"
ROLE_JUDGE = "judge"

ARTIFACT_NOTES = "notes"
ARTIFACT_EVIDENCE = "evidence"
ARTIFACT_DRAFT = "draft"
ARTIFACT_REVIEW = "review"
ARTIFACT_SCORE = "score"
ARTIFACT_FINAL = "final"

EVENT_PLAN_CREATED = "plan_created"
EVENT_TASK_ENQUEUED = "task_enqueued"
EVENT_TASK_STARTED = "task_started"
EVENT_TASK_FINISHED = "task_finished"
EVENT_ARTIFACT_CREATED = "artifact_created"
EVENT_REVIEW_REQUESTED = "review_requested"
EVENT_JUDGE_DECISION_MADE = "judge_decision_made"
EVENT_RUN_COMPLETED = "run_completed"

PROVIDER_REMOTE_ONLY = "remote_only"
PROVIDER_LOCAL_ONLY = "local_only"
PROVIDER_LOCAL_PREFERRED = "local_preferred"
PROVIDER_HYBRID_AUTO = "hybrid_auto"

# Worker statuses
WORKER_IDLE = "idle"
WORKER_RUNNING = "running"
WORKER_BLOCKED = "blocked"
WORKER_FAILED = "failed"
WORKER_DONE = "done"

# Follow-up reasons
FOLLOWUP_CLARIFY = "clarify"
FOLLOWUP_EXPAND = "expand"
FOLLOWUP_FIX = "fix"
FOLLOWUP_VERIFY = "verify"
FOLLOWUP_MERGE = "merge"

# Worker / followup / workspace events
EVENT_WORKER_REGISTERED = "worker_registered"
EVENT_WORKER_STATUS_CHANGED = "worker_status_changed"
EVENT_FOLLOWUP_ENQUEUED = "followup_enqueued"
EVENT_FOLLOWUP_RESOLVED = "followup_resolved"
EVENT_WORKSPACE_RESERVED = "workspace_reserved"
EVENT_WORKSPACE_PROMOTED = "workspace_promoted"
EVENT_WORKSPACE_CLEANED = "workspace_cleaned"

# Workspace modes
WORKSPACE_SHARED = "shared"
WORKSPACE_TEMP_DIR = "temp_dir"
WORKSPACE_WORKTREE = "worktree"


# ───────────────────────────────────────────────
#  Profile -> Role mapping
#  既存の agent_profile を Coordinator role にマップする
# ───────────────────────────────────────────────

PROFILE_TO_ROLE = {
    "explore": ROLE_RESEARCHER,
    "plan": ROLE_WRITER,
    "implement": ROLE_WRITER,
    "verification": ROLE_REVIEWER,
    "default": ROLE_WRITER,
}


def map_profile_to_role(profile: Optional[str]) -> str:
    return PROFILE_TO_ROLE.get((profile or "default").lower(), ROLE_WRITER)


def default_artifact_type_for_role(role: str) -> str:
    return {
        ROLE_RESEARCHER: ARTIFACT_NOTES,
        ROLE_WRITER: ARTIFACT_DRAFT,
        ROLE_REVIEWER: ARTIFACT_REVIEW,
        ROLE_JUDGE: ARTIFACT_SCORE,
    }.get(role, ARTIFACT_DRAFT)


# ───────────────────────────────────────────────
#  Plan generation
# ───────────────────────────────────────────────

def build_coordinator_plan(
    db: Session,
    wf_exec: WorkflowExecution,
    workflow: Workflow,
    wf_skills: List[WorkflowSkill],
    wf_groups: List[WorkflowGroup],
) -> CoordinatorPlan:
    """ワークフロー実行開始時に CoordinatorPlan を生成・永続化する"""
    plan_id = str(uuid.uuid4())

    # roles: 利用される profile から動的に role を作成
    profiles_used: set[str] = set()
    for ws in wf_skills:
        profiles_used.add((ws.agent_profile or "default").lower())

    roles = []
    for profile in sorted(profiles_used):
        role = map_profile_to_role(profile)
        roles.append({
            "role": role,
            "label": profile,
            "default_provider_mode": PROVIDER_REMOTE_ONLY,
        })
    # judge ロールは並列グループがある場合に追加
    has_parallel = any((g.execution_type or "serial") == "parallel" for g in wf_groups)
    if has_parallel and not any(r["role"] == ROLE_JUDGE for r in roles):
        roles.append({
            "role": ROLE_JUDGE,
            "label": "judge",
            "default_provider_mode": PROVIDER_REMOTE_ONLY,
        })

    # tasks: WorkflowSkill ベースで TaskSpec を生成
    tasks = []
    for ws in wf_skills:
        profile = (ws.agent_profile or "default").lower()
        role = map_profile_to_role(profile)
        artifact_type = default_artifact_type_for_role(role)

        # impact level: verification は high、それ以外は medium
        impact_level = "high" if profile == "verification" else "medium"

        # quality_gate が有効な場合は requires_review=True
        requires_review = (ws.quality_gate_type or "disabled") != "disabled"

        # depends_on: 同じグループ内の前のスキル
        depends_on = []
        if ws.group_id:
            grp = next((g for g in wf_groups if g.id == ws.group_id), None)
            if grp and (grp.execution_type or "serial") == "serial":
                # 直列グループでは前のスキルに依存
                prev = [
                    f"task_{s.id}" for s in wf_skills
                    if s.group_id == ws.group_id and (s.order_in_group or 0) < (ws.order_in_group or 0)
                ]
                depends_on = prev[-1:] if prev else []

        tasks.append({
            "task_id": f"task_{ws.id}",
            "role": role,
            "objective": ws.skill_name or f"Step {ws.skill_order}",
            "input_refs": [],
            "expected_artifact_type": artifact_type,
            "impact_level": impact_level,
            "budget_class": "standard",
            "requires_review": requires_review,
            "writes_files": False,
            "retry_budget": ws.max_reflection_loops or 0,
            "provider_mode_hint": None,
            "depends_on": depends_on,
            "workflow_skill_id": ws.id,
        })

    # provider_policy: デフォルトは remote_only。role/impact ベースの簡易ルールで上書き
    provider_policy = {
        "default_mode": PROVIDER_REMOTE_ONLY,
        "local_model": None,
        "remote_model": workflow.parent_model_type,
        "escalation_rules": [
            {"when": {"role": ROLE_RESEARCHER, "impact_level": "low"}, "switch_to": PROVIDER_LOCAL_PREFERRED},
            {"when": {"role": ROLE_REVIEWER}, "switch_to": PROVIDER_REMOTE_ONLY},
            {"when": {"role": ROLE_JUDGE}, "switch_to": PROVIDER_REMOTE_ONLY},
            {"when": {"retry_count_gte": 2}, "switch_to": PROVIDER_REMOTE_ONLY},
        ],
    }

    # complexity_level: タスク数 + 並列の有無で簡易判定
    if len(tasks) <= 2 and not has_parallel:
        complexity = "low"
    elif len(tasks) >= 6 or has_parallel:
        complexity = "high"
    else:
        complexity = "medium"

    plan = CoordinatorPlan(
        plan_id=plan_id,
        workflow_execution_id=wf_exec.id,
        goal=workflow.description or workflow.name,
        complexity_level=complexity,
        max_parallelism=4,
        roles=json.dumps(roles, ensure_ascii=False),
        tasks=json.dumps(tasks, ensure_ascii=False),
        artifact_policy=json.dumps({"persist_intermediate": True}, ensure_ascii=False),
        review_policy=json.dumps({
            "enabled": any(t["requires_review"] for t in tasks),
            "max_revise_loops": max((t["retry_budget"] for t in tasks), default=0),
        }, ensure_ascii=False),
        stop_conditions=json.dumps({"on_error": "stop"}, ensure_ascii=False),
        provider_policy=json.dumps(provider_policy, ensure_ascii=False),
        schema_version="1.0",
    )
    db.add(plan)

    # WorkflowExecution に plan_id を紐付け
    wf_exec.coordinator_plan_id = plan_id
    db.commit()
    db.refresh(plan)

    # plan_created イベント
    record_event(
        db, plan_id, EVENT_PLAN_CREATED,
        payload={"task_count": len(tasks), "role_count": len(roles), "complexity": complexity},
    )
    # task_enqueued イベント (各タスク)
    for t in tasks:
        record_event(
            db, plan_id, EVENT_TASK_ENQUEUED,
            task_id=t["task_id"],
            payload={"role": t["role"], "objective": t["objective"]},
        )

    # 名前付き worker を自動生成し、role 単位で task をラウンドロビン割当
    try:
        provision_workers_for_plan(db, plan, tasks, roles)
    except Exception as _e:
        # worker 生成失敗はワークフロー実行を止めない
        pass

    # writes_files=true な task は自動でワークスペース予約
    try:
        auto_reserve_workspaces_for_plan(db, plan)
    except Exception as _e:
        pass

    return plan


# ───────────────────────────────────────────────
#  Named Worker Management
#  role × max_parallelism で論理ワーカーを生成し、task を割当てる。
#  実際の実行は Tauri 側 worker pool が担う。
# ───────────────────────────────────────────────

def provision_workers_for_plan(
    db: Session,
    plan: CoordinatorPlan,
    tasks: List[Dict[str, Any]],
    roles: List[Dict[str, Any]],
) -> List[CoordinatorWorker]:
    """プランの roles 数に応じて named worker を生成し、tasks をラウンドロビンでアサインする"""
    workers: List[CoordinatorWorker] = []
    role_counts: Dict[str, int] = {}

    # 同一 role の task が複数あれば worker も複数生成（最大 max_parallelism）
    role_task_count: Dict[str, int] = {}
    for t in tasks:
        r = t.get("role", "writer")
        role_task_count[r] = role_task_count.get(r, 0) + 1

    role_workers: Dict[str, List[CoordinatorWorker]] = {}
    for role_spec in roles:
        role_name = role_spec.get("role", "writer")
        wanted = max(1, min(role_task_count.get(role_name, 1), plan.max_parallelism or 4))
        for i in range(wanted):
            worker = CoordinatorWorker(
                worker_id=str(uuid.uuid4()),
                plan_id=plan.plan_id,
                name=f"{role_name}-{i + 1}",
                role=role_name,
                status=WORKER_IDLE,
                task_queue=json.dumps([], ensure_ascii=False),
                artifact_refs=json.dumps([], ensure_ascii=False),
                provider_mode=role_spec.get("default_provider_mode"),
            )
            db.add(worker)
            workers.append(worker)
            role_workers.setdefault(role_name, []).append(worker)

    db.commit()
    for w in workers:
        db.refresh(w)
        record_event(
            db, plan.plan_id, EVENT_WORKER_REGISTERED,
            payload={"worker_id": w.worker_id, "name": w.name, "role": w.role},
        )

    # round-robin で task を queue に割当
    rr_index: Dict[str, int] = {}
    for t in tasks:
        role_name = t.get("role", "writer")
        pool = role_workers.get(role_name, [])
        if not pool:
            continue
        idx = rr_index.get(role_name, 0)
        target = pool[idx % len(pool)]
        rr_index[role_name] = idx + 1
        try:
            queue = json.loads(target.task_queue or "[]")
        except Exception:
            queue = []
        queue.append(t["task_id"])
        target.task_queue = json.dumps(queue, ensure_ascii=False)

    db.commit()
    return workers


def update_worker_status(
    db: Session,
    worker_id: str,
    status: str,
    *,
    current_task_id: Optional[str] = None,
    artifact_id: Optional[str] = None,
) -> Optional[CoordinatorWorker]:
    worker = db.query(CoordinatorWorker).filter(CoordinatorWorker.worker_id == worker_id).first()
    if not worker:
        return None
    prev_status = worker.status
    worker.status = status
    if current_task_id is not None:
        worker.current_task_id = current_task_id
    if status == WORKER_RUNNING and not worker.started_at:
        worker.started_at = datetime.utcnow()
    if status in (WORKER_DONE, WORKER_FAILED):
        worker.finished_at = datetime.utcnow()
    if artifact_id:
        try:
            refs = json.loads(worker.artifact_refs or "[]")
        except Exception:
            refs = []
        if artifact_id not in refs:
            refs.append(artifact_id)
        worker.artifact_refs = json.dumps(refs, ensure_ascii=False)
    db.commit()
    db.refresh(worker)
    record_event(
        db, worker.plan_id, EVENT_WORKER_STATUS_CHANGED,
        payload={"worker_id": worker_id, "from": prev_status, "to": status, "task_id": current_task_id},
    )
    return worker


def find_worker_for_task(db: Session, plan_id: str, task_id: str) -> Optional[CoordinatorWorker]:
    """task が割当られている worker を探す"""
    workers = db.query(CoordinatorWorker).filter(CoordinatorWorker.plan_id == plan_id).all()
    for w in workers:
        try:
            queue = json.loads(w.task_queue or "[]")
        except Exception:
            queue = []
        if task_id in queue:
            return w
    return None


def get_workers_for_plan(db: Session, plan_id: str) -> List[CoordinatorWorker]:
    return db.query(CoordinatorWorker).filter(
        CoordinatorWorker.plan_id == plan_id
    ).order_by(CoordinatorWorker.id.asc()).all()


# ───────────────────────────────────────────────
#  Follow-up Tasks
#  既存タスクの output を参照して派生タスクを発行する。
#  reason は clarify / expand / fix / verify / merge を想定。
# ───────────────────────────────────────────────

def enqueue_followup_task(
    db: Session,
    plan_id: str,
    *,
    target_role: str,
    objective: str,
    parent_task_id: Optional[str] = None,
    target_worker_name: Optional[str] = None,
    input_artifact_refs: Optional[List[str]] = None,
    output_schema: Optional[str] = None,
    requires_review: bool = False,
    reason: Optional[str] = None,
    depends_on: Optional[List[str]] = None,
) -> CoordinatorFollowUpTask:
    task = CoordinatorFollowUpTask(
        task_id=str(uuid.uuid4()),
        plan_id=plan_id,
        parent_task_id=parent_task_id,
        target_role=target_role,
        target_worker_name=target_worker_name,
        objective=objective,
        input_artifact_refs=json.dumps(input_artifact_refs or [], ensure_ascii=False),
        output_schema=output_schema,
        requires_review=requires_review,
        reason=reason,
        status="pending",
        depends_on=json.dumps(depends_on or [], ensure_ascii=False),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    record_event(
        db, plan_id, EVENT_FOLLOWUP_ENQUEUED,
        task_id=task.task_id,
        payload={
            "parent_task_id": parent_task_id,
            "target_role": target_role,
            "reason": reason,
            "objective": objective[:200],
        },
    )
    return task


def get_followup_tasks_for_plan(db: Session, plan_id: str) -> List[CoordinatorFollowUpTask]:
    return db.query(CoordinatorFollowUpTask).filter(
        CoordinatorFollowUpTask.plan_id == plan_id
    ).order_by(CoordinatorFollowUpTask.created_at.asc()).all()


def resolve_followup_task(db: Session, task_id: str, status: str = "done") -> Optional[CoordinatorFollowUpTask]:
    task = db.query(CoordinatorFollowUpTask).filter(CoordinatorFollowUpTask.task_id == task_id).first()
    if not task:
        return None
    task.status = status
    task.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(task)
    record_event(
        db, task.plan_id, EVENT_FOLLOWUP_RESOLVED,
        task_id=task_id,
        payload={"status": status},
    )
    return task


# ───────────────────────────────────────────────
#  Dependency Graph
#  task.depends_on を解決して DAG を構築し、トポロジカルソートで
#  並列実行可能なレイヤーに分解する。
# ───────────────────────────────────────────────

def build_task_dag(plan: CoordinatorPlan) -> Dict[str, Any]:
    """plan.tasks と follow-up tasks から DAG を構築する。
    各ノードは {id, role, depends_on, status, kind} を持つ。
    """
    try:
        tasks = json.loads(plan.tasks or "[]")
    except Exception:
        tasks = []

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, str]] = []
    seen_ids: set = set()

    for t in tasks:
        tid = t.get("task_id")
        if not tid or tid in seen_ids:
            continue
        seen_ids.add(tid)
        nodes.append({
            "id": tid,
            "role": t.get("role"),
            "objective": t.get("objective"),
            "kind": "primary",
            "depends_on": t.get("depends_on", []),
            "impact_level": t.get("impact_level"),
        })
        for dep in t.get("depends_on", []):
            edges.append({"from": dep, "to": tid})

    return {"nodes": nodes, "edges": edges}


def topological_sort_tasks(plan: CoordinatorPlan) -> List[List[str]]:
    """task を依存解決順にレイヤー化（同レイヤー内は並列実行可能）"""
    dag = build_task_dag(plan)
    nodes = {n["id"]: n for n in dag["nodes"]}
    in_degree = {nid: 0 for nid in nodes}
    adj: Dict[str, List[str]] = {nid: [] for nid in nodes}
    for e in dag["edges"]:
        if e["from"] in nodes and e["to"] in nodes:
            in_degree[e["to"]] += 1
            adj[e["from"]].append(e["to"])

    layers: List[List[str]] = []
    current = [nid for nid, d in in_degree.items() if d == 0]
    while current:
        layers.append(sorted(current))
        next_layer: List[str] = []
        for nid in current:
            for nxt in adj[nid]:
                in_degree[nxt] -= 1
                if in_degree[nxt] == 0:
                    next_layer.append(nxt)
        current = next_layer
    return layers


# ───────────────────────────────────────────────
#  Event recording
# ───────────────────────────────────────────────

def record_event(
    db: Session,
    plan_id: str,
    event_type: str,
    task_id: Optional[str] = None,
    artifact_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> CoordinatorEvent:
    event = CoordinatorEvent(
        plan_id=plan_id,
        event_type=event_type,
        task_id=task_id,
        artifact_id=artifact_id,
        payload=json.dumps(payload, ensure_ascii=False) if payload else None,
        schema_version="1.0",
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


# ───────────────────────────────────────────────
#  Artifact recording
# ───────────────────────────────────────────────

def record_artifact(
    db: Session,
    plan_id: str,
    task_id: str,
    role: str,
    artifact_type: str,
    *,
    execution_id: Optional[int] = None,
    summary: Optional[str] = None,
    inline_content: Optional[str] = None,
    content_ref: Optional[str] = None,
    provider_mode: Optional[str] = None,
    model_hint: Optional[str] = None,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> CoordinatorArtifact:
    artifact_id = str(uuid.uuid4())
    artifact = CoordinatorArtifact(
        artifact_id=artifact_id,
        plan_id=plan_id,
        task_id=task_id,
        execution_id=execution_id,
        role=role,
        artifact_type=artifact_type,
        schema_version="1.0",
        summary=summary,
        inline_content=inline_content,
        content_ref=content_ref,
        provider_mode=provider_mode,
        model_hint=model_hint,
        extra_metadata=json.dumps(extra_metadata, ensure_ascii=False) if extra_metadata else None,
    )
    db.add(artifact)
    db.commit()
    db.refresh(artifact)

    record_event(
        db, plan_id, EVENT_ARTIFACT_CREATED,
        task_id=task_id,
        artifact_id=artifact_id,
        payload={"role": role, "type": artifact_type, "execution_id": execution_id},
    )
    return artifact


# ───────────────────────────────────────────────
#  Provider routing
# ───────────────────────────────────────────────

def route_provider_mode(
    plan: CoordinatorPlan,
    *,
    role: str,
    artifact_type: str = "draft",
    impact_level: str = "medium",
    retry_count: int = 0,
    writes_files: bool = False,
) -> str:
    """provider_policy のルールに従って provider_mode を決定する"""
    try:
        policy = json.loads(plan.provider_policy or "{}")
    except Exception:
        policy = {}

    default = policy.get("default_mode", PROVIDER_REMOTE_ONLY)
    rules = policy.get("escalation_rules", [])

    # ルールを順番に評価。マッチした最後のルールを採用 (上書き優先順)
    selected = default
    for rule in rules:
        when = rule.get("when", {})
        if "role" in when and when["role"] != role:
            continue
        if "artifact_type" in when and when["artifact_type"] != artifact_type:
            continue
        if "impact_level" in when and when["impact_level"] != impact_level:
            continue
        if "writes_files" in when and bool(when["writes_files"]) != bool(writes_files):
            continue
        if "retry_count_gte" in when and retry_count < int(when["retry_count_gte"]):
            continue
        selected = rule.get("switch_to", selected)
    return selected


# ───────────────────────────────────────────────
#  Plan retrieval
# ───────────────────────────────────────────────

def get_plan_by_workflow_execution(db: Session, workflow_execution_id: int) -> Optional[CoordinatorPlan]:
    return db.query(CoordinatorPlan).filter(
        CoordinatorPlan.workflow_execution_id == workflow_execution_id
    ).order_by(CoordinatorPlan.id.desc()).first()


def get_artifacts_for_plan(db: Session, plan_id: str) -> List[CoordinatorArtifact]:
    return db.query(CoordinatorArtifact).filter(
        CoordinatorArtifact.plan_id == plan_id
    ).order_by(CoordinatorArtifact.created_at.asc()).all()


def get_events_for_plan(db: Session, plan_id: str, limit: int = 200) -> List[CoordinatorEvent]:
    return db.query(CoordinatorEvent).filter(
        CoordinatorEvent.plan_id == plan_id
    ).order_by(CoordinatorEvent.occurred_at.asc()).limit(limit).all()


# ───────────────────────────────────────────────
#  Workspace Isolation
#  writes_files=true なタスクのために worker ごとに分離されたワークスペースを
#  メタデータ上で管理する。実体ディレクトリはクライアント側 (Tauri) が管理する。
# ───────────────────────────────────────────────

def reserve_workspace(
    db: Session,
    plan_id: str,
    *,
    worker_id: Optional[str] = None,
    task_id: Optional[str] = None,
    mode: str = WORKSPACE_TEMP_DIR,
    cleanup_on_finish: bool = True,
) -> CoordinatorWorkspace:
    """ワークスペースを予約する。実体パスはクライアントが後で書き戻す。"""
    ws = CoordinatorWorkspace(
        workspace_id=str(uuid.uuid4()),
        plan_id=plan_id,
        worker_id=worker_id,
        task_id=task_id,
        mode=mode,
        cleanup_on_finish=cleanup_on_finish,
        status="reserved",
    )
    db.add(ws)
    db.commit()
    db.refresh(ws)
    record_event(
        db, plan_id, EVENT_WORKSPACE_RESERVED,
        task_id=task_id,
        payload={"workspace_id": ws.workspace_id, "mode": mode, "worker_id": worker_id},
    )
    return ws


def update_workspace_path(db: Session, workspace_id: str, workspace_path: str) -> Optional[CoordinatorWorkspace]:
    """クライアント側で確定したパスを書き戻す"""
    ws = db.query(CoordinatorWorkspace).filter(CoordinatorWorkspace.workspace_id == workspace_id).first()
    if not ws:
        return None
    ws.workspace_path = workspace_path
    ws.status = "active"
    db.commit()
    db.refresh(ws)
    return ws


def promote_workspace(db: Session, workspace_id: str) -> Optional[CoordinatorWorkspace]:
    """ワークスペースを最終ターゲットに反映済みとマーク"""
    ws = db.query(CoordinatorWorkspace).filter(CoordinatorWorkspace.workspace_id == workspace_id).first()
    if not ws:
        return None
    ws.promoted = True
    ws.promoted_at = datetime.utcnow()
    ws.status = "promoted"
    db.commit()
    db.refresh(ws)
    record_event(
        db, ws.plan_id, EVENT_WORKSPACE_PROMOTED,
        task_id=ws.task_id,
        payload={"workspace_id": workspace_id},
    )
    return ws


def cleanup_workspace(db: Session, workspace_id: str) -> Optional[CoordinatorWorkspace]:
    ws = db.query(CoordinatorWorkspace).filter(CoordinatorWorkspace.workspace_id == workspace_id).first()
    if not ws:
        return None
    ws.cleaned_at = datetime.utcnow()
    ws.status = "cleaned"
    db.commit()
    db.refresh(ws)
    record_event(
        db, ws.plan_id, EVENT_WORKSPACE_CLEANED,
        task_id=ws.task_id,
        payload={"workspace_id": workspace_id},
    )
    return ws


def get_workspaces_for_plan(db: Session, plan_id: str) -> List[CoordinatorWorkspace]:
    return db.query(CoordinatorWorkspace).filter(
        CoordinatorWorkspace.plan_id == plan_id
    ).order_by(CoordinatorWorkspace.created_at.asc()).all()


def auto_reserve_workspaces_for_plan(db: Session, plan: CoordinatorPlan) -> List[CoordinatorWorkspace]:
    """plan の中で writes_files=true な task に対して自動でワークスペースを予約"""
    try:
        tasks = json.loads(plan.tasks or "[]")
    except Exception:
        tasks = []
    reserved: List[CoordinatorWorkspace] = []
    for t in tasks:
        if not t.get("writes_files"):
            continue
        worker = find_worker_for_task(db, plan.plan_id, t["task_id"])
        ws = reserve_workspace(
            db, plan.plan_id,
            worker_id=worker.worker_id if worker else None,
            task_id=t["task_id"],
            mode=WORKSPACE_TEMP_DIR,
            cleanup_on_finish=True,
        )
        reserved.append(ws)
    return reserved
