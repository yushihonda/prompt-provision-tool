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
    Workflow,
    WorkflowExecution,
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
from app.services.agent_profiles import build_blackboard_summary, compose_agent_profile_prompt, normalize_agent_profile

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
    provider_meta: Optional[dict] = None
    external_cli_meta: Optional[dict] = None


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
    agent_profile: Optional[str] = None
    provider_payload: Optional[dict] = None  # coordinator が選択した http provider 設定
    fallback_provider_payload: Optional[dict] = None  # runtime fallback 用 remote 設定
    # Bundle execution kind discriminator + external_cli payload (Phase 4 routing).
    # Either provider_payload (http) or external_cli_payload (cli) is populated, never both.
    execution_kind: str = "http_provider"
    external_cli_payload: Optional[dict] = None


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
    try:
        return await _get_execution_bundle_inner(execution_id, authorization, x_worker_key, db)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Bundle endpoint unhandled error for execution {execution_id}: {e}")
        raise HTTPException(status_code=500, detail=f"バンドル生成中に内部エラーが発生しました: {type(e).__name__}: {e}")


async def _get_execution_bundle_inner(
    execution_id: int,
    authorization: Optional[str],
    x_worker_key: Optional[str],
    db: Session,
):
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
        # ジャッジ: WorkflowGroup.judge_prompt から復号 or 自動生成
        from app.models import WorkflowGroup as WG
        group = db.query(WG).filter(WG.id == execution.execution_group_id).first() if getattr(execution, 'execution_group_id', None) else None
        if not group:
            raise HTTPException(status_code=404, detail="ジャッジのグループが見つかりません")
        if group.judge_prompt:
            try:
                decrypted = encryption_service.decrypt(group.judge_prompt)
            except Exception:
                decrypted = group.judge_prompt
            model_type = group.judge_model or model_type
        else:
            # 自動ジャッジ: input_data内のjudge_instructionsをプロンプトとして使用
            judge_input = {}
            if execution.input_data:
                try:
                    judge_input = json.loads(execution.input_data)
                except (json.JSONDecodeError, TypeError):
                    pass
            wf_exec_j = db.query(WorkflowExecution).filter(WorkflowExecution.id == execution.workflow_execution_id).first()
            wf_j = db.query(Workflow).filter(Workflow.id == wf_exec_j.workflow_id).first() if wf_exec_j else None
            decrypted = judge_input.get("judge_instructions", "")
            if not decrypted:
                from app.services.auto_orchestration import _build_judge_prompt
                from app.models import WorkflowSkill as WS_j
                group_skill_names = [
                    ws_j.skill_name or f"Step {ws_j.skill_order}"
                    for ws_j in db.query(WS_j).filter(WS_j.group_id == group.id).order_by(WS_j.order_in_group.asc()).all()
                ]
                decrypted = _build_judge_prompt(
                    getattr(wf_j, 'name', '') if wf_j else '',
                    getattr(wf_j, 'description', '') if wf_j else '',
                    group.group_name or f"Group {group.group_order}",
                    group_skill_names
                )
            model_type = group.judge_model or (getattr(wf_j, 'parent_model_type', None) if wf_j else None) or model_type
    elif execution.skill_id:
        # 通常スキル: skills テーブルから復号
        skill = db.query(Skill).filter(Skill.id == execution.skill_id).first()
        if not skill:
            raise HTTPException(status_code=404, detail="スキルが見つかりません")
        decrypted = encryption_service.decrypt(skill.encrypted_content)
        model_type = skill.model_type or model_type
    elif execution.workflow_execution_id:
        # 親スキル: ワークフローから復号 or 自動生成
        wf_exec = db.query(WorkflowExecution).filter(WorkflowExecution.id == execution.workflow_execution_id).first()
        if not wf_exec:
            raise HTTPException(status_code=404, detail="ワークフロー実行が見つかりません")
        workflow = db.query(Workflow).filter(Workflow.id == wf_exec.workflow_id).first()
        if not workflow:
            raise HTTPException(status_code=404, detail="ワークフローが見つかりません")
        if workflow.encrypted_parent_content:
            decrypted = encryption_service.decrypt(workflow.encrypted_parent_content)
        else:
            from app.services.auto_orchestration import generate_leader_prompt
            decrypted = generate_leader_prompt(workflow.name or "", workflow.description or "")
        model_type = workflow.parent_model_type or model_type
    else:
        raise HTTPException(status_code=404, detail="スキルが見つかりません")

    input_data = {}
    if execution.input_data:
        try:
            input_data = json.loads(execution.input_data)
        except (json.JSONDecodeError, TypeError):
            input_data = {}

    profile_value = getattr(execution, "agent_profile", None)
    normalized_profile = normalize_agent_profile(profile_value) if profile_value else None
    workflow_name = ""
    workflow_goal = ""
    parent_prompt = ""
    if execution.workflow_execution_id:
        wf_exec = db.query(WorkflowExecution).filter(WorkflowExecution.id == execution.workflow_execution_id).first()
        if wf_exec:
            workflow = db.query(Workflow).filter(Workflow.id == wf_exec.workflow_id).first()
            if workflow:
                workflow_name = workflow.name or ""
                workflow_goal = workflow.description or ""
                if workflow.encrypted_parent_content and execution.skill_id is not None:
                    try:
                        parent_prompt = encryption_service.decrypt(workflow.encrypted_parent_content)
                    except Exception:
                        parent_prompt = ""

    resolved_skill_prompt = replace_placeholders(decrypted, input_data)
    if normalized_profile:
        final_prompt = compose_agent_profile_prompt(
            profile=normalized_profile,
            workflow_name=workflow_name,
            workflow_goal=workflow_goal,
            parent_skill_prompt=parent_prompt,
            current_skill_prompt=resolved_skill_prompt,
            handoff_context=input_data.get("_nexmagi_handoff_context") or {},
            resolved_input_data=input_data,
            readonly_constraints=input_data.get("_nexmagi_readonly_constraints"),
            verification_contract=input_data.get("_nexmagi_verification_contract"),
            blackboard_summary=build_blackboard_summary(input_data.get("blackboard") or {}),
            step_metadata=input_data.get("_nexmagi_step_metadata") or {},
        )
    else:
        final_prompt = resolved_skill_prompt

    # 永続メモリ注入（ワークフロー実行時のみ）
    if execution.workflow_execution_id and normalized_profile:
        try:
            from app.services.memory_service import get_or_init_memory, build_memory_prompt_section
            wf_id = None
            if execution.workflow_execution_id:
                wf_e = db.query(WorkflowExecution).filter(WorkflowExecution.id == execution.workflow_execution_id).first()
                if wf_e:
                    wf_id = wf_e.workflow_id
            if wf_id:
                memory_text = get_or_init_memory(db, wf_id, normalized_profile)
                memory_section = build_memory_prompt_section(memory_text)
                if memory_section:
                    final_prompt = memory_section + "\n\n" + final_prompt
        except Exception as e:
            logger.warning(f"Failed to inject memory for execution {execution_id}: {e}")

    # ガードレール付加
    if settings.ENABLE_PROMPT_GUARDRAILS:
        final_prompt = settings.GUARDRAIL_PREFIX + "\n\n" + final_prompt

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

    # ステータスを processing に
    execution.status = "processing"
    db.commit()

    # Coordinator が plan を持っていれば、該当 task の provider routing を解決して
    # provider_payload と fallback_provider_payload を bundle に載せる。
    # 失敗しても bundle 発行は止めない。
    provider_payload: Optional[dict] = None
    fallback_provider_payload: Optional[dict] = None
    execution_kind: str = "http_provider"
    external_cli_payload: Optional[dict] = None
    try:
        if execution.workflow_execution_id and execution.workflow_skill_id:
            from app.services.coordinator_service import (
                EXECUTION_KIND_EXTERNAL_CLI,
                get_plan_by_workflow_execution,
                resolve_execution_kind,
                resolve_execution_provider_bundle,
            )
            plan = get_plan_by_workflow_execution(db, execution.workflow_execution_id)
            if plan:
                try:
                    plan_tasks = json.loads(plan.tasks or "[]")
                except (json.JSONDecodeError, TypeError):
                    plan_tasks = []
                matched_task = next(
                    (
                        t for t in plan_tasks
                        if t.get("workflow_skill_id") == execution.workflow_skill_id
                    ),
                    None,
                )
                if matched_task:
                    # Attach the parsed StepExecutionConfig from the
                    # WorkflowSkill row so resolve_execution_kind can
                    # route per-step. Legacy rows yield the default
                    # config, which behaves identically to before.
                    try:
                        from app.services.workflow_step_schema import parse_execution_config
                        from app.models import WorkflowSkill as _WorkflowSkill
                        ws_row = (
                            db.query(_WorkflowSkill)
                            .filter(_WorkflowSkill.id == execution.workflow_skill_id)
                            .first()
                        )
                        if ws_row is not None:
                            matched_task["_step_execution_config"] = parse_execution_config(
                                ws_row.config_json
                            )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "step execution_config parse skipped for execution %s: %s",
                            execution_id, exc,
                        )

                    # Step 1: decide execution kind. resolve_execution_kind
                    # returns external_cli_payload OR delegates to the
                    # http path. We never run both routings on the same
                    # bundle to avoid contradictory payloads.
                    kind_result = resolve_execution_kind(
                        db, plan, matched_task,
                        retry_count=int(getattr(execution, "retry_count", 0) or 0),
                    )
                    if kind_result.get("execution_kind") == EXECUTION_KIND_EXTERNAL_CLI:
                        execution_kind = EXECUTION_KIND_EXTERNAL_CLI
                        external_cli_payload = kind_result.get("external_cli_payload")
                        # External CLI bundles MUST NOT carry a provider_payload —
                        # the desktop runtime owns these and the sidecar bypasses them.
                        provider_payload = None
                        fallback_provider_payload = None
                        logger.info(
                            "external_cli_selected execution_id=%s adapter=%s runtime=%s",
                            execution.id,
                            kind_result.get("adapter_name"),
                            kind_result.get("runtime"),
                        )
                    else:
                        # Step 2: HTTP / internal provider path. We need
                        # the richer fallback payload that
                        # resolve_execution_provider_bundle produces, so
                        # call it here instead of using kind_result's
                        # provider_payload.
                        routing = resolve_execution_provider_bundle(
                            db, plan, matched_task,
                            retry_count=int(getattr(execution, "retry_count", 0) or 0),
                        )
                        provider_payload = routing.get("provider_payload")
                        fallback_provider_payload = routing.get("fallback_provider_payload")
                        # Embed the routing reason inside the payload itself so the
                        # sidecar can echo it back in actual provider metadata.
                        if provider_payload is not None:
                            provider_payload = dict(provider_payload)
                            provider_payload["provider_mode_selected"] = routing.get(
                                "provider_mode_selected"
                            )
                            provider_payload["provider_selection_reason"] = routing.get(
                                "provider_selection_reason"
                            )
                        if fallback_provider_payload is not None:
                            fallback_provider_payload = dict(fallback_provider_payload)
                            fallback_provider_payload["provider_mode_selected"] = (
                                "remote_only"
                            )
                            fallback_provider_payload["provider_selection_reason"] = (
                                "runtime_fallback_remote"
                            )
                        logger.info(
                            "provider_selected execution_id=%s mode=%s adapter=%s "
                            "fallback=%s reason=%s",
                            execution.id,
                            routing.get("provider_mode_selected"),
                            routing.get("selected_adapter_name"),
                            routing.get("fallback_adapter_name"),
                            routing.get("provider_selection_reason"),
                        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("provider routing skipped for execution %s: %s", execution_id, exc)

    # 署名生成（api_keys は署名対象に含めない）
    bundle_data = {
        "execution_id": execution.id,
        "skill_id": execution.skill_id or 0,
        "final_prompt": final_prompt,
        "model": model_type,
        "input_data": input_data,
        "output_format": execution.output_format or "txt",
        "enable_deep_think": bool(execution.enable_deep_think),
        "agent_profile": normalized_profile,
        "provider_payload": provider_payload,
        "fallback_provider_payload": fallback_provider_payload,
        "execution_kind": execution_kind,
        "external_cli_payload": external_cli_payload,
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
        provider_meta=body.provider_meta,
        external_cli_meta=body.external_cli_meta,
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


# ───────────────────────────────────────────────
# Workspace lifecycle endpoints (Tauri filesystem integration)
# ───────────────────────────────────────────────

class WorkspacePathUpdateRequest(BaseModel):
    workspace_path: str


@router.post("/workspaces/{workspace_id}/path")
async def api_update_workspace_path(
    workspace_id: str,
    body: WorkspacePathUpdateRequest,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user),
):
    """Tauri side reports the concrete filesystem path it created for
    the workspace. Transitions the row from reserved -> active.

    The path is validated to be absolute and to contain no traversal
    sequences. The backend cannot fully verify that the path lives
    under the desktop user's actual workspaces root (that's machine-
    specific), but we reject obvious escapes.
    """
    from app.services.coordinator_service import update_workspace_path
    path_str = (body.workspace_path or "").strip()
    if not path_str.startswith("/"):
        raise HTTPException(
            status_code=400,
            detail="workspace_path must be absolute",
        )
    if ".." in path_str.split("/"):
        raise HTTPException(
            status_code=400,
            detail="workspace_path must not contain traversal segments",
        )
    ws = update_workspace_path(db, workspace_id, path_str)
    if ws is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    return {"workspace_id": ws.workspace_id, "status": ws.status, "workspace_path": ws.workspace_path}


@router.post("/workspaces/{workspace_id}/promote")
async def api_promote_workspace(
    workspace_id: str,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user),
):
    """Mark a workspace as promoted (files merged / kept)."""
    from app.services.coordinator_service import promote_workspace
    ws = promote_workspace(db, workspace_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    return {"workspace_id": ws.workspace_id, "status": ws.status}


@router.post("/workspaces/{workspace_id}/cleanup")
async def api_cleanup_workspace(
    workspace_id: str,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user),
):
    """Mark a workspace as cleaned. Actual filesystem removal is the
    Tauri side's responsibility — backend only records the status.
    """
    from app.services.coordinator_service import cleanup_workspace
    ws = cleanup_workspace(db, workspace_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    return {"workspace_id": ws.workspace_id, "status": ws.status}


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
