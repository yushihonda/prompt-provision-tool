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
from typing import Any, Dict, List, Optional, Tuple
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

def route_provider_mode_with_reason(
    plan: CoordinatorPlan,
    *,
    role: str,
    artifact_type: str = "draft",
    impact_level: str = "medium",
    retry_count: int = 0,
    writes_files: bool = False,
    cheap: bool = False,
) -> Tuple[str, str]:
    """Hard-rule + policy-rule routing.

    Returns (provider_mode, selection_reason). Selection reasons are stable
    machine-readable strings so they can be persisted for audit.
    """
    # Hard rules — early return. These cannot be overridden by policy.
    if role == ROLE_JUDGE:
        return PROVIDER_REMOTE_ONLY, "judge_forced_remote"
    if writes_files:
        return PROVIDER_REMOTE_ONLY, "writes_files_forced_remote"
    if retry_count >= 2:
        return PROVIDER_REMOTE_ONLY, "retry_escalation"
    if impact_level == "high":
        return PROVIDER_REMOTE_ONLY, "high_impact_remote"

    # Soft preference for clearly-cheap research-style work.
    if cheap or impact_level == "low":
        if role in (ROLE_RESEARCHER, ROLE_WRITER):
            return PROVIDER_LOCAL_PREFERRED, (
                "cheap_local" if cheap else "low_impact_local"
            )

    try:
        policy = json.loads(plan.provider_policy or "{}")
    except Exception:
        policy = {}

    default = policy.get("default_mode", PROVIDER_REMOTE_ONLY)
    rules = policy.get("escalation_rules", [])

    selected = default
    matched_index = -1
    for idx, rule in enumerate(rules):
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
        matched_index = idx

    reason = f"policy_rule:{matched_index}" if matched_index >= 0 else "policy_default"
    return selected, reason


def route_provider_mode(
    plan: CoordinatorPlan,
    *,
    role: str,
    artifact_type: str = "draft",
    impact_level: str = "medium",
    retry_count: int = 0,
    writes_files: bool = False,
) -> str:
    """Backwards-compatible wrapper. Returns mode only."""
    mode, _ = route_provider_mode_with_reason(
        plan,
        role=role,
        artifact_type=artifact_type,
        impact_level=impact_level,
        retry_count=retry_count,
        writes_files=writes_files,
    )
    return mode


def resolve_execution_provider_bundle(
    db: Session,
    plan: CoordinatorPlan,
    task: Dict[str, Any],
    *,
    retry_count: int = 0,
) -> Dict[str, Any]:
    """Resolve both selected provider and (when policy allows) a remote
    fallback provider for runtime fallback.

    Returns a dict with:
        provider_payload: the selected provider's payload (or None for cli/sdk)
        fallback_provider_payload: the remote fallback payload, or None
        provider_mode_selected: provider mode chosen by routing
        provider_selection_reason: machine-readable reason
        selected_adapter_id / selected_adapter_name
        fallback_adapter_id / fallback_adapter_name

    Rules:
        - remote_only or local_only: no fallback payload
        - local_preferred + local adapter found: attach remote fallback
        - local_preferred + no local adapter (pre-routing fallback already
          downgraded to remote_only): no runtime fallback payload
    """
    from app.services.coordinator_extensions import (
        find_adapter_for_task,
        build_provider_payload,
    )

    primary = resolve_execution_provider(db, plan, task, retry_count=retry_count)
    fallback_payload = None
    fallback_adapter_id = None
    fallback_adapter_name = None

    if (
        primary["provider_mode"] == PROVIDER_LOCAL_PREFERRED
        and not primary["fallback_occurred"]
    ):
        # Look up a remote_only adapter usable for this role.
        role = task.get("role", ROLE_WRITER)
        remote_adapter = find_adapter_for_task(
            db, role=role, provider_mode=PROVIDER_REMOTE_ONLY, capability=None
        )
        if remote_adapter is not None:
            fallback_payload = build_provider_payload(
                remote_adapter, model=task.get("model")
            )
            fallback_adapter_id = remote_adapter.adapter_id
            fallback_adapter_name = remote_adapter.name

    return {
        "provider_payload": primary["provider_payload"],
        "fallback_provider_payload": fallback_payload,
        "provider_mode_selected": primary["provider_mode"],
        "provider_selection_reason": primary["selection_reason"],
        "selected_adapter_id": primary["adapter_id"],
        "selected_adapter_name": primary["adapter_name"],
        "fallback_adapter_id": fallback_adapter_id,
        "fallback_adapter_name": fallback_adapter_name,
        "pre_routing_fallback_occurred": primary["fallback_occurred"],
    }


def resolve_execution_provider(
    db: Session,
    plan: CoordinatorPlan,
    task: Dict[str, Any],
    *,
    retry_count: int = 0,
) -> Dict[str, Any]:
    """Pick adapter + build provider_payload for one task.

    Returns a dict with keys: provider_mode, selection_reason, adapter_id,
    adapter_name, provider_payload, fallback_occurred.

    Fallback rule: if mode==local_preferred but no local adapter is available,
    we transparently fall back to remote_only and append `+fallback_no_adapter`
    to the selection reason.
    """
    from app.services.coordinator_extensions import (
        find_adapter_for_task,
        build_provider_payload,
    )

    role = task.get("role", ROLE_WRITER)
    mode, reason = route_provider_mode_with_reason(
        plan,
        role=role,
        artifact_type=task.get("expected_artifact_type", "draft"),
        impact_level=task.get("impact_level", "medium"),
        retry_count=retry_count,
        writes_files=bool(task.get("writes_files", False)),
        cheap=bool(task.get("cheap", False)),
    )

    capability = "openai_compat" if mode == PROVIDER_LOCAL_PREFERRED else None
    adapter = find_adapter_for_task(
        db, role=role, provider_mode=mode, capability=capability
    )
    fallback_occurred = False
    if adapter is None and mode == PROVIDER_LOCAL_PREFERRED:
        # No local adapter available — fall back to remote.
        mode = PROVIDER_REMOTE_ONLY
        reason = f"{reason}+fallback_no_adapter"
        fallback_occurred = True
        adapter = find_adapter_for_task(
            db, role=role, provider_mode=mode, capability=None
        )

    payload = build_provider_payload(adapter, model=task.get("model"))
    return {
        "provider_mode": mode,
        "selection_reason": reason,
        "adapter_id": adapter.adapter_id if adapter else None,
        "adapter_name": adapter.name if adapter else None,
        "provider_payload": payload,
        "fallback_occurred": fallback_occurred,
    }


# ───────────────────────────────────────────────
#  External CLI execution kind selection
#  (opt-in routing for Claude Code / Codex / Generic external CLI runtimes)
# ───────────────────────────────────────────────

EXECUTION_KIND_HTTP_PROVIDER = "http_provider"
EXECUTION_KIND_EXTERNAL_CLI = "external_cli"
EXECUTION_KIND_INTERNAL = "internal"


def _apply_step_config_to_task(task: Dict[str, Any], step_config) -> None:
    """Translate a parsed StepExecutionConfig into the legacy ad-hoc
    fields that the existing resolve_execution_kind body reads.

    This keeps the integration surgical: we don't rewrite the routing
    body, we just feed it the same shape it already understands.
    """
    exec_meta = step_config.execution
    approval = step_config.approval
    workspace = step_config.workspace

    # Map execution_kind=external_cli to the existing prefer_external_cli flag.
    if exec_meta.execution_kind == "external_cli":
        task["prefer_external_cli"] = True
        if exec_meta.cli_runtime_hint:
            task["cli_runtime_hint"] = exec_meta.cli_runtime_hint
        elif exec_meta.preferred_adapter:
            # Best-effort: derive runtime from adapter name prefix.
            name = exec_meta.preferred_adapter
            if name.startswith("claude-"):
                task["cli_runtime_hint"] = "claude_code"
            elif name.startswith("codex-"):
                task["cli_runtime_hint"] = "codex"
            elif name.startswith("generic-"):
                task["cli_runtime_hint"] = "generic"

    if exec_meta.cwd_hint:
        task.setdefault("cwd_hint", exec_meta.cwd_hint)

    # Approval policy → bundle flags consumed by external_cli_payload.
    if approval.allow_writes or approval.policy == "allow_write":
        task["writes_files"] = True
    if approval.allow_shell or approval.policy == "allow_shell":
        task["allow_shell"] = True
    # ask_before_shell: surface the policy string so the Rust runner
    # knows to emit an approval request event before spawning instead
    # of short-circuiting to read-only. The runner asks the user
    # interactively and, on approval, promotes the step to allow_shell
    # for that single execution.
    task["_approval_policy"] = approval.policy

    # Workspace allocation happens via _maybe_allocate_step_workspace below.
    # Here we just surface the metadata so the planner can decide.
    if workspace.workspace_policy != "none":
        task.setdefault("_workspace_policy", workspace.workspace_policy)
        task.setdefault("_workspace_share_with_steps", workspace.share_with_steps)

    # Stash explicit preferred adapter for downstream lookup helpers.
    if exec_meta.preferred_adapter:
        task["_preferred_adapter_name"] = exec_meta.preferred_adapter
    if exec_meta.candidate_adapters:
        task["_candidate_adapter_names"] = list(exec_meta.candidate_adapters)
    if exec_meta.required_capabilities:
        task["_step_required_capabilities"] = list(exec_meta.required_capabilities)


def _maybe_allocate_step_workspace(
    db: Session,
    plan: "CoordinatorPlan",
    task: Dict[str, Any],
    step_config,
) -> None:
    """Allocate (or share) a CoordinatorWorkspace for a step
    whose `workspace_policy` is not "none".

    Resolution order for `share_with_steps`:
    1. each step key (e.g. "step_42") is interpreted as the upstream
       task's task_id; we look up the existing workspace for that
       task_id under the same plan
    2. if found and not yet cleaned, the downstream task reuses its
       workspace_id / workspace_path
    3. otherwise a fresh workspace is reserved with the requested mode
    """
    workspace_meta = step_config.workspace
    if workspace_meta.workspace_policy == "none":
        return

    # 1. Try share_with_steps lookup.
    for upstream_task_id in workspace_meta.share_with_steps or []:
        existing = find_workspace_by_task_id(db, plan.plan_id, upstream_task_id)
        if existing is not None and existing.status != "cleaned":
            task["workspace_id"] = existing.workspace_id
            task["workspace_mode"] = existing.mode
            if existing.workspace_path:
                task["workspace_path"] = existing.workspace_path
            task["_workspace_shared_from"] = upstream_task_id
            return

    # 2. Reserve a new workspace.
    task_id = task.get("task_id") or f"task_{task.get('workflow_skill_id')}"
    ws = reserve_workspace(
        db, plan.plan_id,
        task_id=task_id,
        mode=workspace_meta.workspace_policy,
    )
    task["workspace_id"] = ws.workspace_id
    task["workspace_mode"] = ws.mode
    if ws.workspace_path:
        task["workspace_path"] = ws.workspace_path


def resolve_execution_kind(
    db: Session,
    plan: CoordinatorPlan,
    task: Dict[str, Any],
    *,
    retry_count: int = 0,
) -> Dict[str, Any]:
    """Decide whether a task should run via HTTP provider, external CLI, or
    fall back to the internal sidecar pipeline.

    Routing rules (initial — conservative, opt-in):
    1. judge tasks always go remote_only/http (hard rule from
       route_provider_mode_with_reason)
    2. if task has prefer_external_cli=true and a cli_runtime_hint
       (e.g. "claude_code"), pick the matching external_cli adapter
    3. otherwise fall through to existing resolve_execution_provider
       and return execution_kind=http_provider

    Returns a dict with:
        execution_kind, adapter_id, adapter_name, runtime,
        required_capabilities, selection_reason, provider_payload,
        external_cli_payload (one of provider_payload / external_cli_payload
        is non-None)
    """
    from app.services.coordinator_extensions import (
        find_adapter_for_task,
        list_adapters,
    )
    from app.services.external_cli_adapters import build_external_cli_payload
    from app.services.external_cli_capabilities import required_capabilities_for_task
    from app.services.workflow_step_schema import (
        StepExecutionConfig,
        is_legacy_step,
    )

    role = task.get("role", ROLE_WRITER)

    # Read step execution metadata from the task envelope.
    # worker.py attaches `_step_execution_config` (a StepExecutionConfig)
    # before calling resolve_execution_kind. Legacy rows produce a
    # default config, indistinguishable from the legacy routing path.
    step_config = task.get("_step_execution_config")
    if isinstance(step_config, StepExecutionConfig) and not is_legacy_step(step_config):
        _apply_step_config_to_task(task, step_config)
        # Allocate (or share) a CoordinatorWorkspace for steps that
        # declared workspace_policy != "none". Judge tasks are excluded
        # from external_cli below, so allocating a workspace for them
        # is harmless but pointless — we still allocate so audit
        # metadata stays consistent.
        _maybe_allocate_step_workspace(db, plan, task, step_config)

    # Hard rule: judge never goes external_cli even if opted in.
    if role == ROLE_JUDGE:
        provider_result = resolve_execution_provider(db, plan, task, retry_count=retry_count)
        return {
            "execution_kind": EXECUTION_KIND_HTTP_PROVIDER,
            "adapter_id": provider_result.get("adapter_id"),
            "adapter_name": provider_result.get("adapter_name"),
            "runtime": None,
            "required_capabilities": [],
            "selection_reason": "judge_forced_remote",
            "provider_payload": provider_result.get("provider_payload"),
            "external_cli_payload": None,
        }

    prefer_cli = bool(task.get("prefer_external_cli", False))
    cli_runtime_hint = task.get("cli_runtime_hint")  # e.g. "claude_code" / "codex"

    if prefer_cli and (cli_runtime_hint or task.get("_preferred_adapter_name")):
        # Find an enabled external_cli adapter. Resolution order:
        # 1. _preferred_adapter_name (exact name match)
        # 2. _candidate_adapter_names (in order)
        # 3. cli_runtime_hint (config.runtime match)
        adapters = list_adapters(db, only_enabled=True)
        target = None
        preferred_name = task.get("_preferred_adapter_name")
        candidate_names = task.get("_candidate_adapter_names") or []
        ordered_candidates = ([preferred_name] if preferred_name else []) + list(candidate_names)
        for name in ordered_candidates:
            for a in adapters:
                if a.transport != "external_cli":
                    continue
                if a.name == name:
                    target = a
                    break
            if target is not None:
                break
        if target is None and cli_runtime_hint:
            for a in adapters:
                if a.transport != "external_cli":
                    continue
                try:
                    cfg = json.loads(a.config or "{}")
                except json.JSONDecodeError:
                    cfg = {}
                if cfg.get("runtime") == cli_runtime_hint:
                    target = a
                    break
        if target is not None:
            # Approval policy enforcement.
            # If the step's required_capabilities exceed what the
            # selected adapter declares, fail fast before issuing the
            # bundle. The Rust capability gate would catch this too,
            # but blocking at planner-time saves a spawn round trip
            # and surfaces a clear selection_reason for audit.
            try:
                target_caps_raw = json.loads(target.capabilities or "[]")
            except json.JSONDecodeError:
                target_caps_raw = []
            target_caps = set(target_caps_raw if isinstance(target_caps_raw, list) else [])
            step_required = set(task.get("_step_required_capabilities") or [])
            # Approval policy adds implicit caps.
            if task.get("writes_files"):
                step_required.add("file_write")
            if task.get("allow_shell"):
                step_required.add("shell_exec")
            missing_caps = sorted(step_required - target_caps)
            if missing_caps:
                # Hard mismatch — fall back to http_provider with a
                # clear selection_reason so the artifact records why.
                provider_result = resolve_execution_provider(
                    db, plan, task, retry_count=retry_count
                )
                return {
                    "execution_kind": EXECUTION_KIND_HTTP_PROVIDER,
                    "adapter_id": provider_result.get("adapter_id"),
                    "adapter_name": provider_result.get("adapter_name"),
                    "runtime": None,
                    "required_capabilities": sorted(step_required),
                    "selection_reason": (
                        f"step_capability_mismatch:{target.name}:missing="
                        + ",".join(missing_caps)
                    ),
                    "provider_payload": provider_result.get("provider_payload"),
                    "external_cli_payload": None,
                }

            workspace_id = task.get("workspace_id")
            workspace_mode = task.get("workspace_mode")
            workspace_path = task.get("workspace_path")
            cwd = workspace_path or task.get("cwd_hint")
            if not cwd:
                # Without a cwd we cannot run an external CLI safely.
                # Fall through to the HTTP provider path.
                pass
            else:
                required_caps = required_capabilities_for_task(
                    role=role,
                    writes_files=bool(task.get("writes_files", False)),
                    allow_shell=bool(task.get("allow_shell", False)),
                    has_workspace=bool(workspace_id),
                    requires_local_auth=True,
                )
                payload = build_external_cli_payload(
                    target,
                    cwd=cwd,
                    prompt=task.get("prompt") or task.get("objective") or "",
                    task_id=task.get("task_id") or f"task_{task.get('workflow_skill_id')}",
                    workflow_run_id=str(plan.workflow_execution_id or plan.plan_id),
                    task_role=role,
                    allow_writes=bool(task.get("writes_files", False)),
                    allow_shell=bool(task.get("allow_shell", False)),
                    required_capabilities=required_caps,
                    workspace_id=workspace_id,
                    workspace_mode=workspace_mode,
                    approval_policy=task.get("_approval_policy"),
                )
                # Determine the runtime label even when cli_runtime_hint
                # was not explicit (preferred_adapter path).
                try:
                    target_cfg = json.loads(target.config or "{}")
                except json.JSONDecodeError:
                    target_cfg = {}
                resolved_runtime = (
                    cli_runtime_hint or target_cfg.get("runtime") or "generic"
                )
                if task.get("_preferred_adapter_name") == target.name:
                    selection_reason = f"step_pref:external_cli:{target.name}"
                elif task.get("_candidate_adapter_names"):
                    selection_reason = f"step_candidate:external_cli:{target.name}"
                else:
                    selection_reason = f"prefer_external_cli:{resolved_runtime}"
                return {
                    "execution_kind": EXECUTION_KIND_EXTERNAL_CLI,
                    "adapter_id": target.adapter_id,
                    "adapter_name": target.name,
                    "runtime": resolved_runtime,
                    "required_capabilities": required_caps,
                    "selection_reason": selection_reason,
                    "provider_payload": None,
                    "external_cli_payload": payload,
                }

    # Default path — existing HTTP/internal routing.
    provider_result = resolve_execution_provider(db, plan, task, retry_count=retry_count)
    return {
        "execution_kind": EXECUTION_KIND_HTTP_PROVIDER,
        "adapter_id": provider_result.get("adapter_id"),
        "adapter_name": provider_result.get("adapter_name"),
        "runtime": None,
        "required_capabilities": [],
        "selection_reason": provider_result.get("selection_reason"),
        "provider_payload": provider_result.get("provider_payload"),
        "external_cli_payload": None,
    }


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


def find_workspace_by_task_id(
    db: Session,
    plan_id: str,
    task_id: str,
) -> Optional[CoordinatorWorkspace]:
    """Locate an existing workspace allocated for the named
    upstream task. Used by `share_with_steps` so a downstream
    verification step inherits the same workspace as the code step.
    """
    return (
        db.query(CoordinatorWorkspace)
        .filter(
            CoordinatorWorkspace.plan_id == plan_id,
            CoordinatorWorkspace.task_id == task_id,
        )
        .order_by(CoordinatorWorkspace.created_at.desc())
        .first()
    )


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
