"""
ローカルワーカー用 API エンドポイント

- GET  /api/worker/executions/{id}/bundle  — 署名付き run bundle を取得
- POST /api/worker/executions/{id}/complete — 実行結果を送信
- POST /api/worker/keys — Worker API Key の発行（管理者用）

認証: job_token (Authorization: Bearer) または Worker API Key (X-Worker-Key)
"""
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Account,
    AccountType,
    APIConfig,
    Execution,
    Skill,
    WorkerAPIKey,
)
from app.encryption import encryption_service
from app.config import settings
from app.auth import get_current_user
from app.services.worker_auth import (
    verify_job_token,
    sign_bundle,
    hash_worker_api_key,
    generate_worker_api_key,
)
from app.services.completion_service import finalize_execution, trigger_workflow_continuation
from app.utils.skill_utils import replace_placeholders

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/worker", tags=["ワーカー"])


# ---------------------------------------------------------------------------
# 認証ヘルパー
# ---------------------------------------------------------------------------

def _authenticate_worker(
    db: Session,
    authorization: Optional[str] = None,
    x_worker_key: Optional[str] = None,
) -> dict:
    """
    job_token / Worker API Key / ユーザー JWT でワーカーを認証する。
    Returns:
        {"account_id": int, "execution_id": int | None, "auth_type": str}
    """
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]

        # 1. job_token
        payload = verify_job_token(token)
        if payload:
            return {
                "account_id": payload["account_id"],
                "execution_id": payload.get("execution_id"),
                "auth_type": "job_token",
            }

        # 2. ユーザー JWT (claim API 等で使用)
        try:
            from jose import JWTError, jwt as jose_jwt
            user_payload = jose_jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            username = user_payload.get("sub")
            if username:
                account = db.query(Account).filter(Account.username == username, Account.is_active == True).first()
                if account:
                    return {
                        "account_id": account.id,
                        "execution_id": None,
                        "auth_type": "user_jwt",
                    }
        except (JWTError, Exception):
            pass

    # 3. Worker API Key
    if x_worker_key:
        key_hash = hash_worker_api_key(x_worker_key)
        wk = (
            db.query(WorkerAPIKey)
            .filter(WorkerAPIKey.key_hash == key_hash, WorkerAPIKey.is_active == True)
            .first()
        )
        if wk:
            wk.last_used_at = datetime.now(timezone(timedelta(hours=9)))
            db.commit()
            return {
                "account_id": wk.account_id,
                "execution_id": None,
                "auth_type": "worker_key",
            }

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="有効な job_token / Worker API Key / ユーザー JWT が必要です",
    )


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class WorkerCompleteRequest(BaseModel):
    output: str
    tokens_used: int = 0
    model_used: str = ""
    execution_time_ms: int = 0


class WorkerCompleteResponse(BaseModel):
    status: str
    execution_id: int


class WorkerKeyCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class WorkerKeyCreateResponse(BaseModel):
    id: int
    name: str
    raw_key: str  # 1 回のみ表示


class BundleResponse(BaseModel):
    execution_id: int
    skill_id: int
    final_prompt: str
    model: str
    input_data: dict
    output_format: str
    enable_deep_think: bool
    signature: str
    api_keys: Optional[dict] = None  # {"openai": "sk-...", "gemini": "AI..."} ローカル実行用


# ---------------------------------------------------------------------------
# Bundle GET
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Claim: pending_local ジョブを取得（常駐ワーカー用）
# ---------------------------------------------------------------------------

@router.get("/claim")
async def claim_pending_jobs(
    limit: int = 10,
    authorization: Optional[str] = Header(None),
    x_worker_key: Optional[str] = Header(None, alias="X-Worker-Key"),
    db: Session = Depends(get_db),
):
    """
    自分のアカウントの pending_local Execution を取得し、job_token を発行する。
    常駐ワーカーがポーリングで呼び出す。
    """
    limit = min(limit, 50)
    auth = _authenticate_worker(db, authorization, x_worker_key)
    account_id = auth["account_id"]

    # pending_local の Execution を取得
    pending = (
        db.query(Execution)
        .filter(
            Execution.account_id == account_id,
            Execution.status == "pending_local",
            Execution.dispatch_mode != "server",
        )
        .order_by(Execution.id.asc())
        .limit(limit)
        .all()
    )

    if not pending:
        return {"jobs": []}

    from app.services.worker_auth import create_job_token

    jobs = []
    for execution in pending:
        job_token = create_job_token(execution.id, account_id)
        jobs.append({
            "execution_id": execution.id,
            "skill_id": execution.skill_id,
            "model": execution.model_used or "",
            "job_token": job_token,
            "workflow_execution_id": execution.workflow_execution_id,
            "skill_order": execution.skill_order,
        })

    return {"jobs": jobs}


# ---------------------------------------------------------------------------
# Bundle GET
# ---------------------------------------------------------------------------

@router.get("/executions/{execution_id}/bundle", response_model=BundleResponse)
async def get_execution_bundle(
    execution_id: int,
    authorization: Optional[str] = Header(None),
    x_worker_key: Optional[str] = Header(None, alias="X-Worker-Key"),
    db: Session = Depends(get_db),
):
    """
    署名付き run bundle を取得する。
    サーバー側でスキルを復号・プレースホルダ展開し、署名を付与して返す。
    """
    auth = _authenticate_worker(db, authorization, x_worker_key)

    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="実行が見つかりません")

    # 認証チェック: job_token なら execution_id 一致、worker_key なら account_id 一致
    if auth["auth_type"] == "job_token" and auth["execution_id"] != execution_id:
        raise HTTPException(status_code=403, detail="この実行へのアクセス権がありません")
    if auth["auth_type"] == "worker_key" and auth["account_id"] != execution.account_id:
        raise HTTPException(status_code=403, detail="この実行へのアクセス権がありません")

    # dispatch_mode チェック
    if execution.dispatch_mode == "server":
        raise HTTPException(status_code=400, detail="この実行はサーバーモードです")

    # ステータスチェック
    if execution.status not in ("pending", "pending_local"):
        raise HTTPException(
            status_code=409,
            detail=f"この実行は取得できません（status={execution.status}）",
        )

    # リース期限チェック（naive/aware 混在対応）
    now = datetime.now(timezone.utc)
    if execution.lease_expires_at:
        lease_exp = execution.lease_expires_at
        if lease_exp.tzinfo is None:
            lease_exp = lease_exp.replace(tzinfo=timezone.utc)
    else:
        lease_exp = None
    if lease_exp and lease_exp < now:
        execution.status = "error"
        execution.error_message = "リース期限切れ"
        db.commit()
        raise HTTPException(status_code=410, detail="リース期限が切れています")

    # スキル復号・展開
    model_type = execution.model_used or ""
    exec_role = getattr(execution, 'execution_role', None)

    if exec_role == "quality_gate":
        # 品質ゲート: WorkflowSkill.quality_gate_prompt から復号
        from app.models import WorkflowSkill as WS
        ws = db.query(WS).filter(WS.id == execution.workflow_skill_id).first() if execution.workflow_skill_id else None
        if not ws or not ws.quality_gate_prompt:
            raise HTTPException(status_code=404, detail="品質ゲートプロンプトが見つかりません")
        try:
            decrypted = encryption_service.decrypt(ws.quality_gate_prompt)
        except Exception:
            decrypted = ws.quality_gate_prompt  # 暗号化されていない場合
        model_type = ws.quality_gate_model or model_type
    elif exec_role == "supervisor":
        # スーパーバイザー: WorkflowGroup.supervisor_prompt から復号
        from app.models import WorkflowGroup as WG
        group = db.query(WG).filter(WG.id == execution.execution_group_id).first() if getattr(execution, 'execution_group_id', None) else None
        if not group or not group.supervisor_prompt:
            raise HTTPException(status_code=404, detail="スーパーバイザープロンプトが見つかりません")
        try:
            decrypted = encryption_service.decrypt(group.supervisor_prompt)
        except Exception:
            decrypted = group.supervisor_prompt
        model_type = group.supervisor_model or model_type
    elif exec_role == "debate_judge":
        # ジャッジ: WorkflowGroup.judge_prompt から復号
        from app.models import WorkflowGroup as WG
        group = db.query(WG).filter(WG.id == execution.execution_group_id).first() if getattr(execution, 'execution_group_id', None) else None
        if not group or not group.judge_prompt:
            raise HTTPException(status_code=404, detail="ジャッジプロンプトが見つかりません")
        try:
            decrypted = encryption_service.decrypt(group.judge_prompt)
        except Exception:
            decrypted = group.judge_prompt
        model_type = group.judge_model or model_type
    elif execution.skill_id:
        # 通常スキル: skills テーブルから復号
        skill = db.query(Skill).filter(Skill.id == execution.skill_id).first()
        if not skill:
            raise HTTPException(status_code=404, detail="スキルが見つかりません")
        decrypted = encryption_service.decrypt(skill.encrypted_content)
        model_type = skill.model_type or model_type
    elif execution.workflow_execution_id:
        # 親スキル: ワークフローから復号
        from app.models import Workflow, WorkflowExecution as WFExec
        wf_exec = db.query(WFExec).filter(WFExec.id == execution.workflow_execution_id).first()
        if not wf_exec:
            raise HTTPException(status_code=404, detail="ワークフロー実行が見つかりません")
        workflow = db.query(Workflow).filter(Workflow.id == wf_exec.workflow_id).first()
        if not workflow or not workflow.encrypted_parent_content:
            raise HTTPException(status_code=404, detail="親スキルが設定されていません")
        decrypted = encryption_service.decrypt(workflow.encrypted_parent_content)
        model_type = workflow.parent_model_type or model_type
    else:
        raise HTTPException(status_code=404, detail="スキルが見つかりません")

    input_data = {}
    if execution.input_data:
        try:
            input_data = json.loads(execution.input_data)
        except (json.JSONDecodeError, TypeError):
            input_data = {}

    # ガードレール付加
    if settings.ENABLE_PROMPT_GUARDRAILS:
        final_prompt = settings.GUARDRAIL_PREFIX + "\n\n" + replace_placeholders(decrypted, input_data)
    else:
        final_prompt = replace_placeholders(decrypted, input_data)

    # ユーザーの API キーを取得（暗号化保存されているため復号する）
    api_keys = {}
    api_config = db.query(APIConfig).filter(
        APIConfig.account_id == execution.account_id,
        APIConfig.is_enabled == True,
    ).first()
    if api_config:
        if api_config.openai_api_key:
            try:
                api_keys["openai"] = encryption_service.decrypt_api_key(api_config.openai_api_key)
            except Exception:
                logger.warning(f"Failed to decrypt OpenAI API key for account {execution.account_id}")
        if api_config.gemini_api_key:
            try:
                api_keys["gemini"] = encryption_service.decrypt_api_key(api_config.gemini_api_key)
            except Exception:
                logger.warning(f"Failed to decrypt Gemini API key for account {execution.account_id}")
        if api_config.anthropic_api_key:
            try:
                api_keys["anthropic"] = encryption_service.decrypt_api_key(api_config.anthropic_api_key)
            except Exception:
                logger.warning(f"Failed to decrypt Anthropic API key for account {execution.account_id}")

    # サーバーのデフォルトキーもフォールバックとして含める
    if "openai" not in api_keys and settings.OPENAI_API_KEY:
        api_keys["openai"] = settings.OPENAI_API_KEY
    if "gemini" not in api_keys and settings.GEMINI_API_KEY:
        api_keys["gemini"] = settings.GEMINI_API_KEY
    if "anthropic" not in api_keys and settings.ANTHROPIC_API_KEY:
        api_keys["anthropic"] = settings.ANTHROPIC_API_KEY

    # ステータスを processing に
    execution.status = "processing"
    db.commit()

    # 署名生成（api_keys は署名対象に含めない）
    bundle_data = {
        "execution_id": execution.id,
        "skill_id": execution.skill_id or 0,
        "final_prompt": final_prompt,
        "model": model_type,
        "input_data": input_data,
        "output_format": execution.output_format or "txt",
        "enable_deep_think": bool(execution.enable_deep_think),
    }
    signature = sign_bundle(bundle_data)
    bundle_data["api_keys"] = api_keys if api_keys else None

    logger.info(f"Bundle issued for execution {execution_id} (dispatch_mode={execution.dispatch_mode}, has_keys={'openai' in api_keys or 'gemini' in api_keys})")

    return BundleResponse(**bundle_data, signature=signature)


# ---------------------------------------------------------------------------
# Complete POST
# ---------------------------------------------------------------------------

@router.post("/executions/{execution_id}/complete", response_model=WorkerCompleteResponse)
async def complete_execution(
    execution_id: int,
    body: WorkerCompleteRequest,
    authorization: Optional[str] = Header(None),
    x_worker_key: Optional[str] = Header(None, alias="X-Worker-Key"),
    db: Session = Depends(get_db),
):
    """
    ローカルワーカーから実行結果を受け取り、DB に保存する。
    サニタイズ・課金・ワークフロー継続を実行する。
    """
    auth = _authenticate_worker(db, authorization, x_worker_key)

    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="実行が見つかりません")

    # 認証チェック
    if auth["auth_type"] == "job_token" and auth["execution_id"] != execution_id:
        raise HTTPException(status_code=403, detail="この実行へのアクセス権がありません")
    if auth["auth_type"] == "worker_key" and auth["account_id"] != execution.account_id:
        raise HTTPException(status_code=403, detail="この実行へのアクセス権がありません")

    if execution.dispatch_mode == "server":
        raise HTTPException(status_code=400, detail="この実行はサーバーモードです")

    if execution.status not in ("processing", "pending", "pending_local"):
        raise HTTPException(
            status_code=409,
            detail=f"この実行は完了できません（status={execution.status}）",
        )

    # テンプレート取得（サニタイズ用）
    template_text = None
    if execution.skill_id:
        skill = db.query(Skill).filter(Skill.id == execution.skill_id).first()
        if skill:
            try:
                template_text = encryption_service.decrypt(skill.encrypted_content)
            except Exception:
                pass

    # 共通完了処理
    finalize_execution(
        db=db,
        execution=execution,
        output=body.output,
        model_used=body.model_used or execution.model_used or "",
        tokens_used=body.tokens_used,
        execution_time_ms=body.execution_time_ms,
        status_result="success",
        template_text=template_text,
    )

    # Redis 完了イベント（UI SSE 用）
    try:
        from app.services.redis_service import publish_complete
        publish_complete(execution_id, {
            "model_used": body.model_used or execution.model_used,
            "tokens_used": body.tokens_used,
            "execution_time": body.execution_time_ms,
            "cost": float(execution.cost or 0.0),
        })
    except Exception as e:
        logger.warning(f"Failed to publish complete event: {e}")

    # ワークフロー継続
    trigger_workflow_continuation(execution, db)

    logger.info(f"Execution {execution_id} completed by local worker")
    return WorkerCompleteResponse(status="success", execution_id=execution_id)


# ---------------------------------------------------------------------------
# Error POST (ワーカーからのエラー報告)
# ---------------------------------------------------------------------------
# Chunk POST (ワーカーからのストリーミングチャンク)
# ---------------------------------------------------------------------------

class WorkerChunkRequest(BaseModel):
    chunk: str


@router.post("/executions/{execution_id}/chunk")
async def post_chunk(
    execution_id: int,
    body: WorkerChunkRequest,
    authorization: Optional[str] = Header(None),
    x_worker_key: Optional[str] = Header(None, alias="X-Worker-Key"),
    db: Session = Depends(get_db),
):
    """ローカルワーカーから LLM のチャンクを Redis Stream に送信"""
    auth = _authenticate_worker(db, authorization, x_worker_key)

    # job_token の場合は execution_id の一致を検証
    if auth["auth_type"] == "job_token" and auth.get("execution_id") != execution_id:
        raise HTTPException(status_code=403, detail="この実行へのアクセス権がありません")

    try:
        from app.services.redis_service import publish_chunk
        publish_chunk(execution_id, body.chunk)
    except Exception as e:
        logger.warning(f"Chunk publish failed for {execution_id}: {e}")

    return {"ok": True}


# ---------------------------------------------------------------------------
# Error POST (ワーカーからのエラー報告)
# ---------------------------------------------------------------------------

class WorkerErrorRequest(BaseModel):
    error_message: str
    execution_time_ms: int = 0


@router.post("/executions/{execution_id}/error")
async def report_execution_error(
    execution_id: int,
    body: WorkerErrorRequest,
    authorization: Optional[str] = Header(None),
    x_worker_key: Optional[str] = Header(None, alias="X-Worker-Key"),
    db: Session = Depends(get_db),
):
    """ローカルワーカーからのエラー報告"""
    auth = _authenticate_worker(db, authorization, x_worker_key)

    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="実行が見つかりません")

    if auth["auth_type"] == "job_token" and auth["execution_id"] != execution_id:
        raise HTTPException(status_code=403, detail="アクセス権がありません")
    if auth["auth_type"] == "worker_key" and auth["account_id"] != execution.account_id:
        raise HTTPException(status_code=403, detail="アクセス権がありません")

    finalize_execution(
        db=db,
        execution=execution,
        output="",
        model_used=execution.model_used or "",
        tokens_used=0,
        execution_time_ms=body.execution_time_ms,
        status_result="error",
        error_message=body.error_message,
    )

    try:
        from app.services.redis_service import publish_error
        publish_error(execution_id, body.error_message)
    except Exception as e:
        logger.warning(f"Failed to publish error event: {e}")

    # ワークフロー継続（エラーリカバリ: retry/skip/stop をトリガー）
    trigger_workflow_continuation(execution, db)

    return {"status": "error", "execution_id": execution_id}


# ---------------------------------------------------------------------------
# Worker API Key 管理（管理者用）
# ---------------------------------------------------------------------------

@router.post("/keys", response_model=WorkerKeyCreateResponse)
async def create_worker_key(
    body: WorkerKeyCreateRequest,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user),
):
    """
    Worker API Key を発行する。
    raw_key は **このレスポンスでのみ** 表示される。
    """
    raw_key, key_hash = generate_worker_api_key()

    wk = WorkerAPIKey(
        account_id=current_user.id,
        key_hash=key_hash,
        name=body.name,
    )
    db.add(wk)
    db.commit()
    db.refresh(wk)

    logger.info(f"Worker API Key created: id={wk.id}, account={current_user.id}, name={body.name}")
    return WorkerKeyCreateResponse(id=wk.id, name=wk.name, raw_key=raw_key)


@router.get("/keys")
async def list_worker_keys(
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user),
):
    """自分のワーカーキー一覧"""
    keys = (
        db.query(WorkerAPIKey)
        .filter(WorkerAPIKey.account_id == current_user.id)
        .all()
    )
    return [
        {
            "id": k.id,
            "name": k.name,
            "is_active": k.is_active,
            "created_at": k.created_at.isoformat() if k.created_at else None,
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
        }
        for k in keys
    ]


# ---------------------------------------------------------------------------
# Execution Output GET (ワーカーが complete 後に出力を取得)
# ---------------------------------------------------------------------------

@router.get("/executions/{execution_id}/output")
async def get_execution_output(
    execution_id: int,
    authorization: Optional[str] = Header(None),
    x_worker_key: Optional[str] = Header(None, alias="X-Worker-Key"),
    db: Session = Depends(get_db),
):
    """完了した Execution の output_data を取得する"""
    auth = _authenticate_worker(db, authorization, x_worker_key)

    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="実行が見つかりません")

    if auth["auth_type"] == "job_token" and auth["execution_id"] != execution_id:
        raise HTTPException(status_code=403, detail="アクセス権がありません")
    if auth["auth_type"] == "worker_key" and auth["account_id"] != execution.account_id:
        raise HTTPException(status_code=403, detail="アクセス権がありません")

    return {
        "execution_id": execution_id,
        "status": execution.status,
        "output": execution.output_data or "",
        "model_used": execution.model_used or "",
        "tokens_used": execution.tokens_used or 0,
    }


@router.delete("/keys/{key_id}")
async def revoke_worker_key(
    key_id: int,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user),
):
    """ワーカーキーを無効化"""
    wk = (
        db.query(WorkerAPIKey)
        .filter(WorkerAPIKey.id == key_id, WorkerAPIKey.account_id == current_user.id)
        .first()
    )
    if not wk:
        raise HTTPException(status_code=404, detail="キーが見つかりません")
    wk.is_active = False
    db.commit()
    return {"status": "revoked", "key_id": key_id}
