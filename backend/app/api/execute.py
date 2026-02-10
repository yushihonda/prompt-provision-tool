from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.auth import get_current_user
from app.models import Account, Prompt, AccountPrompt, Execution, Workflow, WorkflowSkill, WorkflowExecution
from app.schemas import (
    ExecutePromptRequest,
    ExecutePromptResponse,
    ExecuteWorkflowRequest,
    ExecuteWorkflowResponse,
)
from app.encryption import encryption_service
from app.services.openai_service import openai_service
from app.services.gemini_service import gemini_service
from app.config import settings
import logging

logger = logging.getLogger(__name__)

# 遅延インポート（CeleryとRedisが利用できない場合でもアプリケーションが起動できるように）
try:
    from app.services.redis_service import subscribe_stream, publish_cancel
    from app.tasks.execution_tasks import execute_prompt_task
    from app.celery_app import celery_app
    CELERY_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Celery/Redis not available: {str(e)}. Some features will be disabled.")
    CELERY_AVAILABLE = False
    celery_app = None
    execute_prompt_task = None
    subscribe_stream = None
    publish_cancel = None
from app.utils.file_export import export_content, parse_attached_files
from app.utils.prompt_utils import replace_placeholders, sanitize_output
from datetime import datetime, timezone, timedelta
import json
import time
import base64
import asyncio

router = APIRouter(prefix="/api/execute", tags=["実行"])


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


@router.post("", response_model=ExecutePromptResponse)
async def execute_prompt(
    request: ExecutePromptRequest,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user)
):
    """
    プロンプトを実行（Celeryタスク）

    重要: プロンプトの内容はクライアントに送信されない
    サーバー側でプロンプトと入力データを結合してAI APIに送信
    """
    # デバッグ: 受信したリクエスト（本番は入力詳細を出力しない）
    logger.info(f"Execute request - prompt_id: {request.prompt_id}, output_format: {request.output_format}")
    if settings.ENVIRONMENT != "production":
        logger.info(f"Execute request - prompt_id: {request.prompt_id}, input_data: {request.input_data}")
    else:
        logger.info(f"Execute request - prompt_id: {request.prompt_id}")

    # プロンプトの取得
    prompt = db.query(Prompt).filter(Prompt.id == request.prompt_id).first()
    if not prompt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="プロンプトが見つかりません"
        )

    # アクセス権限の確認
    assignment = db.query(AccountPrompt).filter(
        AccountPrompt.account_id == current_user.id,
        AccountPrompt.prompt_id == request.prompt_id
    ).first()

    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="このプロンプトへのアクセス権限がありません"
        )

    # プロンプトが有効かチェック
    if not prompt.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="このプロンプトは現在利用できません"
        )

    # 実行時にDeep Thinkが有効かどうかを判定
    # 優先順位: リクエストで明示的に指定された場合 -> プロンプトの設定 -> デフォルトTrue
    final_enable_deep_think = request.enable_deep_think
    if final_enable_deep_think is None:
        final_enable_deep_think = getattr(prompt, 'enable_deep_think', True)
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

    execution = Execution(
        account_id=current_user.id,
        prompt_id=prompt.id,
        input_data=json.dumps(request.input_data, ensure_ascii=False),
        status="pending",
        model_used=prompt.model_type, # 初期値として設定
        enable_deep_think=bool(final_enable_deep_think),  # 実行時点のDeep Think状態を保存
        output_format=output_format_value,  # 出力形式を保存
        executed_at=now_jst
    )
    db.add(execution)
    db.commit()
    db.refresh(execution)

    # Celeryタスクをキューに送信
    if not CELERY_AVAILABLE or not execute_prompt_task:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Celery/Redisサービスが利用できません。システム管理者に連絡してください。"
        )

    # 添付ファイルを辞書形式に変換（Celeryのシリアライズ対応）
    attachments_dict = None
    if request.attachments:
        attachments_dict = [
            {
                "filename": att.filename,
                "content": att.content
            }
            for att in request.attachments
        ]

    execute_prompt_task.delay(
            execution_id=execution.id,
            prompt_id=prompt.id,
            input_data=request.input_data,
        output_format=output_format_value,  # 保存した値を使用
        attachments=attachments_dict,
            enable_deep_think=request.enable_deep_think
        )

    logger.info(f"Execution {execution.id} queued as Celery task")

    return {
        "execution_id": execution.id,
        "status": "pending"
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

    # ワークフロー内のSkill（Prompt）一覧を取得
    wf_skills = (
        db.query(WorkflowSkill)
        .join(Prompt, Prompt.id == WorkflowSkill.prompt_id)
        .filter(
            WorkflowSkill.workflow_id == request.workflow_id,
            Prompt.deleted_at.is_(None),
            Prompt.is_active == True,  # noqa: E712
        )
        .order_by(WorkflowSkill.step_order.asc(), WorkflowSkill.id.asc())
        .all()
    )

    if not wf_skills:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="このワークフローには有効なStepがありません",
        )

    # ユーザーに割り当てられているプロンプトのみを許可
    assigned_prompt_ids = {
        ap.prompt_id
        for ap in db.query(AccountPrompt)
        .filter(AccountPrompt.account_id == current_user.id)
        .all()
    }

    # 実行可能なSkillのみをフィルタ
    executable_skills = [
        ws for ws in wf_skills
        if ws.prompt and ws.prompt.id in assigned_prompt_ids
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
        global_input_data=json.dumps(request.global_input_data or {}, ensure_ascii=False),
    )
    db.add(wf_execution)
    db.commit()
    db.refresh(wf_execution)

    # 最初のステップのみを起動（順次実行のため）
    first_skill = executable_skills[0]
    prompt = first_skill.prompt

    # per_skill_input のキーは workflow_skill_id を想定
    per_skill_overrides = {}
    if request.per_skill_input and first_skill.id in request.per_skill_input:
        per_skill_overrides = request.per_skill_input[first_skill.id]

    # グローバル入力とSkill個別入力をマージ（個別が優先）
    merged_input = dict(request.global_input_data or {})
    merged_input.update(per_skill_overrides or {})

    # 実行時のDeep Think判定（既存ロジックに合わせる）
    final_enable_deep_think = getattr(prompt, "enable_deep_think", True)
    if final_enable_deep_think is None:
        final_enable_deep_think = True

    # output_format
    output_format_value = request.output_format or "txt"

    # 最初のExecutionレコード作成
    execution = Execution(
        account_id=current_user.id,
        prompt_id=prompt.id,
        workflow_execution_id=wf_execution.id,
        workflow_skill_id=first_skill.id,
        step_order=first_skill.step_order,
        input_data=json.dumps(merged_input, ensure_ascii=False),
        status="pending",
        model_used=prompt.model_type,
        enable_deep_think=bool(final_enable_deep_think),
        output_format=output_format_value,
        executed_at=now_jst,
    )
    db.add(execution)
    
    # ワークフロー実行のステータスを更新
    wf_execution.status = "processing"
    db.commit()
    db.refresh(execution)

    # Celeryタスクキュー投入（最初のステップのみ）
    if not CELERY_AVAILABLE or not execute_prompt_task:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Celery/Redisサービスが利用できません。システム管理者に連絡してください。",
        )

    execute_prompt_task.delay(
        execution_id=execution.id,
        prompt_id=prompt.id,
        input_data=merged_input,
        output_format=output_format_value,
        attachments=None,
        enable_deep_think=final_enable_deep_think,
    )

    return ExecuteWorkflowResponse(
        workflow_id=request.workflow_id,
        workflow_execution_id=wf_execution.id,  # ワークフロー実行ID
        execution_ids=[execution.id],  # 最初のexecution_idのみ返す
    )


@router.post("/{execution_id}/cancel")
async def cancel_execution(
    execution_id: int,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user)
):
    """
    実行中のプロンプトをキャンセルする
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

        # Celeryタスクをキャンセル
        if CELERY_AVAILABLE and celery_app:
            try:
                # タスクIDを取得（CeleryタスクのIDは通常、タスク名と引数から生成される）
                # 実行中のタスクを探してキャンセル
                celery_app.control.revoke(execution_id, terminate=True)
                logger.info(f"Revoked Celery task for execution {execution_id}")
            except Exception as e:
                logger.warning(f"Failed to revoke Celery task for execution {execution_id}: {str(e)}")

        # Redis Streamにキャンセルイベントを送信
        if CELERY_AVAILABLE and publish_cancel:
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
    if not CELERY_AVAILABLE or not subscribe_stream:
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
