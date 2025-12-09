from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
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
        enable_deep_think = getattr(prompt, 'enable_deep_think', True)
        if enable_deep_think is None:
            enable_deep_think = True

        prompt_dict = {
            "id": prompt.id,
            "name": prompt.name,
            "description": prompt.description,
            "model_type": prompt.model_type,
            "allows_file_output": prompt.allows_file_output,
            "enable_deep_think": bool(enable_deep_think)  # 明示的にboolに変換
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
    enable_deep_think = getattr(prompt, 'enable_deep_think', True)
    if enable_deep_think is None:
        enable_deep_think = True

    return {
        "id": prompt.id,
        "name": prompt.name,
        "description": prompt.description,
        "model_type": prompt.model_type,
        "input_schema": input_schema,
        "allows_file_output": prompt.allows_file_output,
        "enable_deep_think": bool(enable_deep_think)  # 明示的にboolに変換
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
        # 実行時に保存されたenable_deep_thinkを使用（実行時点の状態を保持）
        # 保存されていない場合はプロンプトの設定を参照（後方互換性のため）
        enable_deep_think = getattr(execution, 'enable_deep_think', None)
        if enable_deep_think is None and execution.prompt:
            # 古い実行履歴の場合、プロンプトの設定を参照
            enable_deep_think = getattr(execution.prompt, 'enable_deep_think', None)
            if enable_deep_think is None:
                enable_deep_think = True  # デフォルト値

        execution_dict = {
            **execution.__dict__,
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

    prompt_name = execution.prompt.name if execution.prompt else None

    # 実行時に保存されたenable_deep_thinkを使用（実行時点の状態を保持）
    # 保存されていない場合はプロンプトの設定を参照（後方互換性のため）
    enable_deep_think = getattr(execution, 'enable_deep_think', None)
    if enable_deep_think is None and execution.prompt:
        # 古い実行履歴の場合、プロンプトの設定を参照
        enable_deep_think = getattr(execution.prompt, 'enable_deep_think', None)
        if enable_deep_think is None:
            enable_deep_think = True  # デフォルト値

    return {
        **execution.__dict__,
        "prompt_name": prompt_name,
        "enable_deep_think": bool(enable_deep_think) if enable_deep_think is not None else None
    }

