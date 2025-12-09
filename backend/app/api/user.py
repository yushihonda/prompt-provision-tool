from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.auth import get_current_user
from app.models import Account, Prompt, AccountPrompt, Execution
from app.schemas import PromptListResponse, ExecutionResponse, UserDashboardStats
import json
from datetime import datetime

router = APIRouter(prefix="/api/user", tags=["ユーザー"])


# ==================== ダッシュボード ====================
@router.get("/dashboard", response_model=UserDashboardStats)
async def get_user_dashboard_stats(
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user)
):
    """ユーザー用ダッシュボード統計情報を取得"""
    # 利用可能なプロンプト数
    available_prompts = db.query(Prompt).join(
        AccountPrompt, Prompt.id == AccountPrompt.prompt_id
    ).filter(
        AccountPrompt.account_id == current_user.id,
        Prompt.is_active == True
    ).count()
    
    # 総実行回数
    total_executions = db.query(Execution).filter(
        Execution.account_id == current_user.id
    ).count()
    
    # 今日の実行数
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    executions_today = db.query(Execution).filter(
        Execution.account_id == current_user.id,
        Execution.executed_at >= today_start
    ).count()
    
    # 今月の実行数
    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    executions_this_month = db.query(Execution).filter(
        Execution.account_id == current_user.id,
        Execution.executed_at >= month_start
    ).count()
    
    return {
        "available_prompts": available_prompts,
        "total_executions": total_executions,
        "executions_today": executions_today,
        "executions_this_month": executions_this_month
    }


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
    # 総件数を取得
    total = db.query(Prompt).join(
        AccountPrompt, Prompt.id == AccountPrompt.prompt_id
    ).filter(
        AccountPrompt.account_id == current_user.id,
        Prompt.is_active == True
    ).count()
    
    prompts = db.query(Prompt).join(
        AccountPrompt, Prompt.id == AccountPrompt.prompt_id
    ).filter(
        AccountPrompt.account_id == current_user.id,
        Prompt.is_active == True
    ).order_by(Prompt.created_at.desc()).offset(skip).limit(limit).all()

    # input_schemaをJSON形式にパース
    items = []
    for prompt in prompts:
        prompt_dict = {
            "id": prompt.id,
            "name": prompt.name,
            "description": prompt.description,
            "model_type": prompt.model_type,
            "allows_file_output": prompt.allows_file_output
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
    # プロンプトの存在確認
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
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

    return {
        "id": prompt.id,
        "name": prompt.name,
        "description": prompt.description,
        "model_type": prompt.model_type,
        "input_schema": input_schema,
        "allows_file_output": prompt.allows_file_output
    }


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
        items.append({
            **execution.__dict__,
            "prompt_name": prompt_name
        })

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

    prompt_name = execution.prompt.name if execution.prompt else None

    return {
        **execution.__dict__,
        "prompt_name": prompt_name
    }

