from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.auth import get_current_user
from app.models import Account, APIConfig, Skill, AccountSkill, Execution, Workflow, WorkflowSkill, WorkflowExecution
from app.schemas import (
    ExecuteSkillRequest,
    ExecuteSkillResponse,
    ExecuteWorkflowRequest,
    ExecuteWorkflowResponse,
)
from app.services.worker_auth import create_job_token, generate_lease_token
from app.encryption import encryption_service
from app.config import settings
import logging

logger = logging.getLogger(__name__)

# Redis (SSE ストリーミング用)
try:
    from app.services.redis_service import subscribe_stream, publish_cancel
    REDIS_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Redis not available: {str(e)}. SSE streaming will be disabled.")
    REDIS_AVAILABLE = False
    subscribe_stream = None
    publish_cancel = None
from app.utils.file_export import export_content
from app.utils.skill_utils import replace_placeholders
from app.tasks.execution_tasks import _build_skill_input, _augment_skill_input_with_profile, _resolve_agent_profile
from datetime import datetime, timezone, timedelta
import json
import time
import asyncio

router = APIRouter(prefix="/api/execute", tags=["実行"])


def _check_rate_limit(db: Session, account_id: int) -> None:
    """APIConfigのレートリミットを確認し、超過していれば429を返す"""
    api_config = db.query(APIConfig).filter(
        APIConfig.account_id == account_id,
        APIConfig.is_enabled == True,
    ).first()
    if not api_config:
        return  # APIConfig が無い場合はリミットなし

    jst = timezone(timedelta(hours=9))
    now = datetime.now(jst)

    # 1時間あたりのリミット
    if api_config.rate_limit_per_hour:
        one_hour_ago = now - timedelta(hours=1)
        count_hour = db.query(func.count(Execution.id)).filter(
            Execution.account_id == account_id,
            Execution.executed_at >= one_hour_ago,
        ).scalar() or 0
        if count_hour >= api_config.rate_limit_per_hour:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"1時間あたりの実行回数制限（{api_config.rate_limit_per_hour}回）に達しました",
            )

    # 1日あたりのリミット
    if api_config.rate_limit_per_day:
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        count_day = db.query(func.count(Execution.id)).filter(
            Execution.account_id == account_id,
            Execution.executed_at >= today_start,
        ).scalar() or 0
        if count_day >= api_config.rate_limit_per_day:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"1日あたりの実行回数制限（{api_config.rate_limit_per_day}回）に達しました",
            )


@router.get("/download/{execution_id}")
async def download_execution_file(
    execution_id: int,
    output_format: str = "txt",
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user)
):
    """
    実行結果をファイルとしてダウンロード

    Args:
        execution_id: 実行ID
        output_format: 出力形式（csv, pdf, docx, md, txt）
    """
    # 実行ログの取得
    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="実行ログが見つかりません"
        )

    # アクセス権限の確認
    if execution.account_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="この実行ログへのアクセス権限がありません"
        )

    # ファイル出力
    try:
        file_bytes, filename = export_content(
            content=execution.output_data,
            output_format=output_format,
            filename=f"execution_{execution_id}"
        )

        # 適切なContent-Typeを設定（日本語対応のためcharsetを指定）
        content_types = {
            "csv": "text/csv; charset=utf-8",
            "pdf": "application/pdf",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "md": "text/markdown; charset=utf-8",
            "txt": "text/plain; charset=utf-8"
        }
        content_type = content_types.get(output_format.lower(), "application/octet-stream")

        # ファイル名のエンコーディング（日本語対応）
        import urllib.parse
        encoded_filename = urllib.parse.quote(filename.encode('utf-8'))

        return Response(
            content=file_bytes,
            media_type=content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"; filename*=UTF-8\'\'{encoded_filename}'
            }
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"ファイルダウンロードエラー: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ファイルの生成に失敗しました: {str(e)}"
        )


@router.post("", response_model=ExecuteSkillResponse)
async def execute_skill(
    request: ExecuteSkillRequest,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user)
):
    """
    スキルを実行（ローカルワーカーが処理）

    Execution を pending_local で作成し、ローカルデーモンが claim → 実行する。
    スキル本文はクライアントに送信されない（バンドル配信時に復号）。
    """
    # デバッグ: 受信したリクエスト（本番は入力詳細を出力しない）
    logger.info(f"Execute request - skill_id: {request.skill_id}, output_format: {request.output_format}")
    if settings.ENVIRONMENT != "production":
        logger.info(f"Execute request - skill_id: {request.skill_id}, input_data: {request.input_data}")
    else:
        logger.info(f"Execute request - skill_id: {request.skill_id}")

    # スキルの取得
    skill = db.query(Skill).filter(Skill.id == request.skill_id).first()
    if not skill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="スキルが見つかりません"
        )

    # アクセス権限の確認
    assignment = db.query(AccountSkill).filter(
        AccountSkill.account_id == current_user.id,
        AccountSkill.skill_id == request.skill_id
    ).first()

    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="このスキルへのアクセス権限がありません"
        )

    # スキルが有効かチェック
    if not skill.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="このスキルは現在利用できません"
        )

    # レートリミットチェック
    _check_rate_limit(db, current_user.id)

    # 実行時にDeep Thinkが有効かどうかを判定
    # 優先順位: リクエストで明示的に指定された場合 -> スキルの設定 -> デフォルトTrue
    final_enable_deep_think = request.enable_deep_think
    if final_enable_deep_think is None:
        final_enable_deep_think = getattr(skill, 'enable_deep_think', True)
    if final_enable_deep_think is None:
        final_enable_deep_think = True

    # 実行ログの作成（pending状態）
    # JST（日本時間）で現在時刻を取得
    jst = timezone(timedelta(hours=9))
    now_jst = datetime.now(jst)

    # output_formatを取得（明示的に処理）
    output_format_value = request.output_format
    if not output_format_value or output_format_value == "":
        output_format_value = "txt"

    logger.info(f"Execution creation: output_format from request={request.output_format}, final={output_format_value}")

    # 常にローカル実行（デーモンが処理）
    raw_lease_token, lease_token_hash = generate_lease_token()
    lease_expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=settings.WORKER_LEASE_TTL_SECONDS
    )

    execution = Execution(
        account_id=current_user.id,
        skill_id=skill.id,
        input_data=json.dumps(request.input_data, ensure_ascii=False),
        status="pending_local",
        model_used=skill.model_type,
        enable_deep_think=bool(final_enable_deep_think),
        output_format=output_format_value,
        dispatch_mode="local",
        lease_token_hash=lease_token_hash,
        lease_expires_at=lease_expires_at,
        executed_at=now_jst,
        skill_name_snapshot=skill.name,
    )
    db.add(execution)
    db.commit()
    db.refresh(execution)

    job_token = create_job_token(execution.id, current_user.id)
    logger.info(f"Execution {execution.id} created for local worker")

    return {
        "execution_id": execution.id,
        "status": "pending_local",
        "job_token": job_token,
    }


@router.post("/workflow", response_model=ExecuteWorkflowResponse)
async def execute_workflow(
    request: ExecuteWorkflowRequest,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user),
):
    """
    ワークフローを実行（順次実行：各Step完了後に次のStepを自動起動）

    - WorkflowExecutionレコードを作成
    - 最初のStepのみを起動（順次実行のため）
    - 各Step完了時に次のStepが自動的に起動される
    - 前Stepの出力が次のStepの入力に自動マージされる
    - 応答として、workflow_execution_idと最初のexecution_idを返す
    """
    # ワークフローの取得とバリデーション
    wf = (
        db.query(Workflow)
        .filter(Workflow.id == request.workflow_id, Workflow.deleted_at.is_(None))
        .first()
    )
    if not wf or not wf.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ワークフローが見つからないか、現在利用できません",
        )

    # レートリミットチェック
    _check_rate_limit(db, current_user.id)

    # ワークフロー内のSkill一覧を取得
    wf_skills = (
        db.query(WorkflowSkill)
        .join(Skill, Skill.id == WorkflowSkill.skill_id)
        .filter(
            WorkflowSkill.workflow_id == request.workflow_id,
            Skill.deleted_at.is_(None),
            Skill.is_active == True,  # noqa: E712
        )
        .order_by(WorkflowSkill.skill_order.asc(), WorkflowSkill.id.asc())
        .all()
    )

    if not wf_skills:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="このワークフローには有効なStepがありません",
        )

    # ユーザーに割り当てられているスキルのみを許可
    assigned_skill_ids = {
        ask.skill_id
        for ask in db.query(AccountSkill)
        .filter(AccountSkill.account_id == current_user.id)
        .all()
    }

    # 実行可能なSkillのみをフィルタ
    executable_skills = [
        ws for ws in wf_skills
        if ws.skill and ws.skill.id in assigned_skill_ids
    ]

    if not executable_skills:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="このユーザーが実行可能なStepがワークフローに含まれていません",
        )

    # JST現在時刻を一度だけ取得
    jst = timezone(timedelta(hours=9))
    now_jst = datetime.now(jst)

    # WorkflowExecutionレコードを作成
    wf_execution = WorkflowExecution(
        workflow_id=request.workflow_id,
        account_id=current_user.id,
        status="pending",
        current_step=1,
        total_steps=len(executable_skills),
        workflow_name_snapshot=workflow.name,
        global_input_data=json.dumps(request.global_input_data or {}, ensure_ascii=False),
        per_skill_input_data=json.dumps(
            {str(k): v for k, v in (request.per_skill_input or {}).items()},
            ensure_ascii=False,
        ) if request.per_skill_input else None,
        current_stage=None,
        final_verdict=None,
        handoff_summary=None,
    )
    db.add(wf_execution)
    db.commit()
    db.refresh(wf_execution)

    # 実行モード判定
    workflow_execution_mode = "serial"

    # 並列モードの場合は全ステップを一括作成
    skills_to_launch = [executable_skills[0]] if workflow_execution_mode == "serial" else executable_skills

    # output_format
    output_format_value = request.output_format or "txt"

    # 常にローカル実行
    raw_lease_token, lease_token_hash = generate_lease_token()
    lease_expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=settings.WORKER_LEASE_TTL_SECONDS
    )

    # グループベースで最初に起動するスキルを決定
    from app.models import WorkflowGroup
    first_group = (
        db.query(WorkflowGroup)
        .filter(WorkflowGroup.workflow_id == request.workflow_id)
        .order_by(WorkflowGroup.group_order.asc())
        .first()
    )

    if first_group:
        # グループベース: 最初のグループのスキルを起動
        group_skills = [s for s in executable_skills if s.group_id == first_group.id]
        if first_group.execution_type == "parallel":
            skills_to_launch = group_skills  # 並列: グループ内の全スキル
        else:
            skills_to_launch = [group_skills[0]] if group_skills else []  # 直列: 最初の1つ
    else:
        # フォールバック: グループなし → 最初のスキルのみ
        skills_to_launch = [executable_skills[0]]

    launch_profiles = {
        _resolve_agent_profile(ws, ws.skill)
        for ws in skills_to_launch
        if getattr(ws, "skill", None) is not None
    }
    if len(launch_profiles) > 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="parallel group では mixed agent_profile を許可していません。MVP では同一 profile に揃えてください",
        )

    # Execution レコード作成
    created_executions = []
    structured_context = {"global": request.global_input_data or {}, "steps": {}, "all_step_results": [], "blackboard": {}}
    per_skill_input = {str(k): v for k, v in (request.per_skill_input or {}).items()}
    launched_profiles = []
    for ws in skills_to_launch:
        ws_skill = ws.skill
        skill_deep_think = getattr(ws_skill, "enable_deep_think", True)
        if skill_deep_think is None:
            skill_deep_think = True

        skill_input = _build_skill_input(
            ws,
            structured_context,
            request.global_input_data or {},
            "",
            per_skill_input,
            structured_context.get("all_step_results", []),
        )
        agent_profile = _augment_skill_input_with_profile(
            skill_input, wf_execution, wf, ws, ws_skill, structured_context
        )
        launched_profiles.append(agent_profile)

        execution = Execution(
            account_id=current_user.id,
            skill_id=ws_skill.id,
            workflow_execution_id=wf_execution.id,
            workflow_skill_id=ws.id,
            skill_order=ws.skill_order,
            input_data=json.dumps(skill_input, ensure_ascii=False),
            status="pending_local",
            model_used=ws_skill.model_type,
            agent_profile=agent_profile,
            enable_deep_think=bool(skill_deep_think),
            output_format=output_format_value,
            dispatch_mode="local",
            lease_token_hash=lease_token_hash,
            lease_expires_at=lease_expires_at,
            executed_at=now_jst,
            skill_name_snapshot=ws_skill.name,
        )
        db.add(execution)
        created_executions.append(execution)

    wf_execution.status = "processing"
    if launched_profiles:
        wf_execution.current_stage = launched_profiles[0]

    # synthesis event: ワークフロー開始
    from app.services.completion_service import append_synthesis_event
    append_synthesis_event(wf_execution, {
        "event_type": "workflow_start",
        "summary": f"ワークフロー実行を開始（{len(created_executions)}ステップ）",
    })
    db.commit()
    for ex in created_executions:
        db.refresh(ex)

    execution_ids = [ex.id for ex in created_executions]
    job_token = create_job_token(created_executions[0].id, current_user.id)

    logger.info(f"Workflow {wf_execution.id}: {len(created_executions)} steps created for local worker")

    return ExecuteWorkflowResponse(
        workflow_id=request.workflow_id,
        workflow_execution_id=wf_execution.id,
        execution_ids=execution_ids,
        job_token=job_token,
    )


@router.post("/{execution_id}/cancel")
async def cancel_execution(
    execution_id: int,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user)
):
    """
    実行中のスキルをキャンセルする
    """
    try:
        execution = db.query(Execution).filter(
            Execution.id == execution_id,
            Execution.account_id == current_user.id
        ).first()

        if not execution:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="実行ログが見つかりません"
            )

        # 既にキャンセル済みの場合は成功として返す
        if execution.status == "cancelled":
            logger.info(f"Execution {execution_id} is already cancelled")
            return {"status": "cancelled", "message": "既にキャンセル済みです"}

        # 完了済みの場合はキャンセルできない
        if execution.status in ["success", "error"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"この実行はキャンセルできません（現在のステータス: {execution.status}）"
            )

        # ステータスをキャンセルに更新
        execution.status = "cancelled"
        execution.error_message = "ユーザーによりキャンセルされました"

        # 確実にコミット
        db.commit()
        db.refresh(execution)

        # Redis Streamにキャンセルイベントを送信
        if REDIS_AVAILABLE and publish_cancel:
            try:
                publish_cancel(execution_id)
            except Exception as e:
                logger.warning(f"Failed to publish cancel event for execution {execution_id}: {str(e)}")

        logger.info(f"Execution {execution_id} cancelled by user {current_user.id}")

        return {"status": "cancelled", "message": "実行をキャンセルしました"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling execution {execution_id}: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"キャンセル処理中にエラーが発生しました: {str(e)}"
        )


@router.get("/{execution_id}/stream")
async def stream_execution(
    execution_id: int,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user)
):
    """
    実行結果をストリーミング配信（SSE）

    Args:
        execution_id: 実行ID
    """
    if not REDIS_AVAILABLE or not subscribe_stream:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ストリーミングサービスが利用できません。システム管理者に連絡してください。"
        )

    # 認証・認可チェック
    execution = db.query(Execution).filter(
        Execution.id == execution_id,
        Execution.account_id == current_user.id
    ).first()

    if not execution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="実行が見つかりません"
        )

    async def event_generator():
        """SSEイベント生成器"""
        connection_start_time = time.time()
        last_heartbeat = time.time()
        event_count = 0

        try:
            logger.info(f"Starting SSE stream for execution {execution_id}")
            async for event in subscribe_stream(execution_id):
                event_count += 1
                event_type = event.get("type", "chunk")
                event_data = event.get("data", "")

                # 接続タイムアウトチェック（90分）
                current_time = time.time()
                connection_duration = current_time - connection_start_time
                if connection_duration > settings.SSE_CONNECTION_TIMEOUT:
                    logger.warning(f"SSE connection timeout for execution {execution_id}: {connection_duration:.1f}s > {settings.SSE_CONNECTION_TIMEOUT}s")
                    timeout_data = json.dumps({"message": f"SSE接続がタイムアウトしました（90分）"})
                    yield f"event: error\n"
                    yield f"data: {timeout_data}\n\n"
                    break

                logger.info(f"SSE event {event_count} for execution {execution_id}: type={event_type}, data_length={len(event_data)}")

                # ハートビート送信（30秒ごと）
                if current_time - last_heartbeat > settings.SSE_HEARTBEAT_INTERVAL:
                    yield ": heartbeat\n\n"
                    last_heartbeat = current_time

                # イベント送信
                yield f"event: {event_type}\n"
                yield f"data: {event_data}\n\n"

                logger.info(f"SSE event {event_count} sent for execution {execution_id}: type={event_type}")

                # 完了時はループを抜ける（workflow_next_stepは継続）
                if event_type in ["complete", "error", "cancel"]:
                    logger.info(f"SSE stream ending for execution {execution_id}: type={event_type}")
                    break
        except Exception as e:
            logger.error(f"Error in SSE stream for execution {execution_id}: {str(e)}")
            # エラーイベント送信
            error_data = json.dumps({"message": str(e)})
            yield f"event: error\n"
            yield f"data: {error_data}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Nginxバッファリング無効化
        }
    )
