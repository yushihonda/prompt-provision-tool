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
# スキーマ
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
    # バンドル実行種別判別子 + external_cli ペイロード（ルーティング用）。
    # provider_payload（HTTP）か external_cli_payload（CLI）のどちらか一方のみが設定される。
    execution_kind: str = "http_provider"
    external_cli_payload: Optional[dict] = None


# ---------------------------------------------------------------------------
# バンドル取得
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
    #
    # external_cli は claim 対象から除外する。
    # external_cli 種別の step は Tauri desktop 側の external_cli_poller
    # (frontend/user/js/workflow-execute.js) が pending_local/processing を
    # 見て consume_external_cli_bundle 経由で実行するのが唯一の正しいパス。
    # docker/常駐 local_worker がこれを claim してしまうと、
    # コンテナ内には claude CLI も Tauri workspace も存在しないため
    # `external_cli payload missing cwd` で即失敗し、
    # さらに Tauri 側には step が流れなくなる（claim レース負け）。
    # 過去インシデント: workflow "[test] parent=CLI, child=API" の親ステップが
    # worker 復活後に連続エラーしていた件（2026-04-09）。
    #
    # アトミック claim: SELECT 後に行ごとの UPDATE で status を `processing`
    # に変更する（ただし現在 `pending_local` の場合のみ）。UPDATE の rowcount
    # で *この* ワーカーがレースに勝ったかどうかを判定する。負けた行は
    # レスポンスから黙って除外し、呼び出し側が所有していない exec の bundle
    # を取得しようとすることを防ぐ。
    #
    # この仕組みがないと、docker の local_worker デーモンと Tauri の
    # orchestration sidecar が毎 tick で pending_local 行をポーリングして
    # bundle/complete を競合する。負けた側の bundle 取得は 409 になり、
    # 負けた側が /executions/{id}/error を POST して勝者の成功行を
    # 上書きしてしまう。実際に「exec 188 は成功したが DB 行が error
    # → リトライ機構が 191 を生成 → 幽霊重複実行」として顕在化した。
    candidates = (
        db.query(Execution)
        .filter(
            Execution.account_id == account_id,
            Execution.status == "pending_local",
            Execution.dispatch_mode != "server",
            Execution.execution_kind != "external_cli",
        )
        .order_by(Execution.id.asc())
        .limit(limit)
        .all()
    )

    if not candidates:
        return {"jobs": []}

    from app.services.worker_auth import create_job_token

    jobs = []
    for execution in candidates:
        # アトミック変更: status がまだ pending_local の場合のみ成功する。
        # rowcount==1 = 勝利。rowcount==0 = 別のワーカーに先を越された。
        result = (
            db.query(Execution)
            .filter(
                Execution.id == execution.id,
                Execution.status == "pending_local",
            )
            .update({"status": "processing"}, synchronize_session=False)
        )
        if result == 0:
            # レース負け — この行はスキップ
            continue
        db.commit()
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
# バンドル取得
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
    #
    # External CLI 実行は特殊: Tauri の OrchestrationManager が独自の tick で
    # sidecar ワーカーをディスパッチし、行を即座に `processing` に変更する。
    # sidecar は execution_kind=external_cli のため短絡終了し（delegated
    # マーカーを返す）、*実際の* ランナー — フロントエンドポーラーから呼ばれる
    # Rust の consume_external_cli_bundle — は sidecar がステータスを
    # 進めた後に bundle を取得する必要がある。この例外がないと
    # Rust ランナーが毎回 409 になってしまう。
    #
    # /claim がアトミックに `processing` へ変更してから job_token を
    # 発行するようになったため、`processing` は両方の経路で許可される。
    # これがないと http_provider 経路が次の bundle 取得で自分自身を
    # 409 にしてしまう（claim → processing → bundle = 409）。
    allowed_statuses = ("pending", "pending_local", "processing")
    if execution.status not in allowed_statuses:
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

    # ジャッジ: 並列ステップの実際の出力をプロンプトに追加する。
    # デフォルトの judge_prompt はスキル *名* を列挙して「比較せよ」と
    # 指示するだけだが、CLI パスではモデルが出力を読む他のチャネルがない
    # （input_data もワークスペースファイルもない）。インライン化して
    # ジャッジが実際に評価できるようにする。HTTP provider パスでは
    # input_data dict 全体がプロンプトと共に渡されていたため、
    # このギャップは見えなかった。
    if exec_role == "debate_judge":
        try:
            judge_inputs = input_data.get("group_outputs") or []
            if isinstance(judge_inputs, list) and judge_inputs:
                appended_blocks = []
                for go in judge_inputs:
                    if not isinstance(go, dict):
                        continue
                    name = go.get("skill_name") or "(unnamed)"
                    out = (go.get("output") or "").strip()
                    if not out:
                        continue
                    appended_blocks.append(
                        f"### スキル: {name}\n\n```\n{out}\n```"
                    )
                if appended_blocks:
                    final_prompt = (
                        final_prompt
                        + "\n\n# 評価対象の出力\n\n以下が並列実行された各スキルの実際の出力です。"
                        + "これらを直接比較・評価してください（ワークスペース内のファイルを"
                        + "探す必要はありません — すべてここに含まれています）。\n\n"
                        + "\n\n".join(appended_blocks)
                    )
        except Exception as _judge_inline_err:
            logger.warning(
                "judge inline outputs failed for execution %s: %s",
                execution_id, _judge_inline_err,
            )

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
        # ──────────────────────────────────────────────────────────
        # Parent Leader の特殊ケース: workflow_skill_id が None。
        #
        # Leader は _start_parent_skill が作成する合成ステップで、
        # WorkflowSkill 行を持たないため、4 階層の設定チェーンは
        # `workflow.config_json` のみに縮退する。
        # ワークフローレベルで external_cli を選択している場合、
        # Workflow + parent_model_type から直接 external_cli ペイロードを
        # 構築する。子ステップに対する build_external_cli_payload と同様。
        # ──────────────────────────────────────────────────────────
        if (
            execution.workflow_execution_id
            and not execution.workflow_skill_id
            and execution.execution_kind == "external_cli"
        ):
            from app.services.workflow_step_schema import (
                parse_execution_config,
                is_legacy_step,
            )
            from app.services.external_cli_adapters import build_external_cli_payload
            from app.services.coordinator_extensions import list_adapters
            from app.services.coordinator_service import (
                EXECUTION_KIND_EXTERNAL_CLI as _EK_CLI,
            )
            from app.models import Workflow as _WF, WorkflowExecution as _WE
            wf_row = None
            we_row = db.query(_WE).filter(_WE.id == execution.workflow_execution_id).first()
            if we_row and we_row.workflow_id:
                wf_row = db.query(_WF).filter(_WF.id == we_row.workflow_id).first()
            if wf_row and wf_row.config_json:
                wf_cfg = parse_execution_config(wf_row.config_json)
                if not is_legacy_step(wf_cfg) and wf_cfg.execution.execution_kind == "external_cli":
                    # preferred_adapter / candidate / runtime hint でアダプタを解決する。
                    target = None
                    enabled_adapters = list_adapters(db, only_enabled=True)
                    pref = wf_cfg.execution.preferred_adapter
                    candidates = list(wf_cfg.execution.candidate_adapters or [])
                    if pref:
                        for a in enabled_adapters:
                            if a.transport == "external_cli" and a.name == pref:
                                target = a
                                break
                    if target is None:
                        for name in candidates:
                            for a in enabled_adapters:
                                if a.transport == "external_cli" and a.name == name:
                                    target = a
                                    break
                            if target is not None:
                                break
                    if target is None and wf_cfg.execution.cli_runtime_hint:
                        for a in enabled_adapters:
                            if a.transport != "external_cli":
                                continue
                            try:
                                cfg = json.loads(a.config or "{}")
                            except json.JSONDecodeError:
                                cfg = {}
                            if cfg.get("runtime") == wf_cfg.execution.cli_runtime_hint:
                                target = a
                                break
                    if target is not None:
                        # ペイロード構築 — 親のプロンプトを CLI 入力として使用し、
                        # approval ポリシーから allow_writes を取得する。
                        approval = wf_cfg.approval
                        allow_writes = bool(
                            approval.allow_writes or approval.policy == "allow_write"
                        )
                        allow_shell = bool(
                            approval.allow_shell or approval.policy == "allow_shell"
                        )
                        # 子ステップと同様に CoordinatorWorkspace を予約する。
                        # これは重要: Rust ランナーの workspace_ensure_dir 呼び出し
                        # （エンドツーエンドで動作する分岐 — WE 35 で実証済み）は
                        # /api/worker/workspaces/{id}/path に POST するため、
                        # CoordinatorWorkspace に行が存在する必要がある。
                        # ここで予約しないと ensure_dir の POST が 404 になり、
                        # Rust ランナーが claude の起動まで進まない。
                        #
                        # 以前の試み（workspace_id を省略して cwd_hint のみに
                        # 依存）は backend ログからは原因を特定できない理由で
                        # ハングした — ホストの claude が同じプロンプトを 6 秒で
                        # 実行できるのに Rust は /complete を POST しなかった。
                        # 動作実績のある子ステップパスをミラーするのが最も
                        # 確実な修正。
                        from app.services.coordinator_service import (
                            get_plan_by_workflow_execution,
                            reserve_workspace,
                            WORKSPACE_TEMP_DIR,
                        )
                        leader_workspace_id = None
                        leader_plan = get_plan_by_workflow_execution(
                            db, execution.workflow_execution_id
                        )
                        if leader_plan is not None:
                            leader_ws_row = reserve_workspace(
                                db, leader_plan.plan_id,
                                task_id=f"leader_{execution.id}",
                                mode=WORKSPACE_TEMP_DIR,
                            )
                            leader_workspace_id = leader_ws_row.workspace_id
                            db.commit()
                        # cwd は意図的に空にする: Rust の
                        # consume_external_cli_bundle は
                        # `workspace_path.is_none() || cwd.is_empty()`
                        # で workspace_ensure_dir を呼ぶかどうか判定する。
                        # ensure_dir は実際の作業ディレクトリを
                        # ~/.nexmagi/workspaces/<plan_id>/<task_id>-<workspace_id>/
                        # に作成し、パスを backend に POST で返す。
                        # そのパスを Rust ランナーが検証して claude の cwd
                        # として渡す。空でない cwd_hint を渡すと ensure_dir が
                        # スキップされ、ランナーが cwd_hint に対して直接
                        # validate_cwd を試みる — それが以前の失敗パスだった。
                        cli_payload = build_external_cli_payload(
                            target,
                            cwd="",
                            prompt=final_prompt or "",
                            task_id=f"leader_{execution.id}",
                            workflow_run_id=str(execution.workflow_execution_id),
                            task_role="leader",
                            allow_writes=allow_writes,
                            allow_shell=allow_shell,
                            approval_policy=approval.policy,
                            selection_reason=f"workflow_pref:external_cli:{target.name}",
                            workspace_id=leader_workspace_id,
                            workspace_mode="temp_dir",
                            cli_model=getattr(wf_cfg.execution, "cli_model", None),
                        )
                        if cli_payload is not None:
                            external_cli_payload = cli_payload
                            execution_kind = _EK_CLI
                            logger.info(
                                "external_cli_selected (parent leader) execution_id=%s adapter=%s",
                                execution.id, target.name,
                            )
        # ──────────────────────────────────────────────────────────
        # ディベートジャッジの CLI ルーティング。
        #
        # ジャッジは WorkflowSkill を持たない — WorkflowGroup に
        # 付随する内部ロール。グループの
        # config_json.judge_execution_config が external_cli を
        # 選択した場合、_launch_judge が Execution 行に
        # execution_kind="external_cli" をスタンプする。ここでは
        # group.judge_prompt + 並列グループの出力（既に input_data 内）
        # から external_cli ペイロードを構築して対応する。
        # ──────────────────────────────────────────────────────────
        if (
            execution.execution_kind == "external_cli"
            and getattr(execution, "execution_role", None) == "debate_judge"
            and getattr(execution, "execution_group_id", None)
        ):
            from app.services.external_cli_adapters import build_external_cli_payload
            from app.services.coordinator_extensions import list_adapters
            from app.services.coordinator_service import (
                EXECUTION_KIND_EXTERNAL_CLI as _EK_CLI_J,
            )
            from app.models import WorkflowGroup as _WGJ
            grp_row = (
                db.query(_WGJ)
                .filter(_WGJ.id == execution.execution_group_id)
                .first()
            )
            judge_cfg = None
            if grp_row and grp_row.config_json:
                try:
                    grp_cfg_dict = json.loads(grp_row.config_json) if isinstance(grp_row.config_json, str) else grp_row.config_json
                    judge_cfg = (grp_cfg_dict or {}).get("judge_execution_config") or None
                except (json.JSONDecodeError, TypeError):
                    judge_cfg = None
            if judge_cfg:
                exec_block = (judge_cfg or {}).get("execution", {})
                pref_adapter = exec_block.get("preferred_adapter")
                runtime_hint = exec_block.get("cli_runtime_hint")
                cli_model = exec_block.get("cli_model")
                target_judge = None
                enabled_adapters_j = list_adapters(db, only_enabled=True)
                if pref_adapter:
                    for a in enabled_adapters_j:
                        if a.transport == "external_cli" and a.name == pref_adapter:
                            target_judge = a
                            break
                if target_judge is None and runtime_hint:
                    for a in enabled_adapters_j:
                        if a.transport != "external_cli":
                            continue
                        try:
                            cfg_j = json.loads(a.config or "{}")
                        except json.JSONDecodeError:
                            cfg_j = {}
                        if cfg_j.get("runtime") == runtime_hint:
                            target_judge = a
                            break
                if target_judge is not None:
                    # ジャッジには実ワークスペースは不要（読み取り専用のテキスト
                    # 評価、ファイル書き込みなし）だが、Rust ランナーは
                    # 登録済み CoordinatorWorkspace ID がないと空の cwd を
                    # 拒否する（ensure_dir のため）。leader パスと同様に
                    # temp_dir ワークスペースを予約し、cwd を空にしておく。
                    # ランナーが解決済みパスを POST で返す。
                    from app.services.coordinator_service import (
                        get_plan_by_workflow_execution as _get_plan_j,
                        reserve_workspace as _reserve_ws_j,
                        WORKSPACE_TEMP_DIR as _WS_TEMP_J,
                    )
                    judge_workspace_id = None
                    judge_plan = _get_plan_j(db, execution.workflow_execution_id)
                    if judge_plan is not None:
                        judge_ws_row = _reserve_ws_j(
                            db, judge_plan.plan_id,
                            task_id=f"judge_{execution.id}",
                            mode=_WS_TEMP_J,
                        )
                        judge_workspace_id = judge_ws_row.workspace_id
                        db.commit()
                    judge_payload = build_external_cli_payload(
                        target_judge,
                        cwd="",
                        prompt=final_prompt or "",
                        task_id=f"judge_{execution.id}",
                        workflow_run_id=str(execution.workflow_execution_id),
                        task_role="judge",
                        allow_writes=False,
                        allow_shell=False,
                        approval_policy="read_only",
                        selection_reason=f"judge_pref:external_cli:{target_judge.name}",
                        workspace_id=judge_workspace_id,
                        workspace_mode="temp_dir",
                        cli_model=cli_model,
                    )
                    if judge_payload is not None:
                        external_cli_payload = judge_payload
                        execution_kind = _EK_CLI_J
                        provider_payload = None
                        fallback_provider_payload = None
                        logger.info(
                            "external_cli_selected (judge) execution_id=%s adapter=%s",
                            execution.id, target_judge.name,
                        )
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
                    # 完全に構成されたステッププロンプトを注入し、
                    # external_cli ペイロードビルダーが起動する CLI バイナリに
                    # 渡せるようにする。これがないとペイロードのプロンプトは
                    # task["objective"]（"claude_impl" のような短いスキル名）に
                    # フォールバックし、CLI が実質的な指示もスキル内容も
                    # 上流の出力コンテキストもなしで実行されてしまう。
                    if final_prompt:
                        matched_task["prompt"] = final_prompt
                    # WorkflowSkill 行からパース済みの StepExecutionConfig を
                    # 付与し、resolve_execution_kind がステップごとに
                    # ルーティングできるようにする。レガシー行はデフォルト設定を
                    # 返し、従来と同一の動作になる。
                    try:
                        from app.services.workflow_step_schema import (
                            parse_execution_config,
                            merge_step_execution_config_chain,
                        )
                        from app.models import (
                            WorkflowSkill as _WorkflowSkill,
                            WorkflowGroup as _WorkflowGroup,
                            Workflow as _Workflow,
                        )
                        ws_row = (
                            db.query(_WorkflowSkill)
                            .filter(_WorkflowSkill.id == execution.workflow_skill_id)
                            .first()
                        )
                        if ws_row is not None:
                            # 4-level inheritance chain (left = weakest):
                            #   workflow → group → skill → workflow_skill
                            # ブロック単位の置換 —
                            # merge_step_execution_configs の docstring を参照。
                            workflow_cfg = None
                            group_cfg = None
                            skill_cfg = None
                            if ws_row.workflow_id is not None:
                                wf_row = (
                                    db.query(_Workflow)
                                    .filter(_Workflow.id == ws_row.workflow_id)
                                    .first()
                                )
                                if wf_row is not None and getattr(wf_row, "config_json", None):
                                    workflow_cfg = parse_execution_config(wf_row.config_json)
                            if ws_row.group_id is not None:
                                grp_row = (
                                    db.query(_WorkflowGroup)
                                    .filter(_WorkflowGroup.id == ws_row.group_id)
                                    .first()
                                )
                                if grp_row is not None and getattr(grp_row, "config_json", None):
                                    group_cfg = parse_execution_config(grp_row.config_json)
                            if ws_row.skill_id is not None:
                                skill_row = (
                                    db.query(Skill)
                                    .filter(Skill.id == ws_row.skill_id)
                                    .first()
                                )
                                if skill_row is not None and getattr(
                                    skill_row, "config_json", None
                                ):
                                    skill_cfg = parse_execution_config(skill_row.config_json)
                            step_cfg = parse_execution_config(ws_row.config_json)
                            matched_task["_step_execution_config"] = (
                                merge_step_execution_config_chain(
                                    workflow_cfg, group_cfg, skill_cfg, step_cfg
                                )
                            )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "step execution_config parse skipped for execution %s: %s",
                            execution_id, exc,
                        )

                    # ステップ 1: 実行種別を決定。resolve_execution_kind は
                    # external_cli_payload を返すか HTTP パスに委譲する。
                    # 矛盾するペイロードを避けるため、同一バンドルで
                    # 両方のルーティングを実行することはない。
                    kind_result = resolve_execution_kind(
                        db, plan, matched_task,
                        retry_count=int(getattr(execution, "retry_count", 0) or 0),
                    )
                    if kind_result.get("execution_kind") == EXECUTION_KIND_EXTERNAL_CLI:
                        execution_kind = EXECUTION_KIND_EXTERNAL_CLI
                        external_cli_payload = kind_result.get("external_cli_payload")
                        # ルーティング決定を永続化し、フロントエンドのポーリング
                        # ループが bundle を再取得せずに適切なランナーに
                        # ディスパッチできるようにする。リクエスト終了時ではなく
                        # ここで commit し、次の /api/user/executions 読み取りで
                        # 反映されるようにする。
                        try:
                            execution.execution_kind = EXECUTION_KIND_EXTERNAL_CLI
                            db.commit()
                        except Exception as persist_err:  # noqa: BLE001
                            logger.warning(
                                "execution_kind persist failed for %s: %s",
                                execution.id, persist_err,
                            )
                        # External CLI バンドルは provider_payload を持ってはならない —
                        # desktop ランタイムがこれらを所有し、sidecar はバイパスする。
                        provider_payload = None
                        fallback_provider_payload = None
                        logger.info(
                            "external_cli_selected execution_id=%s adapter=%s runtime=%s",
                            execution.id,
                            kind_result.get("adapter_name"),
                            kind_result.get("runtime"),
                        )
                    else:
                        # ステップ 2: HTTP / 内部 provider パス。
                        # resolve_execution_provider_bundle が生成するより
                        # リッチなフォールバックペイロードが必要なので、
                        # kind_result の provider_payload ではなくここで呼ぶ。
                        routing = resolve_execution_provider_bundle(
                            db, plan, matched_task,
                            retry_count=int(getattr(execution, "retry_count", 0) or 0),
                        )
                        provider_payload = routing.get("provider_payload")
                        fallback_provider_payload = routing.get("fallback_provider_payload")
                        # ルーティング理由をペイロード自体に埋め込み、sidecar が
                        # 実際の provider メタデータにエコーバックできるようにする。
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
                        # resolve_execution_kind が external_cli を要求したのに
                        # HTTP パスに着地した場合、目立つようにログ出力する。
                        # このログ行がないと worker 層で格下げが見えなくなる。
                        cli_fallback = kind_result.get("external_cli_fallback_reason")
                        if cli_fallback:
                            logger.warning(
                                "external_cli_fallback execution_id=%s reason=%s",
                                execution.id,
                                cli_fallback,
                            )
                            # 2つの永続化チャネル:
                            # 1. provider_payload — sidecar が /complete 時に
                            #    provider_meta の一部としてエコーバック
                            #    できるようにする（ベストエフォート、未知の
                            #    キーを転送しないアダプタでは失われる可能性あり）。
                            # 2. input_data センチネル — completion_service が
                            #    アーティファクトメタデータ構築時に Execution 行
                            #    から直接読み取る。こちらが永続チャネルであり、
                            #    ランタイムアダプタがペイロードキーを削除しても
                            #    動作する。
                            if provider_payload is not None:
                                provider_payload["external_cli_fallback_reason"] = (
                                    cli_fallback
                                )
                            try:
                                if isinstance(input_data, dict):
                                    input_data["_nexmagi_external_cli_fallback_reason"] = cli_fallback
                            except Exception:  # noqa: BLE001
                                pass
    except Exception as exc:  # noqa: BLE001
        # warning から exception に昇格し、スタックトレースを
        # キャプチャする。以前のバージョンは実際のバグを飲み込んでいた
        # （例: coordinator_service.py の logger インポート欠落が
        # 全ステップをデフォルト HTTP provider パスに黙って格下げし、
        # CLI ルーティングが発火しなかった理由がアーティファクトから
        # 一切わからなかった）。
        logger.exception(
            "provider routing skipped for execution %s: %s",
            execution_id, exc,
        )
        # input_data にセンチネルをスタンプし、finalize_execution が
        # アーティファクトメタデータにエコーできるようにする。これがないと
        # 下流のオブザーバーは全ルーティングロジックを黙ってバイパスした
        # 「成功」実行を見ることになる。
        try:
            if isinstance(input_data, dict):
                input_data["_nexmagi_routing_failed"] = (
                    f"{type(exc).__name__}: {exc}"
                )
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # スタンドアロンスキル実行 — external_cli ルーティング。
    #
    # POST /api/execute 経由で起動されたスキル（ワークフロープランなし）では、
    # execute.py がスキルの execution_config を input_data の
    # `_nexmagi_skill_execution_config` に埋め込む（スキルが非デフォルト設定を
    # 宣言している場合）。ここで external_cli を処理する。スタンドアロンの
    # provider 選択は既存の model_type パスに委ねる。
    # ------------------------------------------------------------------
    if (
        external_cli_payload is None
        and execution_kind == "http_provider"
        and execution.skill_id
        and not execution.workflow_execution_id
    ):
        try:
            raw_cfg = input_data.get("_nexmagi_skill_execution_config") if isinstance(input_data, dict) else None
            if isinstance(raw_cfg, dict):
                from app.services.workflow_step_schema import StepExecutionConfig
                skill_cfg = StepExecutionConfig.model_validate(raw_cfg)
                if skill_cfg.execution.execution_kind == "external_cli":
                    from app.services.external_cli_adapters import (
                        build_external_cli_payload,
                    )
                    from app.services.coordinator_extensions import list_adapters
                    from app.services.external_cli_capabilities import (
                        required_capabilities_for_task,
                    )

                    # アダプタ選択: preferred_adapter → cli_runtime_hint。
                    target = None
                    preferred_name = skill_cfg.execution.preferred_adapter
                    runtime_hint = skill_cfg.execution.cli_runtime_hint
                    adapters = list_adapters(db, only_enabled=True)
                    if preferred_name:
                        for a in adapters:
                            if a.transport == "external_cli" and a.name == preferred_name:
                                target = a
                                break
                    if target is None and runtime_hint:
                        for a in adapters:
                            if a.transport != "external_cli":
                                continue
                            try:
                                cfg = json.loads(a.config or "{}")
                            except json.JSONDecodeError:
                                cfg = {}
                            if cfg.get("runtime") == runtime_hint:
                                target = a
                                break

                    cwd = skill_cfg.execution.cwd_hint
                    if target is not None and cwd:
                        allow_writes = bool(
                            skill_cfg.approval.allow_writes
                            or skill_cfg.approval.policy == "allow_write"
                        )
                        allow_shell = bool(
                            skill_cfg.approval.allow_shell
                            or skill_cfg.approval.policy == "allow_shell"
                        )
                        required_caps = required_capabilities_for_task(
                            role="writer",
                            writes_files=allow_writes,
                            allow_shell=allow_shell,
                            has_workspace=False,
                            requires_local_auth=True,
                        )
                        # ケイパビリティゲート（ワークフローパスと同一ポリシー）。
                        try:
                            target_caps_raw = json.loads(target.capabilities or "[]")
                        except json.JSONDecodeError:
                            target_caps_raw = []
                        target_caps = set(
                            target_caps_raw if isinstance(target_caps_raw, list) else []
                        )
                        step_required = set(skill_cfg.execution.required_capabilities or [])
                        if allow_writes:
                            step_required.add("file_write")
                        if allow_shell:
                            step_required.add("shell_exec")
                        missing_caps = sorted(step_required - target_caps)
                        if missing_caps:
                            logger.warning(
                                "standalone skill external_cli fallback to provider: "
                                "execution=%s adapter=%s missing_caps=%s",
                                execution.id, target.name, missing_caps,
                            )
                        else:
                            external_cli_payload = build_external_cli_payload(
                                target,
                                cwd=cwd,
                                prompt=final_prompt,
                                task_id=f"skill_{execution.id}",
                                workflow_run_id=f"standalone_{execution.id}",
                                task_role="writer",
                                allow_writes=allow_writes,
                                allow_shell=allow_shell,
                                required_capabilities=required_caps,
                                approval_policy=skill_cfg.approval.policy,
                                selection_reason=(
                                    f"skill_standalone:external_cli:{target.name}"
                                ),
                                cli_model=getattr(skill_cfg.execution, "cli_model", None),
                            )
                            if external_cli_payload is not None:
                                execution_kind = "external_cli"
                                provider_payload = None
                                fallback_provider_payload = None
                                logger.info(
                                    "standalone skill external_cli selected "
                                    "execution_id=%s adapter=%s runtime=%s",
                                    execution.id, target.name,
                                    external_cli_payload.get("runtime"),
                                )
                    elif target is None:
                        logger.warning(
                            "standalone skill execution_config requested external_cli "
                            "but no matching adapter found: execution=%s preferred=%s hint=%s",
                            execution.id, preferred_name, runtime_hint,
                        )
                    elif not cwd:
                        logger.warning(
                            "standalone skill external_cli requires cwd_hint: execution=%s",
                            execution.id,
                        )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "standalone skill external_cli routing skipped for execution %s: %s",
                execution_id, exc,
            )

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
    # external_cli バンドルのデバッグダンプ（WF13 の親パス検証後に削除予定）。
    # Rust が受け取る構造化ペイロードをログ出力し、Tauri の stderr なしで
    # validate_cwd / レジストリ検索 / ケイパビリティチェックの失敗モードと
    # 突き合わせできるようにする。
    if execution_kind == "external_cli" and external_cli_payload is not None:
        logger.info(
            "external_cli_payload_debug execution_id=%s adapter_id=%s runtime=%s cwd=%r workspace_id=%r required_caps=%s allow_writes=%s allow_shell=%s",
            execution_id,
            external_cli_payload.get("adapter_id"),
            external_cli_payload.get("runtime"),
            external_cli_payload.get("cwd"),
            external_cli_payload.get("workspace_id"),
            external_cli_payload.get("required_capabilities"),
            external_cli_payload.get("allow_writes"),
            external_cli_payload.get("allow_shell"),
        )

    return BundleResponse(**bundle_data, signature=signature)


# ---------------------------------------------------------------------------
# 完了 POST
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
    # external_cli 実行が失敗した場合（非ゼロ終了、バイナリ欠落、
    # auth_required、capability_mismatch 等）でも local worker は
    # 構造化された meta dict を保持している。エラーパス経由で転送し、
    # finalize_execution がアーティファクトにスタンプして失敗を
    # 監査可能にする。通常の HTTP エラーでは None。
    external_cli_meta: Optional[dict] = None
    provider_meta: Optional[dict] = None


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

    # レースコンディションガード。
    # 複数のワーカー（docker local_worker デーモン + Tauri orchestration
    # sidecar）が同じ execution 行を競合する場合、一方が勝って
    # /complete を POST する（status=success）。負けた側の bundle 取得は
    # 409 になり、負けた側がここに /error を POST しようとする。
    # そのエラー報告を受け入れると、正常に成功した行をエラーで
    # 上書きしてしまい、ワークフローのリトライ機構が重複実行を生成する。
    #
    # 修正: 非エラーの終端状態で既に完了した execution のエラー報告は
    # 無視する。監査でレースが見えるようログは残すが、行は変更しない。
    if execution.status in ("success", "cancelled"):
        logger.info(
            "Ignoring late error report for execution %s (current status=%s, "
            "loser-of-race scenario): %s",
            execution_id, execution.status,
            (body.error_message or "")[:200],
        )
        return {"status": execution.status, "execution_id": execution_id, "noop": True}

    finalize_execution(
        db=db,
        execution=execution,
        output="",
        model_used=execution.model_used or "",
        tokens_used=0,
        execution_time_ms=body.execution_time_ms,
        status_result="error",
        error_message=body.error_message,
        provider_meta=body.provider_meta,
        external_cli_meta=body.external_cli_meta,
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
# ワークスペースライフサイクルエンドポイント（Tauri ファイルシステム連携）
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
    """Tauri 側がワークスペース用に作成した具体的なファイルシステムパスを報告する。
    行を reserved -> active に遷移させる。

    パスは絶対パスであること、トラバーサルシーケンスを含まないことを検証する。
    backend はパスが desktop ユーザーの実際のワークスペースルート配下にあるか
    完全には検証できない（マシン固有のため）が、明らかなエスケープは拒否する。
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


@router.post("/adapters/{adapter_id}/health")
async def api_sync_adapter_health(
    adapter_id: str,
    health_status: str = "unknown",
    detail: str = None,
    capabilities: str = None,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user),
):
    """Tauri ランタイムからアダプタの health 状態をバックエンドに同期する。"""
    from app.models import CoordinatorAdapter
    adapter = db.query(CoordinatorAdapter).filter(
        CoordinatorAdapter.adapter_id == adapter_id,
    ).first()
    if not adapter:
        # adapter_id で見つからない場合は名前 (human-readable) でも検索
        adapter = db.query(CoordinatorAdapter).filter(
            CoordinatorAdapter.name == adapter_id,
        ).first()
    if not adapter:
        raise HTTPException(status_code=404, detail="adapter not found")

    adapter.health_status = health_status
    adapter.last_health_check = datetime.now(timezone.utc)
    if capabilities:
        adapter.supported_capabilities = capabilities
    db.commit()
    db.refresh(adapter)
    return {
        "adapter_id": adapter.adapter_id,
        "name": adapter.name,
        "health_status": adapter.health_status,
        "last_health_check": adapter.last_health_check.isoformat() if adapter.last_health_check else None,
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
