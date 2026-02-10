from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List
from app.database import get_db
from app.auth import get_current_user
from app.models import Account, Prompt, AccountPrompt, Execution, Workflow, WorkflowSkill, WorkflowExecution
from app.schemas import (
    PromptListResponse,
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
    # 利用可能なプロンプト数（論理削除されていないもののみ）
    available_prompts = db.query(Prompt).join(
        AccountPrompt, Prompt.id == AccountPrompt.prompt_id
    ).filter(
        AccountPrompt.account_id == current_user.id,
        Prompt.is_active == True,
        Prompt.deleted_at.is_(None)
    ).count()

    # 今月の開始日時（月が変わったかチェック用）
    # JST（日本時間）で現在の月の開始日時を取得
    from datetime import timezone, timedelta
    jst = timezone(timedelta(hours=9))
    current_month_start = datetime.now(jst).replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # 今月の総トークン数、総料金、実行回数はAccountモデルから取得（保存された値を使用）
    # 月が変わった場合は自動的にリセット
    # last_month_resetがtimezone-naiveの場合はJSTとして解釈
    should_reset = False
    if current_user.last_month_reset is None:
        should_reset = True
    else:
        # timezone-awareかどうかを確認
        if current_user.last_month_reset.tzinfo is None:
            # timezone-naiveの場合はJSTとして解釈
            last_reset_aware = current_user.last_month_reset.replace(tzinfo=jst)
        else:
            last_reset_aware = current_user.last_month_reset
        
        if last_reset_aware < current_month_start:
            should_reset = True
    
    if should_reset:
        current_user.tokens_this_month = 0
        current_user.cost_this_month = 0.0
        current_user.executions_this_month = 0
        current_user.last_month_reset = current_month_start
        db.commit()
        db.refresh(current_user)

    # 保存された値を取得（計算不要）
    total_tokens_this_month = current_user.tokens_this_month or 0
    total_cost_this_month = float(current_user.cost_this_month or 0.0)
    executions_this_month = current_user.executions_this_month or 0

    return {
        "available_prompts": available_prompts,
        "executions_this_month": executions_this_month,
        "total_tokens_this_month": total_tokens_this_month,
        "total_cost_this_month": total_cost_this_month
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


@router.get("/prompts")
async def list_available_prompts(
    skip: int = 0,
    limit: int = 6,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user)
):
    """
    現在のユーザーが利用可能なプロンプト一覧を取得（ページネーション対応）

    注意: プロンプトの内容は含まれない（セキュリティ）
    """
    # 総件数を取得（論理削除されていないもののみ）
    total = db.query(Prompt).join(
        AccountPrompt, Prompt.id == AccountPrompt.prompt_id
    ).filter(
        AccountPrompt.account_id == current_user.id,
        Prompt.is_active == True,
        Prompt.deleted_at.is_(None)
    ).count()

    prompts = db.query(Prompt).join(
        AccountPrompt, Prompt.id == AccountPrompt.prompt_id
    ).filter(
        AccountPrompt.account_id == current_user.id,
        Prompt.is_active == True,
        Prompt.deleted_at.is_(None)
    ).order_by(Prompt.created_at.desc()).offset(skip).limit(limit).all()

    # input_schemaをJSON形式にパース
    items = []
    for prompt in prompts:
        # enable_deep_thinkがNoneの場合はデフォルト値Trueを使用
        enable_deep_think = getattr(prompt, "enable_deep_think", True)
        if enable_deep_think is None:
            enable_deep_think = True

        # 外部ツールフラグはNoneの場合はFalseとして扱う（後方互換）
        enable_web_search = bool(getattr(prompt, "enable_web_search", False) or False)
        enable_code_interpreter = bool(
            getattr(prompt, "enable_code_interpreter", False) or False
        )
        enable_file_search = bool(
            getattr(prompt, "enable_file_search", False) or False
        )

        prompt_dict = {
            "id": prompt.id,
            "name": prompt.name,
            "description": prompt.description,
            "model_type": prompt.model_type,
            "allows_file_output": prompt.allows_file_output,
            "enable_deep_think": bool(enable_deep_think),  # 明示的にboolに変換
            "enable_web_search": enable_web_search,
            "enable_code_interpreter": enable_code_interpreter,
            "enable_file_search": enable_file_search,
        }
        items.append(prompt_dict)

    return {
        "items": items,
        "total": total,
        "skip": skip,
        "limit": limit
    }


@router.get("/prompts/{prompt_id}")
async def get_prompt_detail(
    prompt_id: int,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user)
):
    """
    特定のプロンプトの詳細情報を取得

    注意: プロンプトの内容は含まれない（セキュリティ）
    input_schemaのみ返す（入力フォームの構築用）
    """
    # プロンプトの存在確認（論理削除されていないもののみ）
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id, Prompt.deleted_at.is_(None)).first()
    if not prompt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="プロンプトが見つかりません"
        )

    # アクセス権限の確認
    assignment = db.query(AccountPrompt).filter(
        AccountPrompt.account_id == current_user.id,
        AccountPrompt.prompt_id == prompt_id
    ).first()

    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="このプロンプトへのアクセス権限がありません"
        )

    # input_schemaをパース
    input_schema = None
    if prompt.input_schema:
        try:
            input_schema = json.loads(prompt.input_schema)
        except:
            input_schema = None

    # enable_deep_thinkがNoneの場合はデフォルト値Trueを使用
    enable_deep_think = getattr(prompt, "enable_deep_think", True)
    if enable_deep_think is None:
        enable_deep_think = True

    return {
        "id": prompt.id,
        "name": prompt.name,
        "description": prompt.description,
        "model_type": prompt.model_type,
        "input_schema": input_schema,
        "allows_file_output": prompt.allows_file_output,
        "enable_deep_think": bool(enable_deep_think),  # 明示的にboolに変換
        "enable_web_search": bool(getattr(prompt, "enable_web_search", False) or False),
        "enable_code_interpreter": bool(
            getattr(prompt, "enable_code_interpreter", False) or False
        ),
        "enable_file_search": bool(
            getattr(prompt, "enable_file_search", False) or False
        ),
    }


@router.get("/workflows")
async def list_user_workflows(
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user),
):
    """
    現在のユーザーが利用可能なワークフローと、その中のSkill(=Prompt)一覧を取得
    """
    # このユーザーに割り当てられているプロンプトID
    assigned_prompt_ids_subq = (
        db.query(AccountPrompt.prompt_id)
        .filter(AccountPrompt.account_id == current_user.id)
        .subquery()
    )

    # 利用可能なワークフローを取得（ワークフロー自体が有効 + 論理削除されていない）
    workflows = (
        db.query(Workflow)
        .join(WorkflowSkill, Workflow.id == WorkflowSkill.workflow_id)
        .filter(
            Workflow.deleted_at.is_(None),
            Workflow.is_active == True,  # noqa: E712
            WorkflowSkill.prompt_id.in_(assigned_prompt_ids_subq),
        )
        .distinct()
        .all()
    )

    result: List[UserWorkflowSummary] = []

    for wf in workflows:
        # ワークフロー内のSkillを順番に取得（このユーザーに割り当て済みのPromptのみ）
        wf_skills = (
            db.query(WorkflowSkill)
            .join(Prompt, Prompt.id == WorkflowSkill.prompt_id)
            .filter(
                WorkflowSkill.workflow_id == wf.id,
                WorkflowSkill.prompt_id.in_(assigned_prompt_ids_subq),
                Prompt.deleted_at.is_(None),
                Prompt.is_active == True,  # noqa: E712
            )
            .order_by(WorkflowSkill.step_order.asc(), WorkflowSkill.id.asc())
            .all()
        )

        skill_prompts: List[PromptListResponse] = []
        for ws in wf_skills:
            p = ws.prompt
            if not p:
                continue

            # enable_deep_thinkがNoneの場合はデフォルト値Trueを使用
            enable_deep_think = getattr(p, "enable_deep_think", True)
            if enable_deep_think is None:
                enable_deep_think = True

            skill_prompts.append(
                PromptListResponse(
                    id=p.id,
                    name=p.name,
                    description=p.description,
                    model_type=p.model_type,
                    allows_file_output=p.allows_file_output,
                    enable_deep_think=bool(enable_deep_think),
                    enable_web_search=bool(
                        getattr(p, "enable_web_search", False) or False
                    ),
                    enable_code_interpreter=bool(
                        getattr(p, "enable_code_interpreter", False) or False
                    ),
                    enable_file_search=bool(
                        getattr(p, "enable_file_search", False) or False
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
                    input_schema=workflow_input_schema,
                    is_active=wf.is_active,
                    leader_prompt_id=wf.leader_prompt_id,
                    created_at=wf.created_at,
                    updated_at=wf.updated_at,
                ),
                skills=skill_prompts,
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
    特定のワークフローの詳細情報と、その中のSkill(=Prompt)一覧を取得
    """
    # このユーザーに割り当てられているプロンプトID
    assigned_prompt_ids_subq = (
        db.query(AccountPrompt.prompt_id)
        .filter(AccountPrompt.account_id == current_user.id)
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
        .join(Prompt, Prompt.id == WorkflowSkill.prompt_id)
        .filter(
            WorkflowSkill.workflow_id == wf.id,
            WorkflowSkill.prompt_id.in_(assigned_prompt_ids_subq),
            Prompt.deleted_at.is_(None),
            Prompt.is_active == True,  # noqa: E712
        )
        .order_by(WorkflowSkill.step_order.asc(), WorkflowSkill.id.asc())
        .all()
    )

    skills: List[UserWorkflowDetailSkill] = []
    for ws in wf_skills:
        p = ws.prompt
        if not p:
            continue
        skills.append(
            UserWorkflowDetailSkill(
                workflow_skill_id=ws.id,
                step_order=ws.step_order,
                step_name=ws.step_name,
                prompt_id=p.id,
                prompt_name=p.name,
            )
        )

    if not skills:
        # ワークフロー自体は存在するが、このユーザーが利用できるSkillがない場合
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="このワークフローで利用可能なSkillがありません",
        )

    # input_schemaをJSONから辞書に変換
    workflow_input_schema = None
    if wf.input_schema:
        try:
            workflow_input_schema = json.loads(wf.input_schema) if isinstance(wf.input_schema, str) else wf.input_schema
        except (json.JSONDecodeError, TypeError):
            workflow_input_schema = None

    wf_item = WorkflowListItem(
        id=wf.id,
        name=wf.name,
        description=wf.description,
        input_schema=workflow_input_schema,
        is_active=wf.is_active,
        leader_prompt_id=wf.leader_prompt_id,
        created_at=wf.created_at,
        updated_at=wf.updated_at,
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
    # 総件数を取得
    total = db.query(Execution).filter(
        Execution.account_id == current_user.id
    ).count()

    executions = db.query(Execution).filter(
        Execution.account_id == current_user.id
    ).order_by(
        Execution.executed_at.desc()
    ).offset(skip).limit(limit).all()

    items = []
    for execution in executions:
        prompt_name = execution.prompt.name if execution.prompt else None
        
        # ワークフロー実行情報を取得
        workflow_execution = None
        workflow_name = None
        step_name = None
        if execution.workflow_execution_id:
            workflow_execution = db.query(WorkflowExecution).filter(
                WorkflowExecution.id == execution.workflow_execution_id
            ).first()
            if workflow_execution:
                workflow = db.query(Workflow).filter(
                    Workflow.id == workflow_execution.workflow_id
                ).first()
                if workflow:
                    workflow_name = workflow.name
                # ステップ名を取得
                if execution.workflow_skill_id:
                    workflow_skill = db.query(WorkflowSkill).filter(
                        WorkflowSkill.id == execution.workflow_skill_id
                    ).first()
                    if workflow_skill:
                        step_name = workflow_skill.step_name or f"Step {execution.step_order}"
        
        # 実行時に保存されたenable_deep_thinkを使用（実行時点の状態を保持）
        # 保存されていない場合はプロンプトの設定を参照（後方互換性のため）
        enable_deep_think = getattr(execution, 'enable_deep_think', None)
        if enable_deep_think is None and execution.prompt:
            # 古い実行履歴の場合、プロンプトの設定を参照
            enable_deep_think = getattr(execution.prompt, 'enable_deep_think', None)
            if enable_deep_think is None:
                enable_deep_think = True  # デフォルト値

        # output_formatを取得（モデルから直接取得）
        output_format = getattr(execution, 'output_format', None)
        if output_format is None:
            output_format = 'txt'  # デフォルト値
        
        execution_dict = {
            "id": execution.id,
            "account_id": execution.account_id,
            "prompt_id": execution.prompt_id,
            "workflow_execution_id": execution.workflow_execution_id,
            "workflow_name": workflow_name,
            "step_order": execution.step_order,
            "step_name": step_name,
            "input_data": execution.input_data,
            "output_data": execution.output_data,
            "model_used": execution.model_used,
            "tokens_used": execution.tokens_used,
            "execution_time": execution.execution_time,
            "status": execution.status,
            "error_message": execution.error_message,
            "executed_at": execution.executed_at,
            "output_format": output_format,  # output_formatを明示的に含める
            "prompt_name": prompt_name,
            "enable_deep_think": bool(enable_deep_think) if enable_deep_think is not None else None
        }
        items.append(execution_dict)

    return {
        "items": items,
        "total": total,
        "skip": skip,
        "limit": limit
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

    # プロンプト名
    prompt_name = execution.prompt.name if execution.prompt else None

    # ワークフロー情報（あれば付与）
    workflow_name = None
    step_name = None
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
                step_name = wf_skill.step_name or f"Step {execution.step_order}"

    # 実行時に保存されたenable_deep_thinkを使用（実行時点の状態を保持）
    # 保存されていない場合はプロンプトの設定を参照（後方互換性のため）
    enable_deep_think = getattr(execution, "enable_deep_think", None)
    if enable_deep_think is None and execution.prompt:
        enable_deep_think = getattr(execution.prompt, "enable_deep_think", None)
        if enable_deep_think is None:
            enable_deep_think = True  # デフォルト値

    # output_formatを取得（モデルから直接取得）
    output_format = getattr(execution, "output_format", None)
    if output_format is None:
        output_format = "txt"  # デフォルト値

    return ExecutionResponse(
        id=execution.id,
        account_id=execution.account_id,
        prompt_id=execution.prompt_id,
        prompt_name=prompt_name,
        workflow_execution_id=execution.workflow_execution_id,
        workflow_skill_id=execution.workflow_skill_id,
        step_order=execution.step_order,
        workflow_name=workflow_name,
        step_name=step_name,
        input_data=execution.input_data,
        output_data=execution.output_data,
        model_used=execution.model_used,
        tokens_used=execution.tokens_used,
        execution_time=execution.execution_time,
        status=execution.status,
        error_message=execution.error_message,
        output_format=output_format,
        executed_at=execution.executed_at,
        enable_deep_think=bool(enable_deep_think) if enable_deep_think is not None else None,
    )

