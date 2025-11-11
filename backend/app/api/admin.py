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
    total_prompts = db.query(Prompt).count()
    total_executions = db.query(Execution).count()

    # 今日の実行数
    from datetime import datetime, timedelta
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    executions_today = db.query(Execution).filter(Execution.executed_at >= today_start).count()

    # 今月の実行数
    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    executions_this_month = db.query(Execution).filter(Execution.executed_at >= month_start).count()

    return {
        "total_accounts": total_accounts,
        "total_prompts": total_prompts,
        "total_executions": total_executions,
        "executions_today": executions_today,
        "executions_this_month": executions_this_month
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
        api_config = APIConfig(account_id=db_account.id)
        db.add(api_config)
        db.commit()

    return db_account


@router.get("/accounts", response_model=List[AccountWithPromptCount])
async def list_accounts(
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent)
):
    """全アカウントを取得（子アカウントのみ）"""
    accounts = db.query(
        Account,
        func.count(AccountPrompt.id).label('prompt_count'),
        func.count(Execution.id).label('execution_count')
    ).outerjoin(
        AccountPrompt, Account.id == AccountPrompt.account_id
    ).outerjoin(
        Execution, Account.id == Execution.account_id
    ).filter(
        Account.account_type == AccountType.CHILD
    ).group_by(Account.id).all()

    return [
        {
            "id": acc.id,
            "username": acc.username,
            "email": acc.email,
            "account_type": acc.account_type,
            "is_active": acc.is_active,
            "prompt_count": prompt_count,
            "execution_count": execution_count
        }
        for acc, prompt_count, execution_count in accounts
    ]


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

    # 更新
    if account_update.email:
        account.email = account_update.email
    if account_update.password:
        account.hashed_password = get_password_hash(account_update.password)
    if account_update.is_active is not None:
        account.is_active = account_update.is_active

    db.commit()
    db.refresh(account)
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


@router.get("/prompts", response_model=List[PromptResponse])
async def list_prompts(
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent)
):
    """全プロンプトを取得"""
    prompts = db.query(Prompt).all()

    # input_schemaをJSON文字列からdictに変換
    result = []
    for prompt in prompts:
        prompt_dict = prompt.__dict__.copy()
        if prompt.input_schema:
            try:
                prompt_dict['input_schema'] = json.loads(prompt.input_schema)
            except:
                prompt_dict['input_schema'] = None
        result.append(prompt_dict)

    return result


@router.get("/prompts/{prompt_id}", response_model=PromptResponse)
async def get_prompt(
    prompt_id: int,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent)
):
    """特定のプロンプトを取得"""
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
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
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
    if not prompt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="プロンプトが見つかりません"
        )

    # 復号化
    decrypted_content = encryption_service.decrypt(prompt.encrypted_content)
    return {"content": decrypted_content}


@router.patch("/prompts/{prompt_id}", response_model=PromptResponse)
async def update_prompt(
    prompt_id: int,
    prompt_update: PromptUpdate,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent)
):
    """プロンプト情報を更新"""
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
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
    """プロンプトを削除"""
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
    if not prompt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="プロンプトが見つかりません"
        )

    db.delete(prompt)
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

    # プロンプトの存在確認
    prompt = db.query(Prompt).filter(Prompt.id == assignment.prompt_id).first()
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


@router.get("/accounts/{account_id}/prompts", response_model=List[PromptResponse])
async def get_account_prompts(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent)
):
    """特定のアカウントに割り当てられたプロンプト一覧を取得"""
    prompts = db.query(Prompt).join(
        AccountPrompt, Prompt.id == AccountPrompt.prompt_id
    ).filter(
        AccountPrompt.account_id == account_id
    ).all()

    # input_schemaをJSON文字列からdictに変換
    result = []
    for prompt in prompts:
        prompt_dict = prompt.__dict__.copy()
        if prompt.input_schema:
            try:
                prompt_dict['input_schema'] = json.loads(prompt.input_schema)
            except:
                prompt_dict['input_schema'] = None
        result.append(prompt_dict)

    return result


# ==================== 実行ログ ====================
@router.get("/executions", response_model=List[ExecutionResponse])
async def list_executions(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent)
):
    """全実行ログを取得"""
    executions = db.query(Execution).order_by(
        Execution.executed_at.desc()
    ).offset(skip).limit(limit).all()

    result = []
    for execution in executions:
        prompt_name = execution.prompt.name if execution.prompt else None
        result.append({
            **execution.__dict__,
            "prompt_name": prompt_name
        })

    return result

