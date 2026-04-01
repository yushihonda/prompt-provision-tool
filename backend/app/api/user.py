from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy import func
from typing import List
from app.database import get_db
from app.auth import get_current_user
from app.models import Account, Skill, AccountSkill, Execution, Workflow, WorkflowSkill, WorkflowExecution
from app.schemas import (
    SkillListResponse,
    ExecutionResponse,
    UserDashboardStats,
    UserWorkflowSummary,
    WorkflowListItem,
    UserWorkflowDetail,
    UserWorkflowDetailSkill,
)
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List

router = APIRouter(prefix="/api/user", tags=["ユーザー"])


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

    # 月が変わっていたら月次カウンターをリセット
    from app.services.account_stats import check_and_reset_monthly_stats
    check_and_reset_monthly_stats(current_user, db)

    # 保存された値を取得（計算不要）
    total_tokens_this_month = current_user.tokens_this_month or 0
    total_cost_this_month = float(current_user.cost_this_month or 0.0)
    executions_this_month = current_user.executions_this_month or 0

    return {
        "available_skills": available_skills,
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

        # 外部ツールフラグはNoneの場合はFalseとして扱う（後方互換）
        enable_web_search = bool(getattr(skill, "enable_web_search", False) or False)
        enable_code_interpreter = bool(
            getattr(skill, "enable_code_interpreter", False) or False
        )
        enable_file_search = bool(
            getattr(skill, "enable_file_search", False) or False
        )

        skill_dict = {
            "id": skill.id,
            "name": skill.name,
            "description": skill.description,
            "model_type": skill.model_type,
            "allows_file_output": skill.allows_file_output,
            "enable_deep_think": bool(enable_deep_think),  # 明示的にboolに変換
            "enable_web_search": enable_web_search,
            "enable_code_interpreter": enable_code_interpreter,
            "enable_file_search": enable_file_search,
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

    return {
        "id": skill.id,
        "name": skill.name,
        "description": skill.description,
        "model_type": skill.model_type,
        "input_schema": input_schema,
        "allows_file_output": skill.allows_file_output,
        "enable_deep_think": bool(enable_deep_think),  # 明示的にboolに変換
        "enable_web_search": bool(getattr(skill, "enable_web_search", False) or False),
        "enable_code_interpreter": bool(
            getattr(skill, "enable_code_interpreter", False) or False
        ),
        "enable_file_search": bool(
            getattr(skill, "enable_file_search", False) or False
        ),
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
                    enable_web_search=bool(
                        getattr(s, "enable_web_search", False) or False
                    ),
                    enable_code_interpreter=bool(
                        getattr(s, "enable_code_interpreter", False) or False
                    ),
                    enable_file_search=bool(
                        getattr(s, "enable_file_search", False) or False
                    ),
                )
            )

        # input_schemaをJSONから辞書に変換
        workflow_input_schema = None
        if wf.input_schema:
            try:
                workflow_input_schema = json.loads(wf.input_schema) if isinstance(wf.input_schema, str) else wf.input_schema
            except (json.JSONDecodeError, TypeError):
                workflow_input_schema = None

        result.append(
            UserWorkflowSummary(
                workflow=WorkflowListItem(
                    id=wf.id,
                    name=wf.name,
                    description=wf.description,
                    is_active=wf.is_active,
                    parent_model_type=wf.parent_model_type,
                    created_at=wf.created_at,
                    updated_at=wf.updated_at,
                ),
                skills=skill_list,
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

    skills: List[UserWorkflowDetailSkill] = []
    for ws in wf_skills:
        s = ws.skill
        if not s:
            continue
        skills.append(
            UserWorkflowDetailSkill(
                workflow_skill_id=ws.id,
                skill_order=ws.skill_order,
                skill_name=ws.skill_name,
                skill_id=s.id,
                skill_display_name=s.name,
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
                grp_skills.append({
                    "skill_id": s.id,
                    "skill_name": s.name,
                    "model_type": s.model_type,
                    "order_in_group": ws.order_in_group or ws.skill_order or 0,
                    "skill_display_name": ws.skill_name or s.name,
                    "workflow_skill_id": ws.id,
                    "skill_order": ws.skill_order,
                    "input_mapping": input_mapping_parsed,
                })
        groups_data.append({
            "id": grp.id,
            "group_order": grp.group_order,
            "group_name": grp.group_name,
            "execution_type": grp.execution_type,
            "skills": grp_skills,
        })

    wf_item = WorkflowListItem(
        id=wf.id,
        name=wf.name,
        description=wf.description,
        is_active=wf.is_active,
        parent_model_type=wf.parent_model_type,
        created_at=wf.created_at,
        updated_at=wf.updated_at,
        groups=groups_data,
    )

    return UserWorkflowDetail(workflow=wf_item, skills=skills, input_schema=workflow_input_schema)


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

    items = []
    for execution in executions:
        skill_name = execution.skill.name if execution.skill else None

        # ワークフロー実行情報を取得（eager loaded）
        workflow_name = None
        skill_display_name = None
        if execution.workflow_execution:
            wf = execution.workflow_execution.workflow
            if wf:
                workflow_name = wf.name
            if execution.workflow_skill:
                skill_display_name = execution.workflow_skill.skill_name or f"Step {execution.skill_order}"

        # 実行時に保存されたenable_deep_thinkを使用（実行時点の状態を保持）
        # 保存されていない場合はスキルの設定を参照（後方互換性のため）
        enable_deep_think = getattr(execution, 'enable_deep_think', None)
        if enable_deep_think is None and execution.skill:
            # 古い実行履歴の場合、スキルの設定を参照
            enable_deep_think = getattr(execution.skill, 'enable_deep_think', None)
            if enable_deep_think is None:
                enable_deep_think = True  # デフォルト値

        # output_formatを取得（モデルから直接取得）
        output_format = getattr(execution, 'output_format', None)
        if output_format is None:
            output_format = 'txt'  # デフォルト値

        execution_dict = {
            "id": execution.id,
            "account_id": execution.account_id,
            "skill_id": execution.skill_id,
            "workflow_execution_id": execution.workflow_execution_id,
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
            "reflection_loop": getattr(execution, 'reflection_loop', 0),
            "enable_deep_think": bool(enable_deep_think) if enable_deep_think is not None else None
        }
        items.append(execution_dict)

    return {
        "items": items,
        "total": total,
        "skip": skip,
        "limit": limit
    }


@router.get("/workflow-executions/{wf_execution_id}/status")
async def get_workflow_execution_status(
    wf_execution_id: int,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user)
):
    """ワークフロー実行のステータスを取得"""
    wf_exec = db.query(WorkflowExecution).filter(
        WorkflowExecution.id == wf_execution_id,
        WorkflowExecution.account_id == current_user.id,
    ).first()
    if not wf_exec:
        raise HTTPException(status_code=404, detail="ワークフロー実行が見つかりません")
    blackboard_keys = []
    if wf_exec.blackboard_data:
        try:
            bb = json.loads(wf_exec.blackboard_data)
            blackboard_keys = list(bb.keys())
        except (json.JSONDecodeError, TypeError):
            pass

    return {
        "id": wf_exec.id,
        "status": wf_exec.status,
        "error_message": wf_exec.error_message,
        "current_step": wf_exec.current_step,
        "total_steps": wf_exec.total_steps,
        "blackboard_keys": blackboard_keys,
    }


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

    # スキル名
    skill_name = execution.skill.name if execution.skill else None

    # ワークフロー情報（あれば付与）
    workflow_name = None
    skill_display_name = None
    wf_exec = None
    if execution.workflow_execution_id:
        wf_exec = db.query(WorkflowExecution).filter(
            WorkflowExecution.id == execution.workflow_execution_id
        ).first()
        if wf_exec:
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

    return ExecutionResponse(
        id=execution.id,
        account_id=execution.account_id,
        skill_id=execution.skill_id,
        skill_name=skill_name,
        workflow_execution_id=execution.workflow_execution_id,
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
        executed_at=execution.executed_at,
        enable_deep_think=bool(enable_deep_think) if enable_deep_think is not None else None,
    )
