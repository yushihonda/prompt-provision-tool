from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy import func
from typing import List
from app.database import get_db
from app.auth import get_current_user
from app.models import Account, Skill, AccountSkill, Execution, Workflow, WorkflowSkill, WorkflowExecution, APIConfig
from app.encryption import encryption_service
from app.schemas import (
    SkillListResponse,
    ExecutionResponse,
    UserDashboardStats,
    UserWorkflowSummary,
    WorkflowListItem,
    UserWorkflowDetail,
    UserWorkflowDetailSkill,
    UserAPIConfigResponse,
    UserAPIConfigUpdate,
)
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List

router = APIRouter(prefix="/api/user", tags=["ユーザー"])
WORKFLOW_STATUS_MANUAL_REVIEW_REQUIRED = "manual_review_required"


def _load_json_safe(value, default=None):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def _get_plan_artifact_for_approval(db: Session, approval_id: str):
    from app.models import CoordinatorArtifact

    return (
        db.query(CoordinatorArtifact)
        .filter(CoordinatorArtifact.content_ref == f"approval:{approval_id}")
        .order_by(CoordinatorArtifact.id.desc())
        .first()
    )


def _extract_review_feedback(blackboard: dict | None):
    if not isinstance(blackboard, dict):
        return []
    items = []
    for key, payload in blackboard.items():
        if not isinstance(key, str) or not isinstance(payload, dict):
            continue
        if not (key.startswith("supervisor_group_") or key.startswith("judge_group_")):
            continue
        critique = str(payload.get("critique") or "").strip()
        if not critique:
            continue
        items.append({
            "source_key": key,
            "action": payload.get("action"),
            "critique": critique,
            "target_step_ids": list(payload.get("target_step_ids") or []),
            "goto_step_id": payload.get("goto_step_id"),
            "required_fixes": list(payload.get("required_fixes") or []),
        })
    return items


def _build_coordinator_view(db, wf_exec):
    """
    ワークフロー実行の現在状態から coordinator view と synthesis events を動的生成する。
    DB への追加なし — 既存の Execution レコードから全て計算する。
    """
    from app.services.agent_profiles import normalize_agent_profile

    all_execs = (
        db.query(Execution)
        .filter(Execution.workflow_execution_id == wf_exec.id)
        .order_by(Execution.id.asc())
        .all()
    )

    # 分類
    waiting_on = []
    completed_steps = []
    synthesis_events = []
    last_completed_profile = None
    last_completed_name = None

    blackboard = _load_json_safe(getattr(wf_exec, "blackboard_data", None), {}) or {}
    review_feedback = _extract_review_feedback(blackboard)

    for ex in all_execs:
        profile = normalize_agent_profile(getattr(ex, "agent_profile", None))
        role = getattr(ex, "execution_role", None)
        step_name = getattr(ex, "skill_name", None) or role or f"Step {ex.skill_order}"

        if ex.status in ("pending", "pending_local", "processing", "pending_approval"):
            waiting_on.append({
                "execution_id": ex.id,
                "step_name": step_name,
                "profile": profile,
                "role": role,
            })
        elif ex.status == "success":
            completed_steps.append(ex)
            last_completed_profile = profile
            last_completed_name = step_name

            # synthesis event 生成
            event = {
                "event_type": "step_complete",
                "execution_id": ex.id,
                "stage": profile,
                "step_name": step_name,
            }
            if role == "debate_judge":
                event["event_type"] = "judge_complete"
                event["summary"] = "並列グループの結果を合議・統合完了"
            elif role == "supervisor":
                event["event_type"] = "supervisor_decision"
                event["summary"] = "スーパーバイザーが進行判断を完了"
            elif role == "quality_gate":
                event["event_type"] = "quality_gate_pass"
                event["summary"] = "品質ゲートを通過"
            elif not ex.workflow_skill_id:
                event["event_type"] = "leader_complete"
                event["summary"] = "全結果を統合して最終出力を生成"
            else:
                output_len = len(ex.output_data) if ex.output_data else 0
                event["summary"] = f"{step_name}が完了（{output_len}文字）"

            if getattr(ex, "reflection_loop", 0) > 0:
                event["summary"] += f"（再実行{ex.reflection_loop}回目）"

            # continuation メタデータがあれば付与
            if ex.input_data:
                try:
                    inp = json.loads(ex.input_data)
                    cont = inp.get("_nexmagi_continuation")
                    if cont:
                        event["continuation_of"] = cont.get("continuation_of_execution_id")
                        event["continuation_reason"] = cont.get("continuation_reason")
                except (json.JSONDecodeError, TypeError):
                    pass

            synthesis_events.append(event)

        elif ex.status == "error":
            event = {
                "event_type": "step_error",
                "execution_id": ex.id,
                "stage": profile,
                "step_name": step_name,
                "summary": ex.error_message or "エラーが発生",
            }
            if role:
                event["event_type"] = f"{role}_error"
            synthesis_events.append(event)

    # 次のアクション推定
    if wf_exec.status == "success":
        next_action = "completed"
        latest_summary = "ワークフロー完了"
    elif wf_exec.status == "error":
        next_action = "failed"
        latest_summary = wf_exec.error_message or "エラーで停止"
    elif wf_exec.status == WORKFLOW_STATUS_MANUAL_REVIEW_REQUIRED:
        next_action = "manual_review_required"
        latest_summary = wf_exec.error_message or "人手レビュー待ちです"
    elif waiting_on:
        waiting_names = [w["step_name"] for w in waiting_on]
        if any(w["role"] == "debate_judge" for w in waiting_on):
            next_action = "waiting_for_judge"
            latest_summary = "並列結果のジャッジ合議を実行中"
        elif any(w["role"] == "quality_gate" for w in waiting_on):
            next_action = "waiting_for_quality_gate"
            latest_summary = "品質ゲート検証中"
        elif any(w["role"] == "supervisor" for w in waiting_on):
            next_action = "waiting_for_supervisor"
            latest_summary = "スーパーバイザー判定中"
        elif any(not w.get("role") and not w.get("execution_id") for w in waiting_on):
            next_action = "waiting_for_leader"
            latest_summary = "最終結果を統合中"
        else:
            next_action = "executing_steps"
            latest_summary = f"{', '.join(waiting_names)} を実行中"
    else:
        next_action = "awaiting_continuation"
        if last_completed_name:
            latest_summary = f"{last_completed_name}が完了、次のステップへ進行中"
        else:
            latest_summary = "次を準備中"

    # handoff_summary から「なぜ」の情報を抽出
    decision_why = None
    handoff_key_points = []
    handoff_next_hint = None
    if getattr(wf_exec, "handoff_summary", None):
        try:
            hs = json.loads(wf_exec.handoff_summary) if isinstance(wf_exec.handoff_summary, str) else wf_exec.handoff_summary
            if isinstance(hs, dict):
                hs_summary = hs.get("summary", "")
                handoff_key_points = hs.get("key_points", []) or []
                handoff_next_hint = hs.get("next_action_hint")
                if hs_summary:
                    decision_why = hs_summary
        except (json.JSONDecodeError, TypeError):
            pass

    # latest_summary に「なぜ」を付加
    if decision_why and latest_summary and next_action not in ("completed", "failed"):
        latest_summary = f"{latest_summary}（{decision_why[:100]}）"

    coordinator_view = {
        "current_stage": getattr(wf_exec, "current_stage", None),
        "waiting_on": [f"execution:{w['execution_id']}" for w in waiting_on],
        "waiting_details": waiting_on,
        "completed_count": len(completed_steps),
        "total_executions": len(all_execs),
        "last_decision": f"{last_completed_name} ({last_completed_profile})" if last_completed_name else None,
        "why": decision_why,
        "key_points": handoff_key_points[:5],
        "next_action_hint": handoff_next_hint,
        "next_expected_action": next_action,
        "latest_summary": latest_summary,
        "review_feedback": review_feedback,
    }

    return coordinator_view, synthesis_events


def _serialize_execution_item(db: Session, execution: Execution, *, prefetched_artifacts: dict | None = None) -> dict:
    skill_name = getattr(execution, 'skill_name_snapshot', None) or (execution.skill.name if execution.skill else None)

    workflow_name = None
    skill_display_name = None
    if execution.workflow_execution:
        workflow_name = getattr(execution.workflow_execution, 'workflow_name_snapshot', None)
        if not workflow_name:
            wf = execution.workflow_execution.workflow
            if wf:
                workflow_name = wf.name
        if execution.workflow_skill:
            skill_display_name = execution.workflow_skill.skill_name or f"Step {execution.skill_order}"

    enable_deep_think = getattr(execution, 'enable_deep_think', None)
    if enable_deep_think is None and execution.skill:
        enable_deep_think = getattr(execution.skill, 'enable_deep_think', None)
        if enable_deep_think is None:
            enable_deep_think = True

    output_format = getattr(execution, 'output_format', None)
    if output_format is None:
        output_format = 'txt'

    extra_meta = None
    try:
        if prefetched_artifacts is not None:
            art = prefetched_artifacts.get(execution.id)
        else:
            from app.models import CoordinatorArtifact
            art = (
                db.query(CoordinatorArtifact)
                .filter(CoordinatorArtifact.execution_id == execution.id)
                .order_by(CoordinatorArtifact.id.desc())
                .first()
            )
        if art and art.extra_metadata:
            try:
                extra_meta = json.loads(art.extra_metadata) if isinstance(art.extra_metadata, str) else art.extra_metadata
            except (json.JSONDecodeError, TypeError):
                extra_meta = None
    except Exception:
        extra_meta = None

    return {
        "id": execution.id,
        "account_id": execution.account_id,
        "skill_id": execution.skill_id,
        "workflow_execution_id": execution.workflow_execution_id,
        "workflow_execution_status": execution.workflow_execution.status if execution.workflow_execution else None,
        "workflow_skill_id": execution.workflow_skill_id,
        "workflow_id": execution.workflow_execution.workflow_id if execution.workflow_execution else None,
        "workflow_name": workflow_name,
        "skill_order": execution.skill_order,
        "skill_display_name": skill_display_name,
        "input_data": execution.input_data,
        "output_data": execution.output_data,
        "model_used": execution.model_used,
        "tokens_used": execution.tokens_used,
        "execution_time": execution.execution_time,
        "status": execution.status,
        "error_message": execution.error_message,
        "executed_at": execution.executed_at,
        "output_format": output_format,
        "skill_name": skill_name,
        "execution_role": getattr(execution, 'execution_role', None),
        "execution_group_id": getattr(execution, 'execution_group_id', None),
        "parallel_group_id": (execution.workflow_skill.group_id if execution.workflow_skill and execution.workflow_skill.group and execution.workflow_skill.group.execution_type == 'parallel' else None),
        "agent_profile": getattr(execution, 'agent_profile', None),
        "reflection_loop": getattr(execution, 'reflection_loop', 0),
        "enable_deep_think": bool(enable_deep_think) if enable_deep_think is not None else None,
        "dispatch_mode": getattr(execution, 'dispatch_mode', 'server'),
        "execution_kind": getattr(execution, 'execution_kind', 'http_provider'),
        "extra_metadata": extra_meta,
    }


# ==================== ダッシュボード ====================
@router.get("/dashboard", response_model=UserDashboardStats)
async def get_user_dashboard_stats(
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user)
):
    """ユーザー用ダッシュボード統計情報を取得"""
    # 利用可能なスキル数（論理削除されていないもののみ）
    available_skills = db.query(Skill).join(
        AccountSkill, Skill.id == AccountSkill.skill_id
    ).filter(
        AccountSkill.account_id == current_user.id,
        Skill.is_active == True,
        Skill.deleted_at.is_(None)
    ).count()

    # 利用可能なワークフロー数
    available_workflows = db.query(Workflow).filter(
        Workflow.is_active == True,
        Workflow.deleted_at.is_(None),
    ).count()

    # 月が変わっていたら月次カウンターをリセット
    from app.services.account_stats import check_and_reset_monthly_stats
    check_and_reset_monthly_stats(current_user, db)

    # 保存された値を取得（計算不要）
    total_tokens_this_month = current_user.tokens_this_month or 0
    total_cost_this_month = float(current_user.cost_this_month or 0.0)
    executions_this_month = current_user.executions_this_month or 0

    return {
        "available_skills": available_skills,
        "available_workflows": available_workflows,
        "executions_this_month": executions_this_month,
        "total_tokens_this_month": total_tokens_this_month,
        "total_cost_this_month": total_cost_this_month,
        "total_executions": current_user.total_executions or 0,
        "total_tokens": current_user.total_tokens or 0,
    }


@router.get("/dashboard/contribution-graph")
async def get_contribution_graph(
    year: int = None,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user)
):
    """
    GitHub風のコントリビューショングラフ用データを取得
    日ごとの実行回数を月別に返す（超軽量なdaily_execution_countsテーブルから取得）
    """
    from app.models import DailyExecutionCount
    from datetime import date

    jst = timezone(timedelta(hours=9))
    now = datetime.now(jst)

    # 年の指定がない場合は現在の年を使用
    if year is None:
        year = now.year

    # 指定年の1月1日から12月31日まで
    start_date = date(year, 1, 1)
    end_date = date(year, 12, 31)

    # 日ごとの実行回数を取得（超軽量）
    daily_counts = db.query(DailyExecutionCount).filter(
        DailyExecutionCount.account_id == current_user.id,
        DailyExecutionCount.date >= start_date,
        DailyExecutionCount.date <= end_date
    ).all()

    # 日ごとの実行回数をマップに変換
    count_map = {str(dc.date): dc.count for dc in daily_counts}

    # 月別にグループ化
    result: Dict[str, List[Dict]] = {}

    # 指定年のすべての日を生成（空の日も含める）
    current_date = start_date
    while current_date <= end_date:
        # 月のキー（YYYY-MM形式）
        month_key = current_date.strftime("%Y-%m")
        day_key = current_date.strftime("%Y-%m-%d")

        if month_key not in result:
            result[month_key] = []

        # 実行回数を取得（存在しない場合は0）
        count = count_map.get(day_key, 0)

        result[month_key].append({
            "date": day_key,
            "count": count
        })

        # 次の日へ
        current_date = current_date + timedelta(days=1)

    # 各月の日データをソート
    for month_key in result:
        result[month_key].sort(key=lambda x: x["date"])

    return result


@router.get("/skills")
async def list_available_skills(
    skip: int = 0,
    limit: int = 6,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user)
):
    limit = min(limit, 100)
    """
    現在のユーザーが利用可能なスキル一覧を取得（ページネーション対応）

    注意: スキルの内容は含まれない（セキュリティ）
    """
    # 総件数を取得（論理削除されていないもののみ）
    total = db.query(Skill).join(
        AccountSkill, Skill.id == AccountSkill.skill_id
    ).filter(
        AccountSkill.account_id == current_user.id,
        Skill.is_active == True,
        Skill.deleted_at.is_(None)
    ).count()

    skills = db.query(Skill).join(
        AccountSkill, Skill.id == AccountSkill.skill_id
    ).filter(
        AccountSkill.account_id == current_user.id,
        Skill.is_active == True,
        Skill.deleted_at.is_(None)
    ).order_by(Skill.created_at.desc()).offset(skip).limit(limit).all()

    # input_schemaをJSON形式にパース
    items = []
    for skill in skills:
        # enable_deep_thinkがNoneの場合はデフォルト値Trueを使用
        enable_deep_think = getattr(skill, "enable_deep_think", True)
        if enable_deep_think is None:
            enable_deep_think = True

        cfg_out = None
        if getattr(skill, "config_json", None):
            try:
                cfg_out = json.loads(skill.config_json) if isinstance(skill.config_json, str) else skill.config_json
            except (json.JSONDecodeError, TypeError):
                cfg_out = None

        skill_dict = {
            "id": skill.id,
            "name": skill.name,
            "description": skill.description,
            "model_type": skill.model_type,
            "allows_file_output": skill.allows_file_output,
            "enable_deep_think": bool(enable_deep_think),  # 明示的にboolに変換
            "config_json": cfg_out,
        }
        items.append(skill_dict)

    return {
        "items": items,
        "total": total,
        "skip": skip,
        "limit": limit
    }


@router.get("/skills/{skill_id}")
async def get_skill_detail(
    skill_id: int,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user)
):
    """
    特定のスキルの詳細情報を取得

    注意: スキルの内容は含まれない（セキュリティ）
    input_schemaのみ返す（入力フォームの構築用）
    """
    # スキルの存在確認（論理削除されていないもののみ）
    skill = db.query(Skill).filter(Skill.id == skill_id, Skill.deleted_at.is_(None)).first()
    if not skill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="スキルが見つかりません"
        )

    # アクセス権限の確認
    assignment = db.query(AccountSkill).filter(
        AccountSkill.account_id == current_user.id,
        AccountSkill.skill_id == skill_id
    ).first()

    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="このスキルへのアクセス権限がありません"
        )

    # input_schemaをパース
    input_schema = None
    if skill.input_schema:
        try:
            input_schema = json.loads(skill.input_schema)
        except (json.JSONDecodeError, TypeError):
            input_schema = None

    # enable_deep_thinkがNoneの場合はデフォルト値Trueを使用
    enable_deep_think = getattr(skill, "enable_deep_think", True)
    if enable_deep_think is None:
        enable_deep_think = True

    cfg_out = None
    if getattr(skill, "config_json", None):
        try:
            cfg_out = json.loads(skill.config_json) if isinstance(skill.config_json, str) else skill.config_json
        except (json.JSONDecodeError, TypeError):
            cfg_out = None

    return {
        "id": skill.id,
        "name": skill.name,
        "description": skill.description,
        "model_type": skill.model_type,
        "input_schema": input_schema,
        "allows_file_output": skill.allows_file_output,
        "enable_deep_think": bool(enable_deep_think),
        "config_json": cfg_out,
    }


@router.get("/workflows")
async def list_user_workflows(
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user),
):
    """
    現在のユーザーが利用可能なワークフローと、その中のスキル一覧を取得
    """
    # このユーザーに割り当てられているスキルID
    assigned_skill_ids_subq = (
        db.query(AccountSkill.skill_id)
        .filter(AccountSkill.account_id == current_user.id)
        .subquery()
    )

    # 利用可能なワークフローを取得（ワークフロー自体が有効 + 論理削除されていない）
    workflows = (
        db.query(Workflow)
        .join(WorkflowSkill, Workflow.id == WorkflowSkill.workflow_id)
        .filter(
            Workflow.deleted_at.is_(None),
            Workflow.is_active == True,  # noqa: E712
            WorkflowSkill.skill_id.in_(assigned_skill_ids_subq),
        )
        .distinct()
        .all()
    )

    result: List[UserWorkflowSummary] = []

    for wf in workflows:
        # ワークフロー内のSkillを順番に取得（このユーザーに割り当て済みのスキルのみ）
        wf_skills = (
            db.query(WorkflowSkill)
            .join(Skill, Skill.id == WorkflowSkill.skill_id)
            .filter(
                WorkflowSkill.workflow_id == wf.id,
                WorkflowSkill.skill_id.in_(assigned_skill_ids_subq),
                Skill.deleted_at.is_(None),
                Skill.is_active == True,  # noqa: E712
            )
            .order_by(WorkflowSkill.skill_order.asc(), WorkflowSkill.id.asc())
            .all()
        )

        skill_list: List[SkillListResponse] = []
        for ws in wf_skills:
            s = ws.skill
            if not s:
                continue

            # enable_deep_thinkがNoneの場合はデフォルト値Trueを使用
            enable_deep_think = getattr(s, "enable_deep_think", True)
            if enable_deep_think is None:
                enable_deep_think = True

            skill_list.append(
                SkillListResponse(
                    id=s.id,
                    name=s.name,
                    description=s.description,
                    model_type=s.model_type,
                    allows_file_output=s.allows_file_output,
                    enable_deep_think=bool(enable_deep_think),
                )
            )

        # input_schemaをJSONから辞書に変換
        workflow_input_schema = None
        if wf.input_schema:
            try:
                workflow_input_schema = json.loads(wf.input_schema) if isinstance(wf.input_schema, str) else wf.input_schema
            except (json.JSONDecodeError, TypeError):
                workflow_input_schema = None

        # ステップ順の agent_profile 一覧
        step_profiles = []
        for ws in wf_skills:
            p = ws.agent_profile or (ws.skill.default_agent_profile if ws.skill else None) or "default"
            step_profiles.append(p)

        # グループごとの実行タイプとステップ数
        from app.models import WorkflowGroup
        from app.schemas import StepGroupInfo
        groups = (
            db.query(WorkflowGroup)
            .filter(WorkflowGroup.workflow_id == wf.id)
            .order_by(WorkflowGroup.group_order.asc())
            .all()
        )
        step_groups = []
        if groups:
            for g in groups:
                skill_count = len([s for s in g.skills if s.skill_id in {ws.skill_id for ws in wf_skills}])
                if skill_count > 0:
                    step_groups.append(StepGroupInfo(execution_type=g.execution_type or "serial", count=skill_count))
        else:
            # グループ未定義の場合は全ステップを直列1グループとして扱う
            step_groups = [StepGroupInfo(execution_type="serial", count=len(wf_skills))]

        wf_cfg_out = None
        if getattr(wf, "config_json", None):
            try:
                wf_cfg_out = json.loads(wf.config_json) if isinstance(wf.config_json, str) else wf.config_json
            except (json.JSONDecodeError, TypeError):
                wf_cfg_out = None

        result.append(
            UserWorkflowSummary(
                workflow=WorkflowListItem(
                    id=wf.id,
                    name=wf.name,
                    description=wf.description,
                    is_active=wf.is_active,
                    parent_model_type=wf.parent_model_type,
                    config_json=wf_cfg_out,
                    created_at=wf.created_at,
                    updated_at=wf.updated_at,
                ),
                skills=skill_list,
                step_profiles=step_profiles,
                step_groups=step_groups,
            )
        )

    return result


@router.get("/workflows/{workflow_id}", response_model=UserWorkflowDetail)
async def get_user_workflow_detail(
    workflow_id: int,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user),
):
    """
    特定のワークフローの詳細情報と、その中のスキル一覧を取得
    """
    # このユーザーに割り当てられているスキルID
    assigned_skill_ids_subq = (
        db.query(AccountSkill.skill_id)
        .filter(AccountSkill.account_id == current_user.id)
        .subquery()
    )

    # ワークフローの取得（有効 & 論理削除されていないもののみ）
    wf = (
        db.query(Workflow)
        .filter(
            Workflow.id == workflow_id,
            Workflow.deleted_at.is_(None),
            Workflow.is_active == True,  # noqa: E712
        )
        .first()
    )
    if not wf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ワークフローが見つかりません",
        )

    # このユーザーが利用できるSkillのみ取得
    wf_skills = (
        db.query(WorkflowSkill)
        .join(Skill, Skill.id == WorkflowSkill.skill_id)
        .filter(
            WorkflowSkill.workflow_id == wf.id,
            WorkflowSkill.skill_id.in_(assigned_skill_ids_subq),
            Skill.deleted_at.is_(None),
            Skill.is_active == True,  # noqa: E712
        )
        .order_by(WorkflowSkill.skill_order.asc(), WorkflowSkill.id.asc())
        .all()
    )

    def _parse_cfg(raw):
        if not raw:
            return None
        if isinstance(raw, dict):
            return raw
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    skills: List[UserWorkflowDetailSkill] = []
    for ws in wf_skills:
        s = ws.skill
        if not s:
            continue
        edt = getattr(s, "enable_deep_think", True)
        if edt is None:
            edt = True
        skills.append(
            UserWorkflowDetailSkill(
                workflow_skill_id=ws.id,
                skill_order=ws.skill_order,
                skill_name=ws.skill_name,
                skill_id=s.id,
                skill_display_name=s.name,
                agent_profile=getattr(ws, "agent_profile", None),
                model_type=s.model_type,
                enable_deep_think=bool(edt),
                config_json=_parse_cfg(getattr(ws, "config_json", None)),
                skill_config_json=_parse_cfg(getattr(s, "config_json", None)),
            )
        )

    if not skills:
        # ワークフロー自体は存在するが、このユーザーが利用できるSkillがない場合
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="このワークフローで利用可能なスキルがありません",
        )

    # input_schemaをJSONから辞書に変換
    workflow_input_schema = None
    if wf.input_schema:
        try:
            workflow_input_schema = json.loads(wf.input_schema) if isinstance(wf.input_schema, str) else wf.input_schema
        except (json.JSONDecodeError, TypeError):
            workflow_input_schema = None

    # グループ情報を構築
    from app.models import WorkflowGroup
    groups_data = []
    db_groups = (
        db.query(WorkflowGroup)
        .filter(WorkflowGroup.workflow_id == wf.id)
        .order_by(WorkflowGroup.group_order.asc())
        .all()
    )
    for grp in db_groups:
        grp_skills = []
        for ws in sorted(grp.skills, key=lambda s: s.order_in_group or s.skill_order or 0):
            s = ws.skill
            if s:
                input_mapping_parsed = None
                if ws.input_mapping:
                    try:
                        input_mapping_parsed = json.loads(ws.input_mapping) if isinstance(ws.input_mapping, str) else ws.input_mapping
                    except (json.JSONDecodeError, TypeError):
                        pass
                edt = getattr(s, "enable_deep_think", True)
                if edt is None:
                    edt = True
                grp_skills.append({
                    "skill_id": s.id,
                    "skill_name": s.name,
                    "model_type": s.model_type,
                    "order_in_group": ws.order_in_group or ws.skill_order or 0,
                    "skill_display_name": ws.skill_name or s.name,
                    "workflow_skill_id": ws.id,
                    "skill_order": ws.skill_order,
                    "input_mapping": input_mapping_parsed,
                    "agent_profile": getattr(ws, "agent_profile", None),
                    "enable_deep_think": bool(edt),
                    # ステップ単位の execution_config オーバーライド。フロントエンドが
                    # 各ノードの実効ランタイムを解決できるようにする。
                    "config_json": _parse_cfg(getattr(ws, "config_json", None)),
                })
        groups_data.append({
            "id": grp.id,
            "group_order": grp.group_order,
            "group_name": grp.group_name,
            "execution_type": grp.execution_type,
            # グループ単位の execution_config デフォルト（継承チェーン用）。
            "config_json": _parse_cfg(getattr(grp, "config_json", None)),
            "skills": grp_skills,
        })

    wf_item = WorkflowListItem(
        id=wf.id,
        name=wf.name,
        description=wf.description,
        is_active=wf.is_active,
        parent_model_type=wf.parent_model_type,
        # ワークフロー単位の execution_config（継承チェーンの最上位）。
        config_json=_parse_cfg(getattr(wf, "config_json", None)),
        created_at=wf.created_at,
        updated_at=wf.updated_at,
        groups=groups_data,
    )

    return UserWorkflowDetail(
        workflow=wf_item,
        skills=skills,
        input_schema=workflow_input_schema,
        current_stage=None,
        final_verdict=None,
        handoff_summary=None,
    )


@router.get("/executions")
async def list_my_executions(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user)
):
    """
    自分の実行履歴を取得
    """
    limit = min(limit, 100)
    # 総件数を取得
    total = db.query(Execution).filter(
        Execution.account_id == current_user.id
    ).count()

    # eager loading で N+1 クエリを回避
    executions = (
        db.query(Execution)
        .options(
            joinedload(Execution.skill),
            joinedload(Execution.workflow_execution).joinedload(WorkflowExecution.workflow),
            joinedload(Execution.workflow_skill),
        )
        .filter(Execution.account_id == current_user.id)
        .order_by(Execution.executed_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    # CoordinatorArtifact を一括取得して N+1 回避
    from app.models import CoordinatorArtifact
    exec_ids = [e.id for e in executions]
    artifact_map: dict = {}
    if exec_ids:
        from sqlalchemy import func as sa_func
        latest_ids_subq = (
            db.query(sa_func.max(CoordinatorArtifact.id))
            .filter(CoordinatorArtifact.execution_id.in_(exec_ids))
            .group_by(CoordinatorArtifact.execution_id)
            .subquery()
        )
        arts = db.query(CoordinatorArtifact).filter(CoordinatorArtifact.id.in_(latest_ids_subq)).all()
        for a in arts:
            artifact_map[a.execution_id] = a

    items = []
    for execution in executions:
        items.append(_serialize_execution_item(db, execution, prefetched_artifacts=artifact_map))

    return {
        "items": items,
        "total": total,
        "skip": skip,
        "limit": limit
    }


@router.get("/workflow-executions/{wf_execution_id}/executions")
async def list_workflow_execution_items(
    wf_execution_id: int,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user),
):
    wf_exec = db.query(WorkflowExecution).filter(
        WorkflowExecution.id == wf_execution_id,
        WorkflowExecution.account_id == current_user.id,
    ).first()
    if not wf_exec:
        raise HTTPException(status_code=404, detail="ワークフロー実行が見つかりません")

    executions = (
        db.query(Execution)
        .options(
            joinedload(Execution.skill),
            joinedload(Execution.workflow_execution).joinedload(WorkflowExecution.workflow),
            joinedload(Execution.workflow_skill),
        )
        .filter(
            Execution.account_id == current_user.id,
            Execution.workflow_execution_id == wf_execution_id,
        )
        .order_by(Execution.id.asc())
        .all()
    )

    # CoordinatorArtifact を一括取得して N+1 回避
    from app.models import CoordinatorArtifact
    exec_ids = [e.id for e in executions]
    artifact_map: dict = {}
    if exec_ids:
        from sqlalchemy import func as sa_func
        latest_ids_subq = (
            db.query(sa_func.max(CoordinatorArtifact.id))
            .filter(CoordinatorArtifact.execution_id.in_(exec_ids))
            .group_by(CoordinatorArtifact.execution_id)
            .subquery()
        )
        arts = db.query(CoordinatorArtifact).filter(CoordinatorArtifact.id.in_(latest_ids_subq)).all()
        for a in arts:
            artifact_map[a.execution_id] = a

    return {
        "items": [_serialize_execution_item(db, execution, prefetched_artifacts=artifact_map) for execution in executions],
        "workflow_execution_id": wf_execution_id,
    }


@router.get("/workflow-executions/{wf_execution_id}/status")
async def get_workflow_execution_status(
    wf_execution_id: int,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user)
):
    """ワークフロー実行のステータスを取得（coordinator view 付き）"""
    wf_exec = db.query(WorkflowExecution).filter(
        WorkflowExecution.id == wf_execution_id,
        WorkflowExecution.account_id == current_user.id,
    ).first()
    if not wf_exec:
        raise HTTPException(status_code=404, detail="ワークフロー実行が見つかりません")
    blackboard_keys = []
    blackboard = {}
    if wf_exec.blackboard_data:
        try:
            blackboard = json.loads(wf_exec.blackboard_data)
            blackboard_keys = list(blackboard.keys())
        except (json.JSONDecodeError, TypeError):
            pass

    handoff_summary = None
    if getattr(wf_exec, "handoff_summary", None):
        try:
            handoff_summary = json.loads(wf_exec.handoff_summary) if isinstance(wf_exec.handoff_summary, str) else wf_exec.handoff_summary
        except (json.JSONDecodeError, TypeError):
            handoff_summary = None

    # coordinator view は動的計算、synthesis_events はDB優先
    coordinator_view, computed_events = _build_coordinator_view(db, wf_exec)
    # DB に保存済みの synthesis_log があればそれを使う（タイムスタンプ付き）
    synthesis_events = computed_events
    if getattr(wf_exec, "synthesis_log", None):
        try:
            db_events = json.loads(wf_exec.synthesis_log)
            if isinstance(db_events, list) and len(db_events) > 0:
                synthesis_events = db_events
        except (json.JSONDecodeError, TypeError):
            pass

    return {
        "id": wf_exec.id,
        "status": wf_exec.status,
        "error_message": wf_exec.error_message,
        "current_step": wf_exec.current_step,
        "total_steps": wf_exec.total_steps,
        "current_stage": getattr(wf_exec, "current_stage", None),
        "final_verdict": getattr(wf_exec, "final_verdict", None),
        "handoff_summary": handoff_summary,
        "blackboard_keys": blackboard_keys,
        "review_feedback": _extract_review_feedback(blackboard),
        "coordinator_view": coordinator_view,
        "synthesis_events": synthesis_events,
    }


@router.get("/workflow-executions/{wf_execution_id}/approvals")
async def get_workflow_execution_approvals(
    wf_execution_id: int,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user),
):
    """承認リクエスト一覧を返す。"""
    from app.services.approval_service import get_approvals_for_execution
    wf_exec = db.query(WorkflowExecution).filter(
        WorkflowExecution.id == wf_execution_id,
        WorkflowExecution.account_id == current_user.id,
    ).first()
    if not wf_exec:
        raise HTTPException(status_code=404, detail="ワークフロー実行が見つかりません")
    approvals = get_approvals_for_execution(db, wf_execution_id)
    items = []
    for a in approvals:
        plan_artifact = None
        if a.approval_policy == "plan_required":
            art = _get_plan_artifact_for_approval(db, a.approval_id)
            if art:
                plan_artifact = {
                    "artifact_id": art.artifact_id,
                    "summary": art.summary,
                    "content": art.inline_content,
                    "extra_metadata": _load_json_safe(art.extra_metadata, {}),
                }
        items.append({
            "approval_id": a.approval_id,
            "session_id": a.session_id,
            "step_id": a.step_id,
            "adapter_id": a.adapter_id,
            "runtime": a.runtime,
            "approval_policy": a.approval_policy,
            "status": a.status,
            "prompt_preview": a.prompt_preview,
            "cwd": a.cwd,
            "decided_by": a.decided_by,
            "decided_at": a.decided_at.isoformat() if a.decided_at else None,
            "attempt_no": a.attempt_no,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "plan_artifact": plan_artifact,
        })
    return {"approvals": items}


@router.post("/workflow-executions/{wf_execution_id}/approvals/{approval_id}/respond")
async def respond_to_approval(
    wf_execution_id: int,
    approval_id: str,
    decision: str = "granted",
    decided_by: str = None,
    step_id: str = None,
    adapter_id: str = None,
    runtime: str = None,
    approval_policy: str = "ask_before_shell",
    prompt_preview: str = None,
    cwd: str = None,
    comment: str = None,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user),
):
    """承認リクエストに応答する（granted/rejected）。冪等。

    Tauri フロー: バックエンドに承認リクエストが未作成の場合は
    作成と解決を同時に行う。
    """
    from app.services.approval_service import resolve_approval, create_and_resolve_approval
    from app.models import ApprovalRequest as _AR

    actor = decided_by or getattr(current_user, "email", None) or "user"

    wf_exec = db.query(WorkflowExecution).filter(
        WorkflowExecution.id == wf_execution_id,
        WorkflowExecution.account_id == current_user.id,
    ).first()
    if not wf_exec:
        raise HTTPException(status_code=404, detail="ワークフロー実行が見つかりません")

    existing = db.query(_AR).filter(_AR.approval_id == approval_id).first()

    if not existing:
        result = create_and_resolve_approval(
            db,
            approval_id=approval_id,
            decision=decision,
            decided_by=actor,
            session_id=wf_exec.session_id,
            plan_id=wf_exec.coordinator_plan_id,
            step_id=step_id,
            workflow_execution_id=wf_execution_id,
            adapter_id=adapter_id,
            runtime=runtime,
            approval_policy=approval_policy,
            prompt_preview=prompt_preview,
            cwd=cwd,
            decision_comment=comment,
        )
    else:
        result = resolve_approval(
            db,
            approval_id,
            decision=decision,
            decided_by=actor,
            decision_comment=comment,
        )

    if not result:
        raise HTTPException(status_code=404, detail="承認リクエストが見つかりません")

    if result.approval_policy == "plan_required" and result.execution_id:
        target_execution = db.query(Execution).filter(
            Execution.id == result.execution_id,
            Execution.workflow_execution_id == wf_execution_id,
        ).first()
        plan_artifact = _get_plan_artifact_for_approval(db, result.approval_id)
        if plan_artifact:
            meta = _load_json_safe(plan_artifact.extra_metadata, {}) or {}
            meta["status"] = result.status
            meta["decided_by"] = actor
            if comment:
                meta["decision_comment"] = comment
            plan_artifact.extra_metadata = json.dumps(meta, ensure_ascii=False)
            db.add(plan_artifact)
        if target_execution:
            if result.status == "granted" and target_execution.status == "pending_approval":
                target_execution.status = "pending_local"
                db.add(target_execution)
                db.commit()
            elif result.status in {"rejected", "timed_out"} and target_execution.status == "pending_approval":
                target_execution.status = "error"
                target_execution.error_message = (
                    "Plan approval rejected by user"
                    if result.status == "rejected"
                    else "Plan approval timed out"
                )
                db.add(target_execution)
                db.commit()
                from app.tasks.execution_tasks import continue_workflow_execution
                continue_workflow_execution(wf_execution_id, target_execution.skill_order or 0)

    return {
        "approval_id": result.approval_id,
        "status": result.status,
        "decided_by": result.decided_by,
        "decided_at": result.decided_at.isoformat() if result.decided_at else None,
    }


@router.post("/workflow-executions/{wf_execution_id}/approvals/{approval_id}/resubmit-plan")
async def resubmit_plan_approval(
    wf_execution_id: int,
    approval_id: str,
    updated_content: str,
    updated_summary: str = None,
    resubmitted_by: str = None,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user),
):
    """差し戻された plan_required 承認を新しい承認リクエストとして再提出する。"""
    from app.models import ApprovalRequest as _AR, CoordinatorArtifact
    from app.services.approval_service import create_approval_request

    wf_exec = db.query(WorkflowExecution).filter(
        WorkflowExecution.id == wf_execution_id,
        WorkflowExecution.account_id == current_user.id,
    ).first()
    if not wf_exec:
        raise HTTPException(status_code=404, detail="ワークフロー実行が見つかりません")

    existing = db.query(_AR).filter(
        _AR.approval_id == approval_id,
        _AR.workflow_execution_id == wf_execution_id,
    ).first()
    if not existing or existing.approval_policy != "plan_required":
        raise HTTPException(status_code=404, detail="plan approval が見つかりません")

    target_execution = db.query(Execution).filter(
        Execution.id == existing.execution_id,
        Execution.workflow_execution_id == wf_execution_id,
    ).first()
    if not target_execution:
        raise HTTPException(status_code=404, detail="対象 Execution が見つかりません")

    actor = resubmitted_by or getattr(current_user, "email", None) or "user"
    prompt_preview = updated_summary or existing.prompt_preview or "更新された実行計画"
    new_req = create_approval_request(
        db,
        session_id=wf_exec.session_id,
        plan_id=wf_exec.coordinator_plan_id,
        step_id=existing.step_id,
        execution_id=existing.execution_id,
        workflow_execution_id=wf_execution_id,
        adapter_id=existing.adapter_id,
        runtime=existing.runtime,
        approval_policy="plan_required",
        prompt_preview=prompt_preview,
        cwd=existing.cwd,
        attempt_no=(existing.attempt_no or 1) + 1,
    )

    target_execution.status = "pending_approval"
    target_execution.error_message = None
    db.add(target_execution)

    if wf_exec.coordinator_plan_id:
        from app.services.coordinator_service import record_artifact

        latest_art = _get_plan_artifact_for_approval(db, approval_id)
        role = (latest_art.role if latest_art else "writer")
        artifact_type = (latest_art.artifact_type if latest_art else "draft")
        prev_meta = _load_json_safe(latest_art.extra_metadata, {}) if latest_art else {}
        revision_count = int((prev_meta or {}).get("revision_count", 0)) + 1
        record_artifact(
            db,
            wf_exec.coordinator_plan_id,
            existing.step_id or f"task_{target_execution.workflow_skill_id}",
            role,
            artifact_type,
            execution_id=target_execution.id,
            summary=prompt_preview,
            inline_content=updated_content,
            content_ref=f"approval:{new_req.approval_id}",
            model_hint=target_execution.model_used,
            extra_metadata={
                "artifact_subtype": "execution_plan",
                "approval_id": new_req.approval_id,
                "approval_policy": "plan_required",
                "status": "pending",
                "resubmitted_by": actor,
                "previous_approval_id": approval_id,
                "revision_count": revision_count,
            },
        )
    db.commit()

    return {
        "approval_id": new_req.approval_id,
        "status": new_req.status,
        "attempt_no": new_req.attempt_no,
    }


@router.get("/workflow-executions/{wf_execution_id}/session")
async def get_workflow_execution_session(
    wf_execution_id: int,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user),
):
    """WorkflowRunSession の状態を返す。session_id 未設定（レガシー実行）の場合は null を返す。"""
    from app.services.session_service import get_session_state
    wf_exec = db.query(WorkflowExecution).filter(
        WorkflowExecution.id == wf_execution_id,
        WorkflowExecution.account_id == current_user.id,
    ).first()
    if not wf_exec:
        raise HTTPException(status_code=404, detail="ワークフロー実行が見つかりません")
    state = get_session_state(db, wf_exec)
    return {"session": state}


@router.get("/workflow-executions/{wf_execution_id}/events")
async def get_workflow_execution_events(
    wf_execution_id: int,
    namespace: str = None,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user),
):
    """正規化セッションイベントを返す。namespace でフィルタ可能。"""
    from app.models import CoordinatorEvent
    wf_exec = db.query(WorkflowExecution).filter(
        WorkflowExecution.id == wf_execution_id,
        WorkflowExecution.account_id == current_user.id,
    ).first()
    if not wf_exec:
        raise HTTPException(status_code=404, detail="ワークフロー実行が見つかりません")
    if not wf_exec.session_id:
        return {"events": [], "session_id": None}

    q = db.query(CoordinatorEvent).filter(
        CoordinatorEvent.session_id == wf_exec.session_id,
    )
    if namespace:
        q = q.filter(CoordinatorEvent.event_namespace == namespace)
    q = q.order_by(CoordinatorEvent.event_seq.asc().nullslast(), CoordinatorEvent.occurred_at.asc())
    rows = q.all()

    events = []
    for r in rows:
        payload = None
        if r.payload:
            try:
                payload = json.loads(r.payload)
            except (json.JSONDecodeError, TypeError):
                payload = r.payload
        events.append({
            "id": r.id,
            "event_type": r.event_type,
            "event_namespace": r.event_namespace,
            "event_seq": r.event_seq,
            "session_id": r.session_id,
            "step_id": r.step_id,
            "task_id": r.task_id,
            "artifact_id": r.artifact_id,
            "payload": payload,
            "schema_version": r.schema_version,
            "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
        })
    return {"events": events, "session_id": wf_exec.session_id}


@router.get("/executions/{execution_id}", response_model=ExecutionResponse)
async def get_execution_detail(
    execution_id: int,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user)
):
    """
    特定の実行履歴の詳細を取得
    """
    execution = db.query(Execution).filter(
        Execution.id == execution_id,
        Execution.account_id == current_user.id
    ).first()

    if not execution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="実行履歴が見つかりません"
        )

    # スキル名（スナップショット優先、なければ現在のスキル名）
    skill_name = getattr(execution, 'skill_name_snapshot', None) or (execution.skill.name if execution.skill else None)

    # ワークフロー情報（スナップショット優先）
    workflow_name = None
    skill_display_name = None
    wf_exec = None
    if execution.workflow_execution_id:
        wf_exec = db.query(WorkflowExecution).filter(
            WorkflowExecution.id == execution.workflow_execution_id
        ).first()
        if wf_exec:
            workflow_name = getattr(wf_exec, 'workflow_name_snapshot', None)
            if not workflow_name:
                workflow = db.query(Workflow).filter(
                    Workflow.id == wf_exec.workflow_id
                ).first()
                if workflow:
                    workflow_name = workflow.name
        # ステップ名
        if execution.workflow_skill_id:
            wf_skill = db.query(WorkflowSkill).filter(
                WorkflowSkill.id == execution.workflow_skill_id
            ).first()
            if wf_skill:
                skill_display_name = wf_skill.skill_name or f"Step {execution.skill_order}"

    # 実行時に保存されたenable_deep_thinkを使用（実行時点の状態を保持）
    # 保存されていない場合はスキルの設定を参照（後方互換性のため）
    enable_deep_think = getattr(execution, "enable_deep_think", None)
    if enable_deep_think is None and execution.skill:
        enable_deep_think = getattr(execution.skill, "enable_deep_think", None)
        if enable_deep_think is None:
            enable_deep_think = True  # デフォルト値

    # output_formatを取得（モデルから直接取得）
    output_format = getattr(execution, "output_format", None)
    if output_format is None:
        output_format = "txt"  # デフォルト値

    # coordinator_artifacts からの来歴 / ランタイムメタデータ
    detail_extra_meta = None
    try:
        from app.models import CoordinatorArtifact
        art = (
            db.query(CoordinatorArtifact)
            .filter(CoordinatorArtifact.execution_id == execution.id)
            .order_by(CoordinatorArtifact.id.desc())
            .first()
        )
        if art and art.extra_metadata:
            try:
                detail_extra_meta = json.loads(art.extra_metadata) if isinstance(art.extra_metadata, str) else art.extra_metadata
            except (json.JSONDecodeError, TypeError):
                detail_extra_meta = None
    except Exception:  # noqa: BLE001
        detail_extra_meta = None

    return ExecutionResponse(
        id=execution.id,
        account_id=execution.account_id,
        skill_id=execution.skill_id,
        skill_name=skill_name,
        workflow_execution_id=execution.workflow_execution_id,
        workflow_execution_status=wf_exec.status if wf_exec else None,
        workflow_skill_id=execution.workflow_skill_id,
        workflow_id=wf_exec.workflow_id if wf_exec else None,
        skill_order=execution.skill_order,
        workflow_name=workflow_name,
        skill_display_name=skill_display_name,
        input_data=execution.input_data,
        output_data=execution.output_data,
        model_used=execution.model_used,
        tokens_used=execution.tokens_used,
        execution_time=execution.execution_time,
        status=execution.status,
        error_message=execution.error_message,
        output_format=output_format,
        execution_role=getattr(execution, 'execution_role', None),
        agent_profile=getattr(execution, 'agent_profile', None),
        executed_at=execution.executed_at,
        enable_deep_think=bool(enable_deep_think) if enable_deep_think is not None else None,
        extra_metadata=detail_extra_meta,
    )


# ───────────────────────────────────────────────
#  ユーザー API キー設定
# ───────────────────────────────────────────────

@router.get("/settings/api-config", response_model=UserAPIConfigResponse)
async def get_api_config(
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user),
):
    """自分のAPI設定をマスク表示で取得"""
    config = db.query(APIConfig).filter(APIConfig.account_id == current_user.id).first()
    if not config:
        return UserAPIConfigResponse()

    def _mask(encrypted_key):
        if not encrypted_key:
            return None
        try:
            raw = encryption_service.decrypt_api_key(encrypted_key)
            return encryption_service.mask_api_key(raw) if raw else None
        except Exception:
            return None

    return UserAPIConfigResponse(
        openai_api_key=_mask(config.openai_api_key),
        gemini_api_key=_mask(config.gemini_api_key),
        anthropic_api_key=_mask(config.anthropic_api_key),
        is_enabled=config.is_enabled,
        rate_limit_per_hour=config.rate_limit_per_hour or 100,
        rate_limit_per_day=config.rate_limit_per_day or 1000,
    )


@router.patch("/settings/api-config", response_model=UserAPIConfigResponse)
async def update_api_config(
    body: UserAPIConfigUpdate,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user),
):
    """自分のAPIキーを更新（upsert）"""
    config = db.query(APIConfig).filter(APIConfig.account_id == current_user.id).first()
    if not config:
        config = APIConfig(account_id=current_user.id)
        db.add(config)

    for field in ("openai_api_key", "gemini_api_key", "anthropic_api_key"):
        value = getattr(body, field)
        if value is not None:
            stripped = value.strip()
            setattr(config, field, encryption_service.encrypt_api_key(stripped) if stripped else None)

    db.commit()
    db.refresh(config)

    def _mask(encrypted_key):
        if not encrypted_key:
            return None
        try:
            raw = encryption_service.decrypt_api_key(encrypted_key)
            return encryption_service.mask_api_key(raw) if raw else None
        except Exception:
            return None

    return UserAPIConfigResponse(
        openai_api_key=_mask(config.openai_api_key),
        gemini_api_key=_mask(config.gemini_api_key),
        anthropic_api_key=_mask(config.anthropic_api_key),
        is_enabled=config.is_enabled,
        rate_limit_per_hour=config.rate_limit_per_hour or 100,
        rate_limit_per_day=config.rate_limit_per_day or 1000,
    )


# ───────────────────────────────────────────────
#  Coordinator — plan / artifacts / events / workers / DAG
# ───────────────────────────────────────────────

@router.get("/coordinator/plans/{workflow_execution_id}")
async def get_coordinator_plan(
    workflow_execution_id: int,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user),
):
    """指定ワークフロー実行に紐付く CoordinatorPlan を取得"""
    from app.services.coordinator_service import (
        get_plan_by_workflow_execution,
        get_artifacts_for_plan,
        get_events_for_plan,
        get_workers_for_plan,
        get_followup_tasks_for_plan,
        get_workspaces_for_plan,
        build_task_dag,
        topological_sort_tasks,
    )
    wf_exec = db.query(WorkflowExecution).filter(
        WorkflowExecution.id == workflow_execution_id,
        WorkflowExecution.account_id == current_user.id,
    ).first()
    if not wf_exec:
        raise HTTPException(status_code=404, detail="ワークフロー実行が見つかりません")

    plan = get_plan_by_workflow_execution(db, workflow_execution_id)
    if not plan:
        return {"plan": None, "artifacts": [], "events": []}

    artifacts = get_artifacts_for_plan(db, plan.plan_id)
    events = get_events_for_plan(db, plan.plan_id)
    workers = get_workers_for_plan(db, plan.plan_id)
    followups = get_followup_tasks_for_plan(db, plan.plan_id)
    workspaces = get_workspaces_for_plan(db, plan.plan_id)
    dag = build_task_dag(plan)
    layers = topological_sort_tasks(plan)

    def _safe_json(s):
        if not s:
            return None
        try:
            return json.loads(s)
        except Exception:
            return None

    # 各タスクに provider router の判定結果を付与
    from app.services.coordinator_service import route_provider_mode
    tasks_data = _safe_json(plan.tasks) or []
    for t in tasks_data:
        t["resolved_provider_mode"] = route_provider_mode(
            plan,
            role=t.get("role", "writer"),
            artifact_type=t.get("expected_artifact_type", "draft"),
            impact_level=t.get("impact_level", "medium"),
            retry_count=0,
            writes_files=t.get("writes_files", False),
        )

    return {
        "plan": {
            "plan_id": plan.plan_id,
            "workflow_execution_id": plan.workflow_execution_id,
            "goal": plan.goal,
            "complexity_level": plan.complexity_level,
            "max_parallelism": plan.max_parallelism,
            "roles": _safe_json(plan.roles) or [],
            "tasks": tasks_data,
            "artifact_policy": _safe_json(plan.artifact_policy),
            "review_policy": _safe_json(plan.review_policy),
            "stop_conditions": _safe_json(plan.stop_conditions),
            "provider_policy": _safe_json(plan.provider_policy),
            "schema_version": plan.schema_version,
            "created_at": plan.created_at.isoformat() if plan.created_at else None,
        },
        "artifacts": [
            {
                "artifact_id": a.artifact_id,
                "task_id": a.task_id,
                "execution_id": a.execution_id,
                "role": a.role,
                "artifact_type": a.artifact_type,
                "summary": a.summary,
                "inline_content": a.inline_content,
                "provider_mode": a.provider_mode,
                "model_hint": a.model_hint,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in artifacts
        ],
        "events": [
            {
                "event_type": e.event_type,
                "task_id": e.task_id,
                "artifact_id": e.artifact_id,
                "payload": _safe_json(e.payload),
                "occurred_at": e.occurred_at.isoformat() if e.occurred_at else None,
            }
            for e in events
        ],
        "workers": [
            {
                "worker_id": w.worker_id,
                "name": w.name,
                "role": w.role,
                "status": w.status,
                "task_queue": _safe_json(w.task_queue) or [],
                "artifact_refs": _safe_json(w.artifact_refs) or [],
                "provider_mode": w.provider_mode,
                "current_task_id": w.current_task_id,
                "started_at": w.started_at.isoformat() if w.started_at else None,
                "finished_at": w.finished_at.isoformat() if w.finished_at else None,
            }
            for w in workers
        ],
        "followup_tasks": [
            {
                "task_id": f.task_id,
                "parent_task_id": f.parent_task_id,
                "target_role": f.target_role,
                "target_worker_name": f.target_worker_name,
                "objective": f.objective,
                "input_artifact_refs": _safe_json(f.input_artifact_refs) or [],
                "requires_review": f.requires_review,
                "reason": f.reason,
                "status": f.status,
                "depends_on": _safe_json(f.depends_on) or [],
                "created_at": f.created_at.isoformat() if f.created_at else None,
                "completed_at": f.completed_at.isoformat() if f.completed_at else None,
            }
            for f in followups
        ],
        "workspaces": [
            {
                "workspace_id": w.workspace_id,
                "worker_id": w.worker_id,
                "task_id": w.task_id,
                "mode": w.mode,
                "workspace_path": w.workspace_path,
                "cleanup_on_finish": w.cleanup_on_finish,
                "promoted": w.promoted,
                "status": w.status,
                "created_at": w.created_at.isoformat() if w.created_at else None,
                "promoted_at": w.promoted_at.isoformat() if w.promoted_at else None,
                "cleaned_at": w.cleaned_at.isoformat() if w.cleaned_at else None,
            }
            for w in workspaces
        ],
        "dag": dag,
        "execution_layers": layers,
    }


# ───────────────────────────────────────────────
#  Coordinator 拡張 — アダプタ / 評価 / 再開
# ───────────────────────────────────────────────

@router.get("/coordinator/adapters")
async def list_coordinator_adapters(
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user),
):
    """登録済みアダプター一覧を返す"""
    from app.services.coordinator_extensions import list_adapters
    adapters = list_adapters(db, only_enabled=False)
    def _safe_json(s):
        if not s:
            return None
        try:
            return json.loads(s)
        except Exception:
            return None
    return {
        "adapters": [
            {
                "adapter_id": a.adapter_id,
                "name": a.name,
                "adapter_type": a.adapter_type,
                "provider_mode": a.provider_mode,
                "transport": a.transport,
                "runtime": a.runtime,
                "impl": a.impl,
                "supported_roles": _safe_json(a.supported_roles) or [],
                "capabilities": _safe_json(a.capabilities) or [],
                "is_enabled": a.is_enabled,
                "health_status": a.health_status,
                "last_health_check": a.last_health_check.isoformat() if a.last_health_check else None,
            }
            for a in adapters
        ]
    }


@router.get("/coordinator/eval/{workflow_execution_id}")
async def get_coordinator_eval(
    workflow_execution_id: int,
    record: bool = False,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user),
):
    """plan の品質メトリクスを計算 (record=true で履歴に追記)"""
    from app.services.coordinator_service import get_plan_by_workflow_execution
    from app.services.coordinator_extensions import (
        compute_eval_metrics,
        record_eval_run,
        get_eval_runs_for_plan,
    )
    wf_exec = db.query(WorkflowExecution).filter(
        WorkflowExecution.id == workflow_execution_id,
        WorkflowExecution.account_id == current_user.id,
    ).first()
    if not wf_exec:
        raise HTTPException(status_code=404, detail="ワークフロー実行が見つかりません")
    plan = get_plan_by_workflow_execution(db, workflow_execution_id)
    if not plan:
        return {"current": None, "history": []}

    current = compute_eval_metrics(db, plan)
    if record:
        record_eval_run(db, plan)
    history = get_eval_runs_for_plan(db, plan.plan_id)
    return {
        "current": current,
        "history": [
            {
                "eval_id": e.eval_id,
                "completeness": float(e.completeness or 0),
                "factuality": float(e.factuality or 0),
                "revision_rate": float(e.revision_rate or 0),
                "judge_pass_rate": float(e.judge_pass_rate or 0),
                "overhead_ms": e.overhead_ms,
                "artifact_reuse_rate": float(e.artifact_reuse_rate or 0),
                "local_usage_rate": float(e.local_usage_rate or 0),
                "remote_escalation_rate": float(e.remote_escalation_rate or 0),
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in history
        ],
    }


@router.get("/coordinator/resumable")
async def list_resumable_coordinator_plans(
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user),
):
    """再開可能な plan 一覧 (artifact が一部生成済みで未完了のもの)"""
    from app.services.coordinator_extensions import list_resumable_plans, find_unfinished_tasks
    plans = list_resumable_plans(db)
    # 自分のワークフロー実行のみフィルタ
    result = []
    for p in plans:
        wf = db.query(WorkflowExecution).filter(
            WorkflowExecution.id == p.workflow_execution_id,
            WorkflowExecution.account_id == current_user.id,
        ).first()
        if not wf:
            continue
        unfinished = find_unfinished_tasks(db, p)
        result.append({
            "plan_id": p.plan_id,
            "workflow_execution_id": p.workflow_execution_id,
            "goal": p.goal,
            "complexity_level": p.complexity_level,
            "unfinished_count": len(unfinished),
            "created_at": p.created_at.isoformat() if p.created_at else None,
        })
    return {"plans": result}


@router.post("/coordinator/eval/{workflow_execution_id}/snapshot")
async def snapshot_coordinator_eval(
    workflow_execution_id: int,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user),
):
    """eval メトリクスを履歴として保存"""
    from app.services.coordinator_service import get_plan_by_workflow_execution
    from app.services.coordinator_extensions import record_eval_run
    wf_exec = db.query(WorkflowExecution).filter(
        WorkflowExecution.id == workflow_execution_id,
        WorkflowExecution.account_id == current_user.id,
    ).first()
    if not wf_exec:
        raise HTTPException(status_code=404, detail="ワークフロー実行が見つかりません")
    plan = get_plan_by_workflow_execution(db, workflow_execution_id)
    if not plan:
        raise HTTPException(status_code=404, detail="プランが見つかりません")
    eval_run = record_eval_run(db, plan)
    return {"eval_id": eval_run.eval_id, "created_at": eval_run.created_at.isoformat() if eval_run.created_at else None}
