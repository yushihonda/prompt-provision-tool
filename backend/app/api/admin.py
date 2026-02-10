from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List
from app.database import get_db
from app.auth import get_current_active_parent, get_password_hash
from app.models import Account, Prompt, AccountPrompt, Execution, APIConfig, AccountType, Workflow, WorkflowSkill
from app.schemas import (
    AccountCreate,
    AccountResponse,
    AccountUpdate,
    AccountWithPromptCount,
    PromptCreate,
    PromptResponse,
    PromptUpdate,
    AccountPromptAssign,
    AccountPromptResponse,
    DashboardStats,
    ExecutionResponse,
    CeleryWorkerStats,
    CeleryWorkerInfo,
    RedisStats,
    TaskStats,
    WorkflowCreate,
    WorkflowCreateWithPrompt,
    WorkflowUpdate,
    WorkflowResponse,
    WorkflowSkillItem,
    WorkflowSkillsUpdateRequest,
    WorkflowListItem,
)
from app.encryption import encryption_service
import json
import logging

logger = logging.getLogger(__name__)

# Celery/Redis監視用の遅延インポート
try:
    from app.celery_app import celery_app
    from app.services.redis_service import get_redis_client
    CELERY_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Celery/Redis not available: {str(e)}")
    CELERY_AVAILABLE = False
    celery_app = None

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
        is_active=True,
        allows_file_output=prompt.allows_file_output,
        enable_deep_think=prompt.enable_deep_think,
        enable_web_search=prompt.enable_web_search,
       enable_code_interpreter=prompt.enable_code_interpreter,
        enable_file_search=prompt.enable_file_search,
        created_by=current_user.id
    )
    db.add(db_prompt)
    db.commit()
    db.refresh(db_prompt)

    # input_schemaをJSON文字列からdictに変換
    input_schema = None
    if db_prompt.input_schema:
        try:
            input_schema = json.loads(db_prompt.input_schema)
        except:
            input_schema = None

    # PromptResponseスキーマに合致するフィールドのみを返す（encrypted_contentは含めない）
    return PromptResponse(
        id=db_prompt.id,
        name=db_prompt.name,
        description=db_prompt.description,
        model_type=db_prompt.model_type,
        input_schema=input_schema,
        allows_file_output=db_prompt.allows_file_output,
        enable_deep_think=db_prompt.enable_deep_think,
        enable_web_search=db_prompt.enable_web_search,
        enable_code_interpreter=db_prompt.enable_code_interpreter,
        enable_file_search=db_prompt.enable_file_search,
        is_active=db_prompt.is_active,
        created_by=db_prompt.created_by,
        created_at=db_prompt.created_at,
        updated_at=db_prompt.updated_at
    )


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
        input_schema = None
        if prompt.input_schema:
            try:
                input_schema = json.loads(prompt.input_schema)
            except:
                input_schema = None
        
        # PromptResponseスキーマに合致するフィールドのみを返す（encrypted_contentは含めない）
        items.append(
            PromptResponse(
                id=prompt.id,
                name=prompt.name,
                description=prompt.description,
                model_type=prompt.model_type,
                input_schema=input_schema,
                allows_file_output=prompt.allows_file_output,
                enable_deep_think=prompt.enable_deep_think,
                enable_web_search=prompt.enable_web_search,
                enable_code_interpreter=prompt.enable_code_interpreter,
                enable_file_search=prompt.enable_file_search,
                is_active=prompt.is_active,
                created_by=prompt.created_by,
                created_at=prompt.created_at,
                updated_at=prompt.updated_at,
            )
        )

    return {
        "items": items,
        "total": total,
        "skip": skip,
        "limit": limit
    }


# ==================== ワークフロー管理 ====================


@router.get("/workflows")
async def list_workflows(
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent),
):
    """ワークフロー一覧を取得（論理削除されていないもののみ）"""
    query = db.query(Workflow).filter(Workflow.deleted_at.is_(None))
    total = query.count()

    workflows = (
        query.order_by(Workflow.created_at.desc()).offset(skip).limit(limit).all()
    )

    items: list[WorkflowListItem] = []
    for wf in workflows:
        # input_schema を JSON から dict に変換
        workflow_input_schema = None
        if getattr(wf, "input_schema", None):
            try:
                workflow_input_schema = (
                    json.loads(wf.input_schema)
                    if isinstance(wf.input_schema, str)
                    else wf.input_schema
                )
            except Exception:
                workflow_input_schema = None

        items.append(
            WorkflowListItem(
                id=wf.id,
                name=wf.name,
                description=wf.description,
                input_schema=workflow_input_schema,
                is_active=wf.is_active,
                leader_prompt_id=wf.leader_prompt_id,
                created_at=wf.created_at,
                updated_at=wf.updated_at,
            )
        )

    return {
        "items": items,
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.post("/workflows/with-prompt", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
async def create_workflow_with_prompt(
    request: WorkflowCreateWithPrompt,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent),
):
    """親プロンプトと子プロンプト（Skills）を含むワークフローを一括作成"""
    # 1. 親プロンプト（統合プロンプト）を作成
    encrypted_content = encryption_service.encrypt(request.leader_prompt.content)
    
    # input_schemaをJSON文字列に変換
    input_schema_str = None
    if request.leader_prompt.input_schema:
        input_schema_str = json.dumps(request.leader_prompt.input_schema, ensure_ascii=False)
    
    leader_prompt = Prompt(
        name=request.leader_prompt.name,
        description=request.leader_prompt.description,
        encrypted_content=encrypted_content,
        model_type=request.leader_prompt.model_type,
        input_schema=input_schema_str,
        is_active=True,
        created_by=current_user.id,
        enable_deep_think=request.leader_prompt.enable_deep_think,
        enable_web_search=request.leader_prompt.enable_web_search,
        enable_code_interpreter=request.leader_prompt.enable_code_interpreter,
        enable_file_search=request.leader_prompt.enable_file_search,
    )
    db.add(leader_prompt)
    db.flush()  # IDを取得
    
    # 2. ワークフローを作成
    workflow_input_schema_str = None
    if request.input_schema is not None:
        try:
            workflow_input_schema_str = json.dumps(
                request.input_schema, ensure_ascii=False
            )
        except Exception:
            workflow_input_schema_str = None

    db_wf = Workflow(
        name=request.name,
        description=request.description,
        input_schema=workflow_input_schema_str,
        is_active=request.is_active,
        created_by=current_user.id,
        leader_prompt_id=leader_prompt.id,
    )
    db.add(db_wf)
    db.flush()  # IDを取得
    
    # 3. 子プロンプト（Skills）を登録
    for skill_item in request.skills:
        # プロンプトの存在確認
        prompt = db.query(Prompt).filter(
            Prompt.id == skill_item.prompt_id,
            Prompt.deleted_at.is_(None)
        ).first()
        if not prompt:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"プロンプトID {skill_item.prompt_id} が見つかりません"
            )
        
        config_json_str = None
        if skill_item.config_json:
            config_json_str = json.dumps(skill_item.config_json, ensure_ascii=False)
        
        workflow_skill = WorkflowSkill(
            workflow_id=db_wf.id,
            prompt_id=skill_item.prompt_id,
            step_order=skill_item.step_order,
            step_name=skill_item.step_name,
            config_json=config_json_str,
        )
        db.add(workflow_skill)
    
    db.commit()
    db.refresh(db_wf)
    
    return _build_workflow_response(db_wf, db)


@router.post("/workflows", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    workflow: WorkflowCreate,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent),
):
    """
    新しいワークフローを作成（自動親プロンプト生成版）

    - Workflow レコードを作成
    - leader_prompt_id が指定されていない場合は、このワークフロー専用の統合プロンプト（親プロンプト）を自動作成して紐づける
    """
    # 1. Workflow本体を先に作成
    workflow_input_schema_str = None
    if workflow.input_schema is not None:
        try:
            workflow_input_schema_str = json.dumps(
                workflow.input_schema, ensure_ascii=False
            )
        except Exception:
            workflow_input_schema_str = None

    db_wf = Workflow(
        name=workflow.name,
        description=workflow.description,
        input_schema=workflow_input_schema_str,
        is_active=workflow.is_active,
        created_by=current_user.id,
        leader_prompt_id=workflow.leader_prompt_id,
    )
    db.add(db_wf)
    db.commit()
    db.refresh(db_wf)

    # 2. leader_prompt_id が未指定なら、このワークフロー専用の統合プロンプトを1つ自動生成して紐づける
    if db_wf.leader_prompt_id is None:
        # デフォルトのモデルは GPT-5.1 を利用（必要に応じて後から編集可能）
        default_model = "gpt-5.1"

        default_content = (
            "あなたはワークフローの統合エージェントです。\n"
            "all_step_results に、各ステップ（子プロンプト / Skills）の結果が配列として渡されます。\n"
            "- previous_output / previous_step_result: 直前ステップの結果\n"
            "- all_step_results: これまでの全成功ステップの詳細（step_order, prompt_id, output など）\n\n"
            "これらを踏まえて、ユーザーへの最終回答を日本語でわかりやすく統合してください。"
        )

        encrypted_content = encryption_service.encrypt(default_content)

        leader_prompt = Prompt(
            name=f"[WF:{db_wf.id}] {db_wf.name} - 統合プロンプト",
            description=f"ワークフロー「{db_wf.name}」用の最終統合プロンプトです。",
            encrypted_content=encrypted_content,
            model_type=default_model,
            input_schema=None,
            is_active=True,
            allows_file_output=False,
            enable_deep_think=True,
            enable_web_search=False,
            enable_code_interpreter=False,
            enable_file_search=False,
            created_by=current_user.id,
        )
        db.add(leader_prompt)
        db.commit()
        db.refresh(leader_prompt)

        db_wf.leader_prompt_id = leader_prompt.id
        db.commit()
        db.refresh(db_wf)

    return _build_workflow_response(db_wf, db)


def _build_workflow_response(db_wf: Workflow, db: Session) -> WorkflowResponse:
    """内部用: Workflow + Skills を組み立てて返す"""
    skills: list[WorkflowSkillItem] = []
    wf_skills = (
        db.query(WorkflowSkill)
        .join(Prompt, Prompt.id == WorkflowSkill.prompt_id)
        .filter(WorkflowSkill.workflow_id == db_wf.id)
        .order_by(WorkflowSkill.step_order.asc(), WorkflowSkill.id.asc())
        .all()
    )
    for ws in wf_skills:
        skills.append(
            WorkflowSkillItem(
                id=ws.id,
                step_order=ws.step_order,
                step_name=ws.step_name,
                prompt_id=ws.prompt_id,
                prompt_name=ws.prompt.name if ws.prompt else None,
            )
        )

    workflow_input_schema = None
    if getattr(db_wf, "input_schema", None):
        try:
            workflow_input_schema = (
                json.loads(db_wf.input_schema)
                if isinstance(db_wf.input_schema, str)
                else db_wf.input_schema
            )
        except Exception:
            workflow_input_schema = None

    return WorkflowResponse(
        id=db_wf.id,
        name=db_wf.name,
        description=db_wf.description,
        input_schema=workflow_input_schema,
        is_active=db_wf.is_active,
        leader_prompt_id=db_wf.leader_prompt_id,
        created_by=db_wf.created_by,
        created_at=db_wf.created_at,
        updated_at=db_wf.updated_at,
        deleted_at=db_wf.deleted_at,
        skills=skills,
    )


@router.get("/workflows/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow_detail(
    workflow_id: int,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent),
):
    """ワークフロー詳細（Skill一覧込み）を取得"""
    wf = (
        db.query(Workflow)
        .filter(Workflow.id == workflow_id, Workflow.deleted_at.is_(None))
        .first()
    )
    if not wf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ワークフローが見つかりません",
        )

    return _build_workflow_response(wf, db)


@router.patch("/workflows/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow(
    workflow_id: int,
    workflow_update: WorkflowUpdate,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent),
):
    """ワークフロー基本情報を更新"""
    wf = (
        db.query(Workflow)
        .filter(Workflow.id == workflow_id, Workflow.deleted_at.is_(None))
        .first()
    )
    if not wf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ワークフローが見つかりません",
        )

    if workflow_update.name is not None:
        wf.name = workflow_update.name
    if workflow_update.description is not None:
        wf.description = workflow_update.description
    if workflow_update.input_schema is not None:
        try:
            wf.input_schema = json.dumps(workflow_update.input_schema, ensure_ascii=False)
        except Exception:
            wf.input_schema = None
    if workflow_update.is_active is not None:
        wf.is_active = workflow_update.is_active
    if workflow_update.leader_prompt_id is not None:
        # 存在チェックはここでは行わず、管理画面側での選択に委ねる
        wf.leader_prompt_id = workflow_update.leader_prompt_id

    db.commit()
    db.refresh(wf)

    return _build_workflow_response(wf, db)


@router.delete("/workflows/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(
    workflow_id: int,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent),
):
    """ワークフローを論理削除"""
    wf = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not wf or wf.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ワークフローが見つかりません",
        )

    from datetime import datetime, timezone, timedelta

    jst = timezone(timedelta(hours=9))
    wf.deleted_at = datetime.now(jst)
    db.commit()


@router.put("/workflows/{workflow_id}/skills", response_model=WorkflowResponse)
async def update_workflow_skills(
    workflow_id: int,
    body: WorkflowSkillsUpdateRequest,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent),
):
    """ワークフロー内のSkill構成を一括更新"""
    wf = (
        db.query(Workflow)
        .filter(Workflow.id == workflow_id, Workflow.deleted_at.is_(None))
        .first()
    )
    if not wf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ワークフローが見つかりません",
        )

    # すべてのprompt_idが存在し、論理削除されていないことを確認
    prompt_ids = {item.prompt_id for item in body.skills}
    if prompt_ids:
        existing_prompts = (
            db.query(Prompt)
            .filter(Prompt.id.in_(prompt_ids), Prompt.deleted_at.is_(None))
            .all()
        )
        if len(existing_prompts) != len(prompt_ids):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="存在しない、または削除されたプロンプトが含まれています",
            )

    # 既存のWorkflowSkillを削除して、指定された構成で作り直す
    db.query(WorkflowSkill).filter(WorkflowSkill.workflow_id == workflow_id).delete()
    db.commit()

    for item in body.skills:
        config_json_str = None
        if item.config_json is not None:
            try:
                config_json_str = json.dumps(item.config_json, ensure_ascii=False)
            except Exception:
                config_json_str = None

        ws = WorkflowSkill(
            workflow_id=workflow_id,
            prompt_id=item.prompt_id,
            step_order=item.step_order,
            step_name=item.step_name,
            config_json=config_json_str,
        )
        db.add(ws)

    db.commit()

    db.refresh(wf)
    return _build_workflow_response(wf, db)


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
    input_schema = None
    if prompt.input_schema:
        try:
            input_schema = json.loads(prompt.input_schema)
        except:
            input_schema = None

    # PromptResponseスキーマに合致するフィールドのみを返す（encrypted_contentは含めない）
    return PromptResponse(
        id=prompt.id,
        name=prompt.name,
        description=prompt.description,
        model_type=prompt.model_type,
        input_schema=input_schema,
        allows_file_output=prompt.allows_file_output,
        enable_deep_think=prompt.enable_deep_think,
        enable_web_search=prompt.enable_web_search,
        enable_code_interpreter=prompt.enable_code_interpreter,
        enable_file_search=prompt.enable_file_search,
        is_active=prompt.is_active,
        created_by=prompt.created_by,
        created_at=prompt.created_at,
        updated_at=prompt.updated_at,
    )


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
    if prompt_update.enable_web_search is not None:
        prompt.enable_web_search = prompt_update.enable_web_search
    if prompt_update.enable_code_interpreter is not None:
        prompt.enable_code_interpreter = prompt_update.enable_code_interpreter
    if prompt_update.enable_file_search is not None:
        prompt.enable_file_search = prompt_update.enable_file_search

    db.commit()
    db.refresh(prompt)

    # input_schemaをJSON文字列からdictに変換
    input_schema = None
    if prompt.input_schema:
        try:
            input_schema = json.loads(prompt.input_schema)
        except:
            input_schema = None

    # PromptResponseスキーマに合致するフィールドのみを返す（encrypted_contentは含めない）
    return PromptResponse(
        id=prompt.id,
        name=prompt.name,
        description=prompt.description,
        model_type=prompt.model_type,
        input_schema=input_schema,
        allows_file_output=prompt.allows_file_output,
        enable_deep_think=prompt.enable_deep_think,
        enable_web_search=prompt.enable_web_search,
        enable_code_interpreter=prompt.enable_code_interpreter,
        enable_file_search=prompt.enable_file_search,
        is_active=prompt.is_active,
        created_by=prompt.created_by,
        created_at=prompt.created_at,
        updated_at=prompt.updated_at,
    )


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

        # output_formatを取得（モデルから直接取得）
        output_format = getattr(execution, 'output_format', None)
        if output_format is None:
            output_format = 'txt'  # デフォルト値

        # ExecutionResponseスキーマに合致するフィールドのみを返す（encrypted_contentやリレーションオブジェクトは含めない）
        execution_dict = {
            "id": execution.id,
            "account_id": execution.account_id,
            "prompt_id": execution.prompt_id,
            "prompt_name": prompt_name,
            "input_data": execution.input_data,
            "output_data": execution.output_data,
            "model_used": execution.model_used,
            "tokens_used": execution.tokens_used,
            "execution_time": execution.execution_time,
            "status": execution.status,
            "error_message": execution.error_message,
            "executed_at": execution.executed_at,
            "output_format": output_format,
            "enable_deep_think": bool(enable_deep_think) if enable_deep_think is not None else None
        }
        items.append(execution_dict)

    return {
        "items": items,
        "total": total,
        "skip": skip,
        "limit": limit
    }


# ==================== 監視機能 ====================
@router.get("/monitor/celery", response_model=CeleryWorkerStats)
async def get_celery_worker_stats(
    current_user: Account = Depends(get_current_active_parent)
):
    """Celery Workerの監視情報を取得"""
    if not CELERY_AVAILABLE or not celery_app:
        return CeleryWorkerStats(
            workers=[],
            total_workers=0,
            total_active_tasks=0,
            total_reserved_tasks=0,
            celery_available=False
        )
    
    try:
        inspect = celery_app.control.inspect()
        
        # 実行中のタスク
        active_tasks = inspect.active() or {}
        
        # 待機中のタスク
        reserved_tasks = inspect.reserved() or {}
        
        # Worker統計情報
        stats = inspect.stats() or {}
        
        # Worker一覧を構築
        workers = []
        total_active = 0
        total_reserved = 0
        
        # すべてのWorker名を取得（active, reserved, statsのキーから）
        all_worker_names = set()
        all_worker_names.update(active_tasks.keys())
        all_worker_names.update(reserved_tasks.keys())
        all_worker_names.update(stats.keys())
        
        for worker_name in all_worker_names:
            worker_active = active_tasks.get(worker_name, [])
            worker_reserved = reserved_tasks.get(worker_name, [])
            worker_stats = stats.get(worker_name, {})
            
            active_count = len(worker_active)
            reserved_count = len(worker_reserved)
            total_active += active_count
            total_reserved += reserved_count
            
            workers.append(CeleryWorkerInfo(
                name=worker_name,
                status="online" if worker_name in stats else "offline",
                active_tasks=active_count,
                reserved_tasks=reserved_count,
                total_tasks_completed=worker_stats.get("total", {}).get("tasks.succeeded", 0) if isinstance(worker_stats.get("total"), dict) else None,
                total_tasks_failed=worker_stats.get("total", {}).get("tasks.failed", 0) if isinstance(worker_stats.get("total"), dict) else None
            ))
        
        return CeleryWorkerStats(
            workers=workers,
            total_workers=len(workers),
            total_active_tasks=total_active,
            total_reserved_tasks=total_reserved,
            celery_available=True
        )
    except Exception as e:
        logger.error(f"Failed to get Celery worker stats: {str(e)}")
        return CeleryWorkerStats(
            workers=[],
            total_workers=0,
            total_active_tasks=0,
            total_reserved_tasks=0,
            celery_available=False
        )


@router.get("/monitor/redis", response_model=RedisStats)
async def get_redis_stats(
    current_user: Account = Depends(get_current_active_parent)
):
    """Redisの監視情報を取得"""
    if not CELERY_AVAILABLE:
        return RedisStats(
            connection_status="disconnected",
            stream_count=0,
            active_streams=[]
        )
    
    try:
        redis_client = get_redis_client()
        
        # 接続確認
        try:
            redis_client.ping()
            connection_status = "connected"
        except Exception:
            connection_status = "disconnected"
            return RedisStats(
                connection_status=connection_status,
                stream_count=0,
                active_streams=[]
            )
        
        # メモリ情報
        memory_info = redis_client.info('memory')
        memory_used = memory_info.get('used_memory', 0) / (1024 * 1024)  # MB
        memory_max = memory_info.get('maxmemory', 0) / (1024 * 1024) if memory_info.get('maxmemory', 0) > 0 else None  # MB
        memory_usage_percent = (memory_used / memory_max * 100) if memory_max and memory_max > 0 else None
        
        # Stream一覧（execution:*パターン）
        stream_keys = redis_client.keys('execution:*')
        stream_count = len(stream_keys)
        # アクティブなStream一覧（最大10件）
        active_streams = [key.replace('execution:', '') for key in stream_keys[:10]]
        
        return RedisStats(
            connection_status=connection_status,
            memory_used_mb=memory_used,
            memory_max_mb=memory_max,
            memory_usage_percent=memory_usage_percent,
            stream_count=stream_count,
            active_streams=active_streams
        )
    except Exception as e:
        logger.error(f"Failed to get Redis stats: {str(e)}")
        return RedisStats(
            connection_status="disconnected",
            stream_count=0,
            active_streams=[]
        )


@router.get("/monitor/tasks", response_model=TaskStats)
async def get_task_stats(
    hours: int = 24,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent)
):
    """タスクの実行統計を取得"""
    from datetime import datetime, timedelta, timezone
    
    try:
        # 期間の開始時刻を計算（JST）
        jst = timezone(timedelta(hours=9))
        now = datetime.now(jst)
        start_time = now - timedelta(hours=hours)
        
        # 期間内の実行を取得
        executions = db.query(Execution).filter(
            Execution.executed_at >= start_time
        ).all()
        
        total_executions = len(executions)
        successful = sum(1 for e in executions if e.status == "success")
        failed = sum(1 for e in executions if e.status == "error")
        cancelled = sum(1 for e in executions if e.status == "cancelled")
        
        # 成功率・エラー率
        success_rate = successful / total_executions if total_executions > 0 else 0.0
        error_rate = failed / total_executions if total_executions > 0 else 0.0
        
        # 実行時間の統計
        execution_times = [e.execution_time for e in executions if e.execution_time is not None]
        average_execution_time_ms = sum(execution_times) / len(execution_times) if execution_times else None
        max_execution_time_ms = max(execution_times) if execution_times else None
        
        return TaskStats(
            period_hours=hours,
            total_executions=total_executions,
            successful=successful,
            failed=failed,
            cancelled=cancelled,
            success_rate=success_rate,
            error_rate=error_rate,
            average_execution_time_ms=average_execution_time_ms,
            max_execution_time_ms=max_execution_time_ms
        )
    except Exception as e:
        logger.error(f"Failed to get task stats: {str(e)}")
        return TaskStats(
            period_hours=hours,
            total_executions=0,
            successful=0,
            failed=0,
            cancelled=0,
            success_rate=0.0,
            error_rate=0.0,
            average_execution_time_ms=None,
            max_execution_time_ms=None
        )

