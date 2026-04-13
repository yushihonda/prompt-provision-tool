from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from app.database import get_db
from app.auth import get_current_active_parent, get_password_hash
from app.models import Account, Skill, AccountSkill, Execution, APIConfig, AccountType, Workflow, WorkflowSkill, WorkflowExecution
from app.schemas import (
    AccountCreate,
    AccountResponse,
    AccountUpdate,
    AccountWithSkillCount,
    SkillCreate,
    SkillResponse,
    SkillUpdate,
    AccountSkillAssign,
    AccountSkillResponse,
    DashboardStats,
    ExecutionResponse,
    CeleryWorkerStats,
    CeleryWorkerInfo,
    RedisStats,
    TaskStats,
    WorkflowCreate,
    WorkflowCreateWithParentSkill,
    WorkflowUpdate,
    WorkflowResponse,
    WorkflowSkillItem,
    WorkflowSkillsUpdateRequest,
    WorkflowListItem,
)
from app.encryption import encryption_service
from app.services.agent_profiles import normalize_agent_profile
import json
import logging

logger = logging.getLogger(__name__)


def _validate_parallel_group_profiles(groups) -> None:
    for grp in groups or []:
        if getattr(grp, "execution_type", None) != "parallel":
            continue
        profiles = {
            normalize_agent_profile(getattr(skill, "agent_profile", None) or "default")
            for skill in (getattr(grp, "skills", None) or [])
        }
        if len(profiles) > 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="parallel group では mixed agent_profile を許可していません。MVP では同一 profile に揃えてください",
            )


# Redis 監視用
try:
    from app.services.redis_service import get_redis_client
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

router = APIRouter(prefix="/api/admin", tags=["管理者"])


# ==================== ダッシュボード ====================
@router.get("/dashboard", response_model=DashboardStats)
async def get_dashboard_stats(
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent)
):
    """ダッシュボード統計情報を取得"""
    total_accounts = db.query(Account).filter(Account.account_type == AccountType.CHILD).count()
    total_skills = db.query(Skill).filter(Skill.deleted_at.is_(None)).count()
    total_workflows = db.query(Workflow).filter(Workflow.deleted_at.is_(None)).count()
    # 総実行回数はAccount.total_executionsの合計を使用（保存された値）
    total_executions = db.query(func.sum(Account.total_executions)).scalar() or 0
    total_executions = int(total_executions)  # Decimal型をintに変換

    return {
        "total_accounts": total_accounts,
        "total_skills": total_skills,
        "total_workflows": total_workflows,
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
            openai_api_key=encryption_service.encrypt_api_key(account.openai_api_key) if account.openai_api_key else None,
            gemini_api_key=encryption_service.encrypt_api_key(account.gemini_api_key) if account.gemini_api_key else None,
            anthropic_api_key=encryption_service.encrypt_api_key(account.anthropic_api_key) if account.anthropic_api_key else None,
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
    limit = min(limit, 100)
    # 総件数を取得
    total = db.query(Account).count()

    # アカウント一覧を取得
    accounts = db.query(Account).order_by(Account.id.desc()).offset(skip).limit(limit).all()

    from app.services.account_stats import check_and_reset_monthly_stats

    # 一括プリフェッチ: アカウントごとスキル数、WF→skill_id マッピング
    account_ids = [a.id for a in accounts]
    # スキル数を一括取得
    skill_counts_rows = (
        db.query(AccountSkill.account_id, func.count(AccountSkill.id))
        .filter(AccountSkill.account_id.in_(account_ids))
        .group_by(AccountSkill.account_id)
        .all()
    )
    skill_counts_map = dict(skill_counts_rows)
    # アカウントごとの割り当て済みスキルIDを一括取得
    assigned_rows = (
        db.query(AccountSkill.account_id, AccountSkill.skill_id)
        .filter(AccountSkill.account_id.in_(account_ids))
        .all()
    )
    assigned_map: dict[int, set] = {}
    for acc_id, sid in assigned_rows:
        assigned_map.setdefault(acc_id, set()).add(sid)
    # 有効ワークフローとそのスキルIDを一括取得（ループ外で1回だけ）
    active_wfs = db.query(Workflow).filter(Workflow.is_active == True, Workflow.deleted_at.is_(None)).all()
    wf_ids = [w.id for w in active_wfs]
    wf_skill_rows = (
        db.query(WorkflowSkill.workflow_id, WorkflowSkill.skill_id)
        .filter(WorkflowSkill.workflow_id.in_(wf_ids), WorkflowSkill.skill_id.isnot(None))
        .all()
    ) if wf_ids else []
    wf_skill_map: dict[int, set] = {}
    for wid, sid in wf_skill_rows:
        wf_skill_map.setdefault(wid, set()).add(sid)

    items = []
    for acc in accounts:
        skill_count = skill_counts_map.get(acc.id, 0)

        # 割り当て済みスキルIDから有効ワークフロー数を計算（プリフェッチ済みデータで判定）
        assigned_ids = assigned_map.get(acc.id, set())
        wf_count = 0
        for wf in active_wfs:
            wf_skill_ids = wf_skill_map.get(wf.id, set())
            if wf_skill_ids and wf_skill_ids.issubset(assigned_ids):
                wf_count += 1

        # 月が変わっていたら月次カウンターをリセット
        check_and_reset_monthly_stats(acc, db)
        executions_this_month = acc.executions_this_month or 0

        # 総トークン数、総料金、総実行回数はAccountモデルから取得（保存された値を使用）
        total_tokens = acc.total_tokens or 0
        total_cost = float(acc.total_cost or 0.0)
        total_executions = acc.total_executions or 0

        # 今月のトークン数と料金も取得
        tokens_this_month = acc.tokens_this_month or 0
        cost_this_month = float(acc.cost_this_month or 0.0)

        # API設定情報を取得（子アカウントのみ）— キーはマスク表示
        api_config_data = None
        if str(acc.account_type) == AccountType.CHILD:
            api_config = db.query(APIConfig).filter(APIConfig.account_id == acc.id).first()
            if api_config:
                # 暗号化されたキーを復号→マスク表示
                openai_masked = None
                gemini_masked = None
                if api_config.openai_api_key:
                    try:
                        openai_masked = encryption_service.mask_api_key(
                            encryption_service.decrypt_api_key(api_config.openai_api_key)
                        )
                    except Exception:
                        openai_masked = "****"
                if api_config.gemini_api_key:
                    try:
                        gemini_masked = encryption_service.mask_api_key(
                            encryption_service.decrypt_api_key(api_config.gemini_api_key)
                        )
                    except Exception:
                        gemini_masked = "****"
                anthropic_masked = None
                if api_config.anthropic_api_key:
                    try:
                        anthropic_masked = encryption_service.mask_api_key(
                            encryption_service.decrypt_api_key(api_config.anthropic_api_key)
                        )
                    except Exception:
                        anthropic_masked = "****"
                api_config_data = {
                    "openai_api_key": openai_masked,
                    "gemini_api_key": gemini_masked,
                    "anthropic_api_key": anthropic_masked,
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
            "skill_count": skill_count,
            "workflow_count": wf_count,
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

        # API設定を更新（値が提供されている場合のみ更新）— キーは暗号化して保存
        if account_update.openai_api_key is not None:
            stripped = account_update.openai_api_key.strip() if account_update.openai_api_key else ""
            api_config.openai_api_key = encryption_service.encrypt_api_key(stripped) if stripped else None
        if account_update.gemini_api_key is not None:
            stripped = account_update.gemini_api_key.strip() if account_update.gemini_api_key else ""
            api_config.gemini_api_key = encryption_service.encrypt_api_key(stripped) if stripped else None
        if account_update.anthropic_api_key is not None:
            stripped = account_update.anthropic_api_key.strip() if account_update.anthropic_api_key else ""
            api_config.anthropic_api_key = encryption_service.encrypt_api_key(stripped) if stripped else None
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


# ==================== スキル管理 ====================
@router.post("/skills", response_model=SkillResponse, status_code=status.HTTP_201_CREATED)
async def create_skill(
    skill: SkillCreate,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent)
):
    """新しいスキルを作成"""
    # スキルを暗号化
    encrypted_content = encryption_service.encrypt(skill.content)

    # input_schemaをJSON文字列に変換
    input_schema_str = json.dumps(skill.input_schema) if skill.input_schema else None

    # Skill-level execution_config (runtime selection) — stored as JSON
    # string in config_json. Nullable; legacy behavior when absent.
    config_json_str = json.dumps(skill.config_json) if skill.config_json else None

    db_skill = Skill(
        name=skill.name,
        description=skill.description,
        encrypted_content=encrypted_content,
        model_type=skill.model_type,
        input_schema=input_schema_str,
        config_json=config_json_str,
        is_active=True,
        allows_file_output=skill.allows_file_output,
        enable_deep_think=skill.enable_deep_think,
        default_agent_profile=getattr(skill, "default_agent_profile", None),
        created_by=current_user.id
    )
    db.add(db_skill)
    db.commit()
    db.refresh(db_skill)

    # input_schemaをJSON文字列からdictに変換
    input_schema = None
    if db_skill.input_schema:
        try:
            input_schema = json.loads(db_skill.input_schema)
        except (json.JSONDecodeError, TypeError):
            input_schema = None

    config_json_out = None
    if db_skill.config_json:
        try:
            config_json_out = json.loads(db_skill.config_json)
        except (json.JSONDecodeError, TypeError):
            config_json_out = None

    # SkillResponseスキーマに合致するフィールドのみを返す（encrypted_contentは含めない）
    return SkillResponse(
        id=db_skill.id,
        name=db_skill.name,
        description=db_skill.description,
        model_type=db_skill.model_type,
        input_schema=input_schema,
        allows_file_output=db_skill.allows_file_output,
        enable_deep_think=db_skill.enable_deep_think,
        default_agent_profile=getattr(db_skill, "default_agent_profile", None),
        config_json=config_json_out,
        is_active=db_skill.is_active,
        created_by=db_skill.created_by,
        created_at=db_skill.created_at,
        updated_at=db_skill.updated_at
    )


@router.get("/skills")
async def list_skills(
    skip: int = 0,
    limit: int = 6,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent)
):
    """全スキルを取得（ページネーション対応）"""
    limit = min(limit, 100)
    # 総件数を取得（論理削除されていないもののみ）
    total = db.query(Skill).filter(Skill.deleted_at.is_(None)).count()

    skills = db.query(Skill).filter(Skill.deleted_at.is_(None)).order_by(Skill.created_at.desc()).offset(skip).limit(limit).all()

    # input_schemaをJSON文字列からdictに変換
    items = []
    for skill in skills:
        input_schema = None
        if skill.input_schema:
            try:
                input_schema = json.loads(skill.input_schema)
            except (json.JSONDecodeError, TypeError):
                input_schema = None

        config_json_out = None
        if getattr(skill, "config_json", None):
            try:
                config_json_out = json.loads(skill.config_json)
            except (json.JSONDecodeError, TypeError):
                config_json_out = None

        # SkillResponseスキーマに合致するフィールドのみを返す（encrypted_contentは含めない）
        items.append(
            SkillResponse(
                id=skill.id,
                name=skill.name,
                description=skill.description,
                model_type=skill.model_type,
                input_schema=input_schema,
                allows_file_output=skill.allows_file_output,
                enable_deep_think=skill.enable_deep_think,
                default_agent_profile=getattr(skill, "default_agent_profile", None),
                config_json=config_json_out,
                is_active=skill.is_active,
                created_by=skill.created_by,
                created_at=skill.created_at,
                updated_at=skill.updated_at,
            )
        )

    return {
        "items": items,
        "total": total,
        "skip": skip,
        "limit": limit
    }


# ==================== ワークフロー実行ステータス ====================


@router.get("/workflow-executions/{wf_execution_id}/status")
async def get_admin_workflow_execution_status(
    wf_execution_id: int,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent),
):
    """管理者用: ワークフロー実行のステータスを取得（coordinator view 付き）"""
    wf_exec = db.query(WorkflowExecution).filter(
        WorkflowExecution.id == wf_execution_id,
    ).first()
    if not wf_exec:
        raise HTTPException(status_code=404, detail="ワークフロー実行が見つかりません")

    import json as _json
    blackboard_keys = []
    if wf_exec.blackboard_data:
        try:
            bb = _json.loads(wf_exec.blackboard_data)
            blackboard_keys = list(bb.keys())
        except (json.JSONDecodeError, TypeError):
            pass

    handoff_summary = None
    if getattr(wf_exec, "handoff_summary", None):
        try:
            handoff_summary = _json.loads(wf_exec.handoff_summary) if isinstance(wf_exec.handoff_summary, str) else wf_exec.handoff_summary
        except (_json.JSONDecodeError, TypeError):
            handoff_summary = None

    # coordinator view + synthesis events
    from app.api.user import _build_coordinator_view
    coordinator_view, computed_events = _build_coordinator_view(db, wf_exec)
    synthesis_events = computed_events
    if getattr(wf_exec, "synthesis_log", None):
        try:
            db_events = _json.loads(wf_exec.synthesis_log)
            if isinstance(db_events, list) and len(db_events) > 0:
                synthesis_events = db_events
        except (_json.JSONDecodeError, TypeError):
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
        "coordinator_view": coordinator_view,
        "synthesis_events": synthesis_events,
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

    # グループ・スキルを一括プリフェッチして N+1 回避
    from app.models import WorkflowGroup as WG_list
    from app.schemas import WorkflowGroupItem, WorkflowGroupSkillItem
    wf_ids = [w.id for w in workflows]
    all_groups = (
        db.query(WG_list)
        .filter(WG_list.workflow_id.in_(wf_ids))
        .order_by(WG_list.group_order.asc())
        .all()
    ) if wf_ids else []
    group_ids = [g.id for g in all_groups]
    all_wf_skills = (
        db.query(WorkflowSkill)
        .options(joinedload(WorkflowSkill.skill))
        .filter(WorkflowSkill.group_id.in_(group_ids))
        .order_by(WorkflowSkill.order_in_group.asc())
        .all()
    ) if group_ids else []
    # グループIDごとにスキルをまとめる
    skills_by_group: dict[int, list] = {}
    for ws in all_wf_skills:
        skills_by_group.setdefault(ws.group_id, []).append(ws)
    # ワークフローIDごとにグループをまとめる
    groups_by_wf: dict[int, list] = {}
    for g in all_groups:
        groups_by_wf.setdefault(g.workflow_id, []).append(g)

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

        # グループ構造を構築（プリフェッチ済みデータから）
        groups_data = []
        for g in groups_by_wf.get(wf.id, []):
            g_skills = skills_by_group.get(g.id, [])
            groups_data.append(WorkflowGroupItem(
                id=g.id,
                group_order=g.group_order,
                group_name=g.group_name,
                execution_type=g.execution_type or "serial",
                skills=[WorkflowGroupSkillItem(
                    id=ws.id,
                    workflow_skill_id=ws.id,
                    skill_id=ws.skill_id,
                    skill_order=ws.skill_order,
                    skill_name=ws.skill_name,
                    model_type=ws.skill.model_type if ws.skill else None,
                    agent_profile=ws.agent_profile,
                ) for ws in g_skills],
            ))

        wf_cfg_out = None
        if getattr(wf, "config_json", None):
            try:
                wf_cfg_out = json.loads(wf.config_json) if isinstance(wf.config_json, str) else wf.config_json
            except (json.JSONDecodeError, TypeError):
                wf_cfg_out = None

        items.append(
            WorkflowListItem(
                id=wf.id,
                name=wf.name,
                description=wf.description,
                is_active=wf.is_active,
                parent_model_type=wf.parent_model_type,
                config_json=wf_cfg_out,
                created_at=wf.created_at,
                updated_at=wf.updated_at,
                groups=groups_data,
            )
        )

    return {
        "items": items,
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.post("/workflows/with-parent-skill", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
async def create_workflow_with_parent_skill(
    request: WorkflowCreateWithParentSkill,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent),
):
    """親スキルと子スキルを含むワークフローを一括作成"""
    # 1. 親スキルコンテンツを暗号化してワークフローに埋め込み
    encrypted_parent_content = encryption_service.encrypt(request.parent_skill.content)

    # input_schemaをJSON文字列に変換
    workflow_input_schema_str = None
    if request.input_schema is not None:
        try:
            workflow_input_schema_str = json.dumps(
                request.input_schema, ensure_ascii=False
            )
        except Exception:
            workflow_input_schema_str = None

    workflow_config_json_str = None
    if getattr(request, "config_json", None):
        try:
            workflow_config_json_str = json.dumps(request.config_json, ensure_ascii=False)
        except Exception:
            workflow_config_json_str = None

    db_wf = Workflow(
        name=request.name,
        description=request.description,
        input_schema=workflow_input_schema_str,
        is_active=request.is_active,
        created_by=current_user.id,
        encrypted_parent_content=encrypted_parent_content,
        parent_model_type=request.parent_skill.model_type,
        parent_enable_deep_think=request.parent_skill.enable_deep_think,
        parent_skill_mode="required",
        supervisor_mode=getattr(request, 'supervisor_mode', 'disabled') or 'disabled',
        config_json=workflow_config_json_str,
    )
    db.add(db_wf)
    db.flush()  # IDを取得

    from app.models import WorkflowGroup

    def _validate_skill_exists(sid: int) -> None:
        skill = db.query(Skill).filter(
            Skill.id == sid,
            Skill.deleted_at.is_(None),
        ).first()
        if not skill:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"スキルID {sid} が見つかりません",
            )

    # 2. 子スキルを登録 — グループ優先、なければ旧 skills を1直列グループに包む
    _validate_parallel_group_profiles(getattr(request, "groups", None))
    if request.groups is not None and len(request.groups) > 0:
        step_counter = 1
        for grp_data in request.groups:
            condition_expr_str = None
            if getattr(grp_data, 'condition_expression', None):
                condition_expr_str = json.dumps(grp_data.condition_expression, ensure_ascii=False)
            # supervisor_prompt / judge_prompt の暗号化
            encrypted_supervisor_prompt = None
            raw_supervisor_prompt = getattr(grp_data, 'supervisor_prompt', None)
            if raw_supervisor_prompt:
                encrypted_supervisor_prompt = encryption_service.encrypt(raw_supervisor_prompt)
            encrypted_judge_prompt = None
            raw_judge_prompt = getattr(grp_data, 'judge_prompt', None)
            if raw_judge_prompt:
                encrypted_judge_prompt = encryption_service.encrypt(raw_judge_prompt)

            grp_config_json_str = None
            if getattr(grp_data, "config_json", None):
                try:
                    grp_config_json_str = json.dumps(grp_data.config_json, ensure_ascii=False)
                except (TypeError, ValueError):
                    grp_config_json_str = None

            grp = WorkflowGroup(
                workflow_id=db_wf.id,
                group_order=grp_data.group_order,
                group_name=grp_data.group_name,
                execution_type=grp_data.execution_type or "serial",
                condition_expression=condition_expr_str,
                skip_on_condition_fail=getattr(grp_data, 'skip_on_condition_fail', True),
                supervisor_prompt=encrypted_supervisor_prompt,
                supervisor_model=getattr(grp_data, 'supervisor_model', None),
                dynamic_mode=getattr(grp_data, 'dynamic_mode', 'static') or 'static',
                judge_prompt=encrypted_judge_prompt,
                judge_model=getattr(grp_data, 'judge_model', None),
                config_json=grp_config_json_str,
            )
            db.add(grp)
            db.flush()

            for skill_data in grp_data.skills:
                _validate_skill_exists(skill_data.skill_id)
                config_json_str = None
                if getattr(skill_data, "config_json", None):
                    config_json_str = json.dumps(
                        skill_data.config_json, ensure_ascii=False
                    )
                input_mapping_str = None
                if getattr(skill_data, "input_mapping", None):
                    input_mapping_str = json.dumps(skill_data.input_mapping, ensure_ascii=False)
                # quality_gate_prompt の暗号化
                encrypted_qg_prompt = None
                raw_qg_prompt = getattr(skill_data, 'quality_gate_prompt', None)
                if raw_qg_prompt:
                    encrypted_qg_prompt = encryption_service.encrypt(raw_qg_prompt)
                # handoff_rules の JSON 化
                handoff_rules_str = None
                raw_handoff = getattr(skill_data, 'handoff_rules', None)
                if raw_handoff:
                    handoff_rules_str = json.dumps(raw_handoff, ensure_ascii=False)
                ws = WorkflowSkill(
                    workflow_id=db_wf.id,
                    skill_id=skill_data.skill_id,
                    skill_order=step_counter,
                    skill_name=skill_data.skill_display_name or skill_data.skill_name,
                    config_json=config_json_str,
                    group_id=grp.id,
                    order_in_group=skill_data.order_in_group,
                    on_error=getattr(skill_data, 'on_error', 'stop') or 'stop',
                    max_retries=getattr(skill_data, 'max_retries', 0) or 0,
                    retry_delay_seconds=getattr(skill_data, 'retry_delay_seconds', 5) or 5,
                    depends_on=getattr(skill_data, 'depends_on', None),
                    input_mapping=input_mapping_str,
                    output_key=getattr(skill_data, 'output_key', None),
                    quality_gate_type=getattr(skill_data, 'quality_gate_type', 'disabled') or 'disabled',
                    quality_gate_prompt=encrypted_qg_prompt,
                    quality_gate_model=getattr(skill_data, 'quality_gate_model', None),
                    max_reflection_loops=getattr(skill_data, 'max_reflection_loops', 0) or 0,
                    handoff_rules=handoff_rules_str,
                    agent_profile=getattr(skill_data, "agent_profile", None),
                )
                db.add(ws)
                step_counter += 1
    elif request.skills:
        grp = WorkflowGroup(
            workflow_id=db_wf.id,
            group_order=1,
            group_name="グループ 1",
            execution_type="serial",
        )
        db.add(grp)
        db.flush()
        step_counter = 1
        for skill_item in request.skills:
            _validate_skill_exists(skill_item.skill_id)
            config_json_str = None
            if skill_item.config_json:
                config_json_str = json.dumps(
                    skill_item.config_json, ensure_ascii=False
                )
            workflow_skill = WorkflowSkill(
                workflow_id=db_wf.id,
                skill_id=skill_item.skill_id,
                skill_order=step_counter,
                skill_name=skill_item.skill_name,
                config_json=config_json_str,
                group_id=grp.id,
                order_in_group=step_counter,
                agent_profile=getattr(skill_item, "agent_profile", None),
            )
            db.add(workflow_skill)
            step_counter += 1
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="groups または skills に少なくとも1件のスキルを含めてください",
        )

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
    新しいワークフローを作成（親スキル埋め込み版）

    - Workflow レコードを作成
    - parent_skill_content を暗号化してワークフローに直接埋め込む
    """
    # 1. Workflow本体を作成
    workflow_input_schema_str = None
    if workflow.input_schema is not None:
        try:
            workflow_input_schema_str = json.dumps(
                workflow.input_schema, ensure_ascii=False
            )
        except Exception:
            workflow_input_schema_str = None

    # 親スキルコンテンツを暗号化
    encrypted_parent_content = None
    if workflow.parent_skill_content:
        encrypted_parent_content = encryption_service.encrypt(workflow.parent_skill_content)
    else:
        # デフォルトの親スキルコンテンツ
        default_content = (
            "あなたはワークフローの統合エージェントです。\n"
            "all_step_results に、各ステップ（子スキル）の結果が配列として渡されます。\n"
            "- previous_output / previous_step_result: 直前ステップの結果\n"
            "- all_step_results: これまでの全成功ステップの詳細（skill_order, skill_id, output など）\n\n"
            "これらを踏まえて、ユーザーへの最終回答を日本語でわかりやすく統合してください。"
        )
        encrypted_parent_content = encryption_service.encrypt(default_content)

    workflow_config_json_str = None
    if getattr(workflow, "config_json", None) is not None:
        try:
            workflow_config_json_str = json.dumps(workflow.config_json, ensure_ascii=False)
        except Exception:
            workflow_config_json_str = None

    db_wf = Workflow(
        name=workflow.name,
        description=workflow.description,
        input_schema=workflow_input_schema_str,
        is_active=workflow.is_active,
        created_by=current_user.id,
        encrypted_parent_content=encrypted_parent_content,
        parent_model_type=workflow.parent_model_type,
        parent_enable_deep_think=workflow.parent_enable_deep_think,
        parent_skill_mode="required",
        supervisor_mode=getattr(workflow, 'supervisor_mode', 'disabled') or 'disabled',
        config_json=workflow_config_json_str,
    )
    db.add(db_wf)
    db.commit()
    db.refresh(db_wf)

    # NOTE: This endpoint creates an EMPTY workflow (no groups/skills).
    # If the caller wants to seed groups in one shot, they should use
    # POST /workflows/with-parent-skill which has the full create path
    # (group encryption, skill validation, dependency wiring, etc).
    # We deliberately reject `groups` here rather than half-implementing
    # group creation — last time we tried that, condition_expression /
    # supervisor_prompt / judge_prompt / skip_on_condition_fail / skills
    # all silently fell through.
    if getattr(workflow, "groups", None):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "groups を含むワークフロー作成は POST /workflows/with-parent-skill "
                "を使用してください。このエンドポイントは空ワークフロー作成専用です。"
            ),
        )

    return _build_workflow_response(db_wf, db)


def _build_workflow_response(db_wf: Workflow, db: Session) -> WorkflowResponse:
    """内部用: Workflow + Groups + Skills を組み立てて返す"""
    from app.models import WorkflowGroup
    from app.schemas import WorkflowGroupItem, WorkflowGroupSkillItem, WorkflowSkillItem

    # グループベース構造を構築
    groups_list = []
    flat_skills = []

    db_groups = (
        db.query(WorkflowGroup)
        .filter(WorkflowGroup.workflow_id == db_wf.id)
        .order_by(WorkflowGroup.group_order.asc())
        .all()
    )

    for grp in db_groups:
        grp_skills = []
        for ws in sorted(grp.skills, key=lambda s: s.order_in_group or s.skill_order or 0):
            skill = ws.skill
            input_mapping_parsed = None
            if ws.input_mapping:
                try:
                    input_mapping_parsed = json.loads(ws.input_mapping) if isinstance(ws.input_mapping, str) else ws.input_mapping
                except (json.JSONDecodeError, TypeError):
                    pass
            # quality_gate_prompt の復号
            quality_gate_prompt_val = None
            if getattr(ws, 'quality_gate_prompt', None):
                try:
                    quality_gate_prompt_val = encryption_service.decrypt(ws.quality_gate_prompt)
                except Exception:
                    quality_gate_prompt_val = "(復号エラー)"
            # handoff_rules のパース
            handoff_rules_parsed = None
            if getattr(ws, 'handoff_rules', None):
                try:
                    handoff_rules_parsed = json.loads(ws.handoff_rules) if isinstance(ws.handoff_rules, str) else ws.handoff_rules
                except (json.JSONDecodeError, TypeError):
                    pass
            # Per-step execution_config (lives in WorkflowSkill.config_json
            # alongside any other free-form keys). Parse the whole JSON
            # blob and pass it through so the workflow builder UI can
            # round-trip it intact.
            ws_config_json_parsed = None
            if getattr(ws, 'config_json', None):
                try:
                    ws_config_json_parsed = (
                        json.loads(ws.config_json)
                        if isinstance(ws.config_json, str)
                        else ws.config_json
                    )
                except (json.JSONDecodeError, TypeError):
                    ws_config_json_parsed = None
            skill_item = WorkflowGroupSkillItem(
                id=ws.id,
                skill_id=ws.skill_id,
                skill_name=skill.name if skill else None,
                model_type=skill.model_type if skill else None,
                order_in_group=ws.order_in_group or ws.skill_order or 0,
                skill_display_name=ws.skill_name,
                on_error=ws.on_error or "stop",
                max_retries=ws.max_retries or 0,
                retry_delay_seconds=ws.retry_delay_seconds or 5,
                input_mapping=input_mapping_parsed,
                output_key=ws.output_key,
                quality_gate_type=getattr(ws, 'quality_gate_type', 'disabled') or 'disabled',
                quality_gate_prompt=quality_gate_prompt_val,
                quality_gate_model=getattr(ws, 'quality_gate_model', None),
                max_reflection_loops=getattr(ws, 'max_reflection_loops', 0) or 0,
                handoff_rules=handoff_rules_parsed,
                agent_profile=getattr(ws, "agent_profile", None),
                depends_on=getattr(ws, "depends_on", None),
                # enable_deep_think is owned by the parent Skill row,
                # not WorkflowSkill — there is no per-step override
                # column. We surface the parent's value here so the
                # builder UI can display it (read-only context).
                enable_deep_think=(skill.enable_deep_think if skill is not None else None),
                config_json=ws_config_json_parsed,
            )
            grp_skills.append(skill_item)
            # 後方互換: フラット skills
            flat_skills.append(WorkflowSkillItem(
                id=ws.id,
                skill_order=ws.skill_order,
                skill_name=ws.skill_name,
                skill_id=ws.skill_id,
                skill_display_name=skill.name if skill else None,
                agent_profile=getattr(ws, "agent_profile", None),
            ))

        condition_parsed = None
        if grp.condition_expression:
            try:
                condition_parsed = json.loads(grp.condition_expression) if isinstance(grp.condition_expression, str) else grp.condition_expression
            except (json.JSONDecodeError, TypeError):
                pass
        # supervisor_prompt / judge_prompt の復号
        supervisor_prompt_val = None
        if getattr(grp, 'supervisor_prompt', None):
            try:
                supervisor_prompt_val = encryption_service.decrypt(grp.supervisor_prompt)
            except Exception:
                supervisor_prompt_val = "(復号エラー)"
        judge_prompt_val = None
        if getattr(grp, 'judge_prompt', None):
            try:
                judge_prompt_val = encryption_service.decrypt(grp.judge_prompt)
            except Exception:
                judge_prompt_val = "(復号エラー)"

        grp_config_json_parsed = None
        if getattr(grp, "config_json", None):
            try:
                grp_config_json_parsed = (
                    json.loads(grp.config_json)
                    if isinstance(grp.config_json, str)
                    else grp.config_json
                )
            except (json.JSONDecodeError, TypeError):
                grp_config_json_parsed = None

        groups_list.append(WorkflowGroupItem(
            id=grp.id,
            group_order=grp.group_order,
            group_name=grp.group_name,
            execution_type=grp.execution_type,
            condition_expression=condition_parsed,
            skip_on_condition_fail=grp.skip_on_condition_fail if grp.skip_on_condition_fail is not None else True,
            supervisor_prompt=supervisor_prompt_val,
            supervisor_model=getattr(grp, 'supervisor_model', None),
            dynamic_mode=getattr(grp, 'dynamic_mode', 'static') or 'static',
            judge_prompt=judge_prompt_val,
            judge_model=getattr(grp, 'judge_model', None),
            config_json=grp_config_json_parsed,
            skills=grp_skills,
        ))

    # input_schema パース
    workflow_input_schema = None
    if getattr(db_wf, "input_schema", None):
        try:
            workflow_input_schema = (
                json.loads(db_wf.input_schema)
                if isinstance(db_wf.input_schema, str)
                else db_wf.input_schema
            )
        except Exception:
            pass

    # 親スキル復号（管理者用）
    parent_content = None
    if db_wf.encrypted_parent_content:
        try:
            parent_content = encryption_service.decrypt(db_wf.encrypted_parent_content)
        except Exception:
            parent_content = "(復号エラー)"

    workflow_config_json_parsed = None
    if getattr(db_wf, "config_json", None):
        try:
            workflow_config_json_parsed = (
                json.loads(db_wf.config_json)
                if isinstance(db_wf.config_json, str)
                else db_wf.config_json
            )
        except (json.JSONDecodeError, TypeError):
            workflow_config_json_parsed = None

    return WorkflowResponse(
        id=db_wf.id,
        name=db_wf.name,
        description=db_wf.description,
        input_schema=workflow_input_schema,
        is_active=db_wf.is_active,
        parent_skill_content=parent_content,
        parent_model_type=db_wf.parent_model_type,
        parent_enable_deep_think=db_wf.parent_enable_deep_think,
        supervisor_mode=getattr(db_wf, 'supervisor_mode', 'disabled') or 'disabled',
        config_json=workflow_config_json_parsed,
        created_by=db_wf.created_by,
        created_at=db_wf.created_at,
        updated_at=db_wf.updated_at,
        groups=groups_list,
        skills=flat_skills,
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

    # 親スキル更新
    if workflow_update.parent_skill_content is not None:
        wf.encrypted_parent_content = encryption_service.encrypt(workflow_update.parent_skill_content)
    if workflow_update.parent_model_type is not None:
        wf.parent_model_type = workflow_update.parent_model_type
    if workflow_update.parent_enable_deep_think is not None:
        wf.parent_enable_deep_think = workflow_update.parent_enable_deep_think
    if workflow_update.supervisor_mode is not None:
        wf.supervisor_mode = workflow_update.supervisor_mode

    # Workflow-level execution_config (top of inheritance chain).
    # An explicit None in the request payload is "leave unchanged"; an
    # empty dict clears the column so the workflow falls back to legacy
    # defaults.
    if workflow_update.config_json is not None:
        if workflow_update.config_json == {}:
            wf.config_json = None
        else:
            try:
                wf.config_json = json.dumps(
                    workflow_update.config_json, ensure_ascii=False
                )
            except Exception:
                wf.config_json = None

    # グループ構造更新（全置換）
    if workflow_update.groups is not None:
        _validate_parallel_group_profiles(workflow_update.groups)
        from app.models import WorkflowGroup
        # 既存グループ・スキル削除
        db.query(WorkflowSkill).filter(WorkflowSkill.workflow_id == workflow_id).delete()
        db.query(WorkflowGroup).filter(WorkflowGroup.workflow_id == workflow_id).delete()
        db.flush()

        # 新規グループ・スキル作成
        step_counter = 1
        for grp_data in workflow_update.groups:
            condition_expr_str = None
            if getattr(grp_data, 'condition_expression', None):
                condition_expr_str = json.dumps(grp_data.condition_expression, ensure_ascii=False)
            # supervisor_prompt / judge_prompt の暗号化
            encrypted_supervisor_prompt = None
            raw_supervisor_prompt = getattr(grp_data, 'supervisor_prompt', None)
            if raw_supervisor_prompt:
                encrypted_supervisor_prompt = encryption_service.encrypt(raw_supervisor_prompt)
            encrypted_judge_prompt = None
            raw_judge_prompt = getattr(grp_data, 'judge_prompt', None)
            if raw_judge_prompt:
                encrypted_judge_prompt = encryption_service.encrypt(raw_judge_prompt)

            # Group-level execution_config (sits between workflow and skill).
            grp_config_json_str = None
            raw_grp_cfg = getattr(grp_data, 'config_json', None)
            if raw_grp_cfg:
                try:
                    grp_config_json_str = json.dumps(raw_grp_cfg, ensure_ascii=False)
                except (TypeError, ValueError):
                    grp_config_json_str = None

            grp = WorkflowGroup(
                workflow_id=workflow_id,
                group_order=grp_data.group_order,
                group_name=grp_data.group_name,
                execution_type=grp_data.execution_type,
                condition_expression=condition_expr_str,
                skip_on_condition_fail=getattr(grp_data, 'skip_on_condition_fail', True),
                supervisor_prompt=encrypted_supervisor_prompt,
                supervisor_model=getattr(grp_data, 'supervisor_model', None),
                dynamic_mode=getattr(grp_data, 'dynamic_mode', 'static') or 'static',
                judge_prompt=encrypted_judge_prompt,
                judge_model=getattr(grp_data, 'judge_model', None),
                config_json=grp_config_json_str,
            )
            db.add(grp)
            db.flush()

            for skill_data in grp_data.skills:
                input_mapping_str = None
                if getattr(skill_data, 'input_mapping', None):
                    input_mapping_str = json.dumps(skill_data.input_mapping, ensure_ascii=False)
                # quality_gate_prompt の暗号化
                encrypted_qg_prompt = None
                raw_qg_prompt = getattr(skill_data, 'quality_gate_prompt', None)
                if raw_qg_prompt:
                    encrypted_qg_prompt = encryption_service.encrypt(raw_qg_prompt)
                # handoff_rules の JSON 化
                handoff_rules_str = None
                raw_handoff = getattr(skill_data, 'handoff_rules', None)
                if raw_handoff:
                    handoff_rules_str = json.dumps(raw_handoff, ensure_ascii=False)
                # Per-step config_json (holds execution_config). Serialize
                # the dict the builder UI sent. None / empty dict clears
                # the column so the step falls back to the parent skill's
                # execution_config.
                step_config_json_str = None
                raw_step_cfg = getattr(skill_data, 'config_json', None)
                if raw_step_cfg:
                    try:
                        step_config_json_str = json.dumps(raw_step_cfg, ensure_ascii=False)
                    except (TypeError, ValueError):
                        step_config_json_str = None
                ws = WorkflowSkill(
                    workflow_id=workflow_id,
                    skill_id=skill_data.skill_id,
                    skill_order=step_counter,
                    skill_name=skill_data.skill_display_name or skill_data.skill_name,
                    group_id=grp.id,
                    order_in_group=skill_data.order_in_group,
                    on_error=getattr(skill_data, 'on_error', 'stop') or 'stop',
                    max_retries=getattr(skill_data, 'max_retries', 0) or 0,
                    retry_delay_seconds=getattr(skill_data, 'retry_delay_seconds', 5) or 5,
                    depends_on=getattr(skill_data, 'depends_on', None),
                    input_mapping=input_mapping_str,
                    output_key=getattr(skill_data, 'output_key', None),
                    quality_gate_type=getattr(skill_data, 'quality_gate_type', 'disabled') or 'disabled',
                    quality_gate_prompt=encrypted_qg_prompt,
                    quality_gate_model=getattr(skill_data, 'quality_gate_model', None),
                    max_reflection_loops=getattr(skill_data, 'max_reflection_loops', 0) or 0,
                    handoff_rules=handoff_rules_str,
                    agent_profile=getattr(skill_data, "agent_profile", None),
                    config_json=step_config_json_str,
                )
                db.add(ws)
                step_counter += 1

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

    # すべてのskill_idが存在し、論理削除されていないことを確認
    skill_ids = {item.skill_id for item in body.skills}
    if skill_ids:
        existing_skills = (
            db.query(Skill)
            .filter(Skill.id.in_(skill_ids), Skill.deleted_at.is_(None))
            .all()
        )
        if len(existing_skills) != len(skill_ids):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="存在しない、または削除されたスキルが含まれています",
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
            skill_id=item.skill_id,
            skill_order=item.skill_order,
            skill_name=item.skill_name,
            config_json=config_json_str,
            agent_profile=getattr(item, "agent_profile", None),
        )
        db.add(ws)

    db.commit()

    db.refresh(wf)
    return _build_workflow_response(wf, db)


@router.get("/skills/{skill_id}", response_model=SkillResponse)
async def get_skill(
    skill_id: int,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent)
):
    """特定のスキルを取得"""
    skill = db.query(Skill).filter(Skill.id == skill_id, Skill.deleted_at.is_(None)).first()
    if not skill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="スキルが見つかりません"
        )

    # input_schemaをJSON文字列からdictに変換
    input_schema = None
    if skill.input_schema:
        try:
            input_schema = json.loads(skill.input_schema)
        except (json.JSONDecodeError, TypeError):
            input_schema = None

    # SkillResponseスキーマに合致するフィールドのみを返す（encrypted_contentは含めない）
    return SkillResponse(
        id=skill.id,
        name=skill.name,
        description=skill.description,
        model_type=skill.model_type,
        input_schema=input_schema,
        allows_file_output=skill.allows_file_output,
        enable_deep_think=skill.enable_deep_think,
        default_agent_profile=getattr(skill, "default_agent_profile", None),
        is_active=skill.is_active,
        created_by=skill.created_by,
        created_at=skill.created_at,
        updated_at=skill.updated_at,
    )


@router.get("/skills/{skill_id}/content")
async def get_skill_content(
    skill_id: int,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent)
):
    """スキルの内容を取得（復号化）- 管理者のみ"""
    skill = db.query(Skill).filter(Skill.id == skill_id, Skill.deleted_at.is_(None)).first()
    if not skill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="スキルが見つかりません"
        )

    # 復号化
    try:
        if skill.encrypted_content is None:
            return {"content": ""}
        decrypted_content = encryption_service.decrypt(skill.encrypted_content)
        return {"content": decrypted_content}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"スキルの復号化に失敗しました: {str(e)}"
        )


@router.patch("/skills/{skill_id}", response_model=SkillResponse)
async def update_skill(
    skill_id: int,
    skill_update: SkillUpdate,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent)
):
    """スキル情報を更新"""
    skill = db.query(Skill).filter(Skill.id == skill_id, Skill.deleted_at.is_(None)).first()
    if not skill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="スキルが見つかりません"
        )

    # 更新
    if skill_update.name:
        skill.name = skill_update.name
    if skill_update.description is not None:
        skill.description = skill_update.description
    if skill_update.content:
        skill.encrypted_content = encryption_service.encrypt(skill_update.content)
    if skill_update.model_type:
        skill.model_type = skill_update.model_type
    if skill_update.input_schema is not None:
        skill.input_schema = json.dumps(skill_update.input_schema)
    if skill_update.is_active is not None:
        skill.is_active = skill_update.is_active
    if skill_update.allows_file_output is not None:
        skill.allows_file_output = skill_update.allows_file_output
    if skill_update.enable_deep_think is not None:
        skill.enable_deep_think = skill_update.enable_deep_think
    if skill_update.default_agent_profile is not None:
        skill.default_agent_profile = skill_update.default_agent_profile
    if skill_update.config_json is not None:
        # Empty dict / None → clear column (revert to legacy default).
        skill.config_json = (
            json.dumps(skill_update.config_json)
            if skill_update.config_json
            else None
        )

    db.commit()
    db.refresh(skill)

    # input_schemaをJSON文字列からdictに変換
    input_schema = None
    if skill.input_schema:
        try:
            input_schema = json.loads(skill.input_schema)
        except (json.JSONDecodeError, TypeError):
            input_schema = None

    config_json_out = None
    if skill.config_json:
        try:
            config_json_out = json.loads(skill.config_json)
        except (json.JSONDecodeError, TypeError):
            config_json_out = None

    # SkillResponseスキーマに合致するフィールドのみを返す（encrypted_contentは含めない）
    return SkillResponse(
        id=skill.id,
        name=skill.name,
        description=skill.description,
        model_type=skill.model_type,
        input_schema=input_schema,
        allows_file_output=skill.allows_file_output,
        enable_deep_think=skill.enable_deep_think,
        config_json=config_json_out,
        is_active=skill.is_active,
        created_by=skill.created_by,
        created_at=skill.created_at,
        updated_at=skill.updated_at,
    )


@router.delete("/skills/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(
    skill_id: int,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent)
):
    """スキルを論理削除"""
    skill = db.query(Skill).filter(Skill.id == skill_id, Skill.deleted_at.is_(None)).first()
    if not skill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="スキルが見つかりません"
        )

    # 論理削除: deleted_atに現在時刻を設定
    from datetime import datetime, timezone, timedelta
    jst = timezone(timedelta(hours=9))
    skill.deleted_at = datetime.now(jst)
    db.commit()


# ==================== スキル割り当て ====================
@router.post("/assign-skill", response_model=AccountSkillResponse, status_code=status.HTTP_201_CREATED)
async def assign_skill_to_account(
    assignment: AccountSkillAssign,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent)
):
    """アカウントにスキルを割り当て"""
    # アカウントの存在確認
    account = db.query(Account).filter(Account.id == assignment.account_id).first()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="アカウントが見つかりません"
        )

    # スキルの存在確認（論理削除されていないもののみ）
    skill = db.query(Skill).filter(Skill.id == assignment.skill_id, Skill.deleted_at.is_(None)).first()
    if not skill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="スキルが見つかりません"
        )

    # 既に割り当てられているかチェック
    existing = db.query(AccountSkill).filter(
        AccountSkill.account_id == assignment.account_id,
        AccountSkill.skill_id == assignment.skill_id
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="このスキルは既に割り当てられています"
        )

    # 割り当て
    account_skill = AccountSkill(
        account_id=assignment.account_id,
        skill_id=assignment.skill_id
    )
    db.add(account_skill)
    db.commit()
    db.refresh(account_skill)

    return account_skill


@router.post("/assign-workflow")
async def assign_workflow_to_account(
    body: dict,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent),
):
    """ワークフローをアカウントに割り当て（関連スキルもまとめて割り当て）"""
    account_id = body.get("account_id")
    workflow_id = body.get("workflow_id")
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="アカウントが見つかりません")
    wf = db.query(Workflow).filter(Workflow.id == workflow_id, Workflow.deleted_at.is_(None)).first()
    if not wf:
        raise HTTPException(status_code=404, detail="ワークフローが見つかりません")

    # ワークフローに含まれる全スキルを取得
    wf_skills = db.query(WorkflowSkill).filter(WorkflowSkill.workflow_id == workflow_id).all()
    skill_ids = {ws.skill_id for ws in wf_skills if ws.skill_id}
    assigned_count = 0
    for sid in skill_ids:
        existing = db.query(AccountSkill).filter(
            AccountSkill.account_id == account_id,
            AccountSkill.skill_id == sid,
        ).first()
        if not existing:
            db.add(AccountSkill(account_id=account_id, skill_id=sid))
            assigned_count += 1
    db.commit()
    return {"assigned_skills": assigned_count, "workflow_id": workflow_id}


@router.delete("/assign-workflow/{workflow_id}/account/{account_id}")
async def unassign_workflow_from_account(
    workflow_id: int,
    account_id: int,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent),
):
    """ワークフローの関連スキルをアカウントからまとめて解除"""
    wf_skills = db.query(WorkflowSkill).filter(WorkflowSkill.workflow_id == workflow_id).all()
    skill_ids = {ws.skill_id for ws in wf_skills if ws.skill_id}
    removed = 0
    for sid in skill_ids:
        assignment = db.query(AccountSkill).filter(
            AccountSkill.account_id == account_id,
            AccountSkill.skill_id == sid,
        ).first()
        if assignment:
            db.delete(assignment)
            removed += 1
    db.commit()
    return {"removed_skills": removed, "workflow_id": workflow_id}


@router.delete("/assign-skill/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unassign_skill_from_account(
    assignment_id: int,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent)
):
    """アカウントからスキルの割り当てを解除"""
    assignment = db.query(AccountSkill).filter(AccountSkill.id == assignment_id).first()
    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="割り当てが見つかりません"
        )

    db.delete(assignment)
    db.commit()


@router.get("/accounts/{account_id}/skills")
async def get_account_skills(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_active_parent)
):
    """特定のアカウントに割り当てられたスキル一覧を取得（assignment_idを含む）"""
    assignments = db.query(AccountSkill).filter(
        AccountSkill.account_id == account_id
    ).all()

    # input_schemaをJSON文字列からdictに変換
    result = []
    for assignment in assignments:
        skill = assignment.skill
        assignment_id = assignment.id  # assignment_idを先に取得

        # 必要なフィールドのみを明示的に取得
        skill_dict = {
            'id': skill.id,
            'name': skill.name,
            'description': skill.description,
            'model_type': skill.model_type,
            'is_active': skill.is_active,
            'allows_file_output': skill.allows_file_output,
            'created_by': skill.created_by,
            'created_at': skill.created_at.isoformat() if skill.created_at else None,
            'updated_at': skill.updated_at.isoformat() if skill.updated_at else None,
            'assignment_id': assignment_id  # assignment_idを追加
        }
        # input_schemaをJSON文字列からdictに変換
        if skill.input_schema:
            try:
                skill_dict['input_schema'] = json.loads(skill.input_schema)
            except (json.JSONDecodeError, TypeError):
                skill_dict['input_schema'] = None
        else:
            skill_dict['input_schema'] = None

        result.append(skill_dict)

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
    limit = min(limit, 100)
    # 総件数を取得
    total = db.query(Execution).count()

    executions = db.query(Execution).options(
        joinedload(Execution.workflow_execution).joinedload(WorkflowExecution.workflow)
    ).order_by(
        Execution.executed_at.desc()
    ).offset(skip).limit(limit).all()

    items = []
    for execution in executions:
        skill_name = getattr(execution, 'skill_name_snapshot', None) or (execution.skill.name if execution.skill else None)
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

        # ワークフロー情報を取得（スナップショット優先）
        workflow_name = None
        wf_id = None
        if execution.workflow_execution_id:
            wf_exec = execution.workflow_execution
            if wf_exec:
                workflow_name = getattr(wf_exec, 'workflow_name_snapshot', None)
                if not workflow_name and wf_exec.workflow:
                    workflow_name = wf_exec.workflow.name
                wf_id = wf_exec.workflow_id

        # Provenance / runtime metadata lives on CoordinatorArtifact.extra_metadata
        # (NOT executions.extra_metadata — that column doesn't exist).
        # We pick the newest artifact tied to this execution_id and pass
        # its parsed extra_metadata to the frontend so runtime-badge.js
        # can render a chip.
        extra_meta = None
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
                    extra_meta = json.loads(art.extra_metadata) if isinstance(art.extra_metadata, str) else art.extra_metadata
                except (json.JSONDecodeError, TypeError):
                    extra_meta = None
        except Exception:  # noqa: BLE001
            extra_meta = None

        # ExecutionResponseスキーマに合致するフィールドのみを返す（encrypted_contentやリレーションオブジェクトは含めない）
        execution_dict = {
            "id": execution.id,
            "account_id": execution.account_id,
            "skill_id": execution.skill_id,
            "skill_name": skill_name,
            "input_data": execution.input_data,
            "output_data": execution.output_data,
            "model_used": execution.model_used,
            "tokens_used": execution.tokens_used,
            "execution_time": execution.execution_time,
            "status": execution.status,
            "error_message": execution.error_message,
            "executed_at": execution.executed_at,
            "output_format": output_format,
            "enable_deep_think": bool(enable_deep_think) if enable_deep_think is not None else None,
            "workflow_execution_id": execution.workflow_execution_id,
            "workflow_execution_status": execution.workflow_execution.status if execution.workflow_execution else None,
            "workflow_skill_id": execution.workflow_skill_id,
            "skill_order": execution.skill_order,
            "workflow_name": workflow_name,
            "workflow_id": wf_id,
            "agent_profile": getattr(execution, "agent_profile", None),
            "execution_role": getattr(execution, "execution_role", None),
            "extra_metadata": extra_meta,
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
    """Celery Worker監視（廃止済み — ローカルワーカーに移行）"""
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
    if not REDIS_AVAILABLE:
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
