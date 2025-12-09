from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List
from app.database import get_db
from app.auth import get_current_active_parent, get_password_hash
from app.models import Account, Prompt, AccountPrompt, Execution, APIConfig, AccountType
from app.schemas import (
    AccountCreate, AccountResponse, AccountUpdate, AccountWithPromptCount,
    PromptCreate, PromptResponse, PromptUpdate,
    AccountPromptAssign, AccountPromptResponse,
    DashboardStats, ExecutionResponse
)
from app.encryption import encryption_service
import json

router = APIRouter(prefix="/api/admin", tags=["管理者"])


# ==================== ダッシュボード ====================
@router.get("/dashboard", response_model=DashboardStats)
async def get_dashboard_stats(
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent)
):
    """ダッシュボード統計情報を取得"""
    total_accounts = db.query(Account).filter(Account.account_type == AccountType.CHILD).count()
    total_prompts = db.query(Prompt).filter(Prompt.deleted_at.is_(None)).count()
    # 総実行回数はAccount.total_executionsの合計を使用（保存された値）
    total_executions = db.query(func.sum(Account.total_executions)).scalar() or 0
    total_executions = int(total_executions)  # Decimal型をintに変換

    return {
        "total_accounts": total_accounts,
        "total_prompts": total_prompts,
        "total_executions": total_executions
    }


# ==================== アカウント管理 ====================
@router.post("/accounts", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
async def create_account(
    account: AccountCreate,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent)
):
    """新しいアカウントを作成"""
    # ユーザー名の重複チェック
    existing_account = db.query(Account).filter(Account.username == account.username).first()
    if existing_account:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="このユーザー名は既に使用されています"
        )

    # メールアドレスの重複チェック
    existing_email = db.query(Account).filter(Account.email == account.email).first()
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="このメールアドレスは既に使用されています"
        )

    # アカウント作成
    db_account = Account(
        username=account.username,
        email=account.email,
        hashed_password=get_password_hash(account.password),
        account_type=account.account_type
    )
    db.add(db_account)
    db.commit()
    db.refresh(db_account)

    # 子アカウントの場合、API設定も作成
    if str(account.account_type) == AccountType.CHILD:
        api_config = APIConfig(
            account_id=db_account.id,
            openai_api_key=account.openai_api_key if account.openai_api_key else None,
            gemini_api_key=account.gemini_api_key if account.gemini_api_key else None,
            rate_limit_per_hour=account.rate_limit_per_hour if account.rate_limit_per_hour is not None else 100,
            rate_limit_per_day=account.rate_limit_per_day if account.rate_limit_per_day is not None else 1000,
            is_enabled=account.api_config_enabled if account.api_config_enabled is not None else True
        )
        db.add(api_config)
        db.commit()

    return db_account


@router.get("/accounts")
async def list_accounts(
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent)
):
    """全アカウントを取得（ページネーション対応）"""
    # 総件数を取得
    total = db.query(Account).count()

    # アカウント一覧を取得
    accounts = db.query(Account).order_by(Account.id.desc()).offset(skip).limit(limit).all()

    # 今月の開始日時（JST基準）
    from datetime import datetime, timezone, timedelta
    jst = timezone(timedelta(hours=9))
    current_month_start = datetime.now(jst).replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # 各アカウントのプロンプト数、実行回数、総トークン数、総料金を個別に取得
    items = []
    for acc in accounts:
        prompt_count = db.query(func.count(AccountPrompt.id)).filter(
            AccountPrompt.account_id == acc.id
        ).scalar() or 0

        # 今月の実行回数はAccountモデルから取得（保存された値を使用）
        # 月が変わった場合は自動的にリセット
        # last_month_resetがtimezone-naiveの場合はJSTとして解釈
        should_reset = False
        if acc.last_month_reset is None:
            should_reset = True
        else:
            # timezone-awareかどうかを確認
            if acc.last_month_reset.tzinfo is None:
                # timezone-naiveの場合はJSTとして解釈
                from datetime import timezone, timedelta
                jst = timezone(timedelta(hours=9))
                last_reset_aware = acc.last_month_reset.replace(tzinfo=jst)
            else:
                last_reset_aware = acc.last_month_reset
            
            if last_reset_aware < current_month_start:
                should_reset = True
        
        if should_reset:
            acc.tokens_this_month = 0
            acc.cost_this_month = 0.0
            acc.executions_this_month = 0
            acc.last_month_reset = current_month_start
            db.commit()
            db.refresh(acc)
        
        executions_this_month = acc.executions_this_month or 0

        # 総トークン数、総料金、総実行回数はAccountモデルから取得（保存された値を使用）
        total_tokens = acc.total_tokens or 0
        total_cost = float(acc.total_cost or 0.0)
        total_executions = acc.total_executions or 0

        # 今月のトークン数と料金も取得
        tokens_this_month = acc.tokens_this_month or 0
        cost_this_month = float(acc.cost_this_month or 0.0)

        # API設定情報を取得（子アカウントのみ）
        api_config_data = None
        if str(acc.account_type) == AccountType.CHILD:
            api_config = db.query(APIConfig).filter(APIConfig.account_id == acc.id).first()
            if api_config:
                api_config_data = {
                    "openai_api_key": api_config.openai_api_key if api_config.openai_api_key else None,
                    "gemini_api_key": api_config.gemini_api_key if api_config.gemini_api_key else None,
                    "rate_limit_per_hour": api_config.rate_limit_per_hour or 100,
                    "rate_limit_per_day": api_config.rate_limit_per_day or 1000,
                    "is_enabled": api_config.is_enabled if api_config.is_enabled is not None else True
                }

        items.append({
            "id": acc.id,
            "username": acc.username,
            "email": acc.email,
            "account_type": acc.account_type,
            "is_active": acc.is_active,
            "prompt_count": prompt_count,
            "execution_count": total_executions,
            "executions_this_month": executions_this_month,
            "total_tokens": total_tokens,
            "total_cost": total_cost,
            "tokens_this_month": tokens_this_month,
            "cost_this_month": cost_this_month,
            "api_config": api_config_data
        })

    return {
        "items": items,
        "total": total,
        "skip": skip,
        "limit": limit
    }


@router.get("/accounts/{account_id}", response_model=AccountResponse)
async def get_account(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent)
):
    """特定のアカウントを取得"""
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="アカウントが見つかりません"
        )
    return account


@router.patch("/accounts/{account_id}", response_model=AccountResponse)
async def update_account(
    account_id: int,
    account_update: AccountUpdate,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent)
):
    """アカウント情報を更新"""
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="アカウントが見つかりません"
        )

    # アカウント情報を更新
    if account_update.email:
        account.email = account_update.email
    if account_update.password:
        account.hashed_password = get_password_hash(account_update.password)
    if account_update.is_active is not None:
        account.is_active = account_update.is_active

    db.commit()
    db.refresh(account)

    # 子アカウントの場合、API設定も更新
    if str(account.account_type) == AccountType.CHILD:
        api_config = db.query(APIConfig).filter(APIConfig.account_id == account_id).first()

        # API設定が存在しない場合は作成
        if not api_config:
            api_config = APIConfig(account_id=account_id)
            db.add(api_config)

        # API設定を更新（値が提供されている場合のみ更新）
        if account_update.openai_api_key is not None:
            # 空文字列の場合はNoneに設定（削除）
            api_config.openai_api_key = account_update.openai_api_key.strip() if account_update.openai_api_key and account_update.openai_api_key.strip() else None
        if account_update.gemini_api_key is not None:
            # 空文字列の場合はNoneに設定（削除）
            api_config.gemini_api_key = account_update.gemini_api_key.strip() if account_update.gemini_api_key and account_update.gemini_api_key.strip() else None
        if account_update.rate_limit_per_hour is not None:
            api_config.rate_limit_per_hour = account_update.rate_limit_per_hour
        if account_update.rate_limit_per_day is not None:
            api_config.rate_limit_per_day = account_update.rate_limit_per_day
        if account_update.api_config_enabled is not None:
            api_config.is_enabled = account_update.api_config_enabled

        db.commit()

    return account


@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent)
):
    """アカウントを削除"""
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="アカウントが見つかりません"
        )

    # 親アカウントは削除できない
    if str(account.account_type) == AccountType.PARENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="親アカウントは削除できません"
        )

    db.delete(account)
    db.commit()


# ==================== プロンプト管理 ====================
@router.post("/prompts", response_model=PromptResponse, status_code=status.HTTP_201_CREATED)
async def create_prompt(
    prompt: PromptCreate,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent)
):
    """新しいプロンプトを作成"""
    # プロンプトを暗号化
    encrypted_content = encryption_service.encrypt(prompt.content)

    # input_schemaをJSON文字列に変換
    input_schema_str = json.dumps(prompt.input_schema) if prompt.input_schema else None

    db_prompt = Prompt(
        name=prompt.name,
        description=prompt.description,
        encrypted_content=encrypted_content,
        model_type=prompt.model_type,
        input_schema=input_schema_str,
        allows_file_output=prompt.allows_file_output,
        enable_deep_think=prompt.enable_deep_think,
        created_by=current_user.id
    )
    db.add(db_prompt)
    db.commit()
    db.refresh(db_prompt)

    # input_schemaをJSON文字列からdictに変換
    prompt_dict = db_prompt.__dict__.copy()
    if db_prompt.input_schema:
        try:
            prompt_dict['input_schema'] = json.loads(db_prompt.input_schema)
        except:
            prompt_dict['input_schema'] = None

    return prompt_dict


@router.get("/prompts")
async def list_prompts(
    skip: int = 0,
    limit: int = 6,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent)
):
    """全プロンプトを取得（ページネーション対応）"""
    # 総件数を取得（論理削除されていないもののみ）
    total = db.query(Prompt).filter(Prompt.deleted_at.is_(None)).count()

    prompts = db.query(Prompt).filter(Prompt.deleted_at.is_(None)).order_by(Prompt.created_at.desc()).offset(skip).limit(limit).all()

    # input_schemaをJSON文字列からdictに変換
    items = []
    for prompt in prompts:
        prompt_dict = prompt.__dict__.copy()
        if prompt.input_schema:
            try:
                prompt_dict['input_schema'] = json.loads(prompt.input_schema)
            except:
                prompt_dict['input_schema'] = None
        items.append(prompt_dict)

    return {
        "items": items,
        "total": total,
        "skip": skip,
        "limit": limit
    }


@router.get("/prompts/{prompt_id}", response_model=PromptResponse)
async def get_prompt(
    prompt_id: int,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent)
):
    """特定のプロンプトを取得"""
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id, Prompt.deleted_at.is_(None)).first()
    if not prompt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="プロンプトが見つかりません"
        )

    # input_schemaをJSON文字列からdictに変換
    prompt_dict = prompt.__dict__.copy()
    if prompt.input_schema:
        try:
            prompt_dict['input_schema'] = json.loads(prompt.input_schema)
        except:
            prompt_dict['input_schema'] = None

    return prompt_dict


@router.get("/prompts/{prompt_id}/content")
async def get_prompt_content(
    prompt_id: int,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent)
):
    """プロンプトの内容を取得（復号化）- 管理者のみ"""
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id, Prompt.deleted_at.is_(None)).first()
    if not prompt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="プロンプトが見つかりません"
        )

    # 復号化
    try:
        if prompt.encrypted_content is None:
            return {"content": ""}
        decrypted_content = encryption_service.decrypt(prompt.encrypted_content)
        return {"content": decrypted_content}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"プロンプトの復号化に失敗しました: {str(e)}"
        )


@router.patch("/prompts/{prompt_id}", response_model=PromptResponse)
async def update_prompt(
    prompt_id: int,
    prompt_update: PromptUpdate,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent)
):
    """プロンプト情報を更新"""
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id, Prompt.deleted_at.is_(None)).first()
    if not prompt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="プロンプトが見つかりません"
        )

    # 更新
    if prompt_update.name:
        prompt.name = prompt_update.name
    if prompt_update.description is not None:
        prompt.description = prompt_update.description
    if prompt_update.content:
        prompt.encrypted_content = encryption_service.encrypt(prompt_update.content)
    if prompt_update.model_type:
        prompt.model_type = prompt_update.model_type
    if prompt_update.input_schema is not None:
        prompt.input_schema = json.dumps(prompt_update.input_schema)
    if prompt_update.is_active is not None:
        prompt.is_active = prompt_update.is_active
    if prompt_update.allows_file_output is not None:
        prompt.allows_file_output = prompt_update.allows_file_output
    if prompt_update.enable_deep_think is not None:
        prompt.enable_deep_think = prompt_update.enable_deep_think

    db.commit()
    db.refresh(prompt)

    # input_schemaをJSON文字列からdictに変換
    prompt_dict = prompt.__dict__.copy()
    if prompt.input_schema:
        try:
            prompt_dict['input_schema'] = json.loads(prompt.input_schema)
        except:
            prompt_dict['input_schema'] = None

    return prompt_dict


@router.delete("/prompts/{prompt_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_prompt(
    prompt_id: int,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent)
):
    """プロンプトを論理削除"""
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id, Prompt.deleted_at.is_(None)).first()
    if not prompt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="プロンプトが見つかりません"
        )

    # 論理削除: deleted_atに現在時刻を設定
    from datetime import datetime, timezone, timedelta
    jst = timezone(timedelta(hours=9))
    prompt.deleted_at = datetime.now(jst)
    db.commit()


# ==================== プロンプト割り当て ====================
@router.post("/assign-prompt", response_model=AccountPromptResponse, status_code=status.HTTP_201_CREATED)
async def assign_prompt_to_account(
    assignment: AccountPromptAssign,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent)
):
    """アカウントにプロンプトを割り当て"""
    # アカウントの存在確認
    account = db.query(Account).filter(Account.id == assignment.account_id).first()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="アカウントが見つかりません"
        )

    # プロンプトの存在確認（論理削除されていないもののみ）
    prompt = db.query(Prompt).filter(Prompt.id == assignment.prompt_id, Prompt.deleted_at.is_(None)).first()
    if not prompt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="プロンプトが見つかりません"
        )

    # 既に割り当てられているかチェック
    existing = db.query(AccountPrompt).filter(
        AccountPrompt.account_id == assignment.account_id,
        AccountPrompt.prompt_id == assignment.prompt_id
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="このプロンプトは既に割り当てられています"
        )

    # 割り当て
    account_prompt = AccountPrompt(
        account_id=assignment.account_id,
        prompt_id=assignment.prompt_id
    )
    db.add(account_prompt)
    db.commit()
    db.refresh(account_prompt)

    return account_prompt


@router.delete("/assign-prompt/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unassign_prompt_from_account(
    assignment_id: int,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent)
):
    """アカウントからプロンプトの割り当てを解除"""
    assignment = db.query(AccountPrompt).filter(AccountPrompt.id == assignment_id).first()
    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="割り当てが見つかりません"
        )

    db.delete(assignment)
    db.commit()


@router.get("/accounts/{account_id}/prompts")
async def get_account_prompts(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent)
):
    """特定のアカウントに割り当てられたプロンプト一覧を取得（assignment_idを含む）"""
    assignments = db.query(AccountPrompt).filter(
        AccountPrompt.account_id == account_id
    ).all()

    # input_schemaをJSON文字列からdictに変換
    result = []
    for assignment in assignments:
        prompt = assignment.prompt
        assignment_id = assignment.id  # assignment_idを先に取得

        # 必要なフィールドのみを明示的に取得
        prompt_dict = {
            'id': prompt.id,
            'name': prompt.name,
            'description': prompt.description,
            'model_type': prompt.model_type,
            'is_active': prompt.is_active,
            'allows_file_output': prompt.allows_file_output,
            'created_by': prompt.created_by,
            'created_at': prompt.created_at.isoformat() if prompt.created_at else None,
            'updated_at': prompt.updated_at.isoformat() if prompt.updated_at else None,
            'assignment_id': assignment_id  # assignment_idを追加
        }
        # input_schemaをJSON文字列からdictに変換
        if prompt.input_schema:
            try:
                prompt_dict['input_schema'] = json.loads(prompt.input_schema)
            except:
                prompt_dict['input_schema'] = None
        else:
            prompt_dict['input_schema'] = None

        result.append(prompt_dict)

    return result


# ==================== 実行ログ ====================
@router.get("/executions")
async def list_executions(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent)
):
    """全実行ログを取得"""
    # 総件数を取得
    total = db.query(Execution).count()

    executions = db.query(Execution).order_by(
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

