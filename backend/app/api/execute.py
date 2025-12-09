from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.auth import get_current_user
from app.models import Account, Prompt, AccountPrompt, Execution
from app.schemas import ExecutePromptRequest, ExecutePromptResponse
from app.encryption import encryption_service
from app.services.openai_service import openai_service
from app.services.gemini_service import gemini_service
from app.config import settings
from app.utils.file_export import export_content, parse_attached_files
from datetime import datetime, timezone, timedelta
import difflib
import json
import time
import logging
import re
import base64

logger = logging.getLogger(__name__)

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

        # 適切なContent-Typeを設定
        content_types = {
            "csv": "text/csv",
            "pdf": "application/pdf",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "md": "text/markdown",
            "txt": "text/plain"
        }
        content_type = content_types.get(output_format.lower(), "application/octet-stream")

        return Response(
            content=file_bytes,
            media_type=content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
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


def replace_placeholders(prompt_template: str, input_data: dict) -> str:
    """
    プロンプトテンプレート内のプレースホルダーを入力データで置き換える

    プレースホルダーの形式: {variable_name}
    オプショナルフィールドが空の場合、その行を削除する

    Args:
        prompt_template: プロンプトテンプレート
        input_data: 入力データ

    Returns:
        置き換え後のプロンプト
    """
    result = prompt_template
    for key, value in input_data.items():
        placeholder = f"{{{key}}}"
        # 値がNone、空文字列、または空白のみの場合は空文字列に置換
        if value is None or (isinstance(value, str) and value.strip() == ""):
            # オプショナルフィールドの行全体を削除（行末まで）
            # プレースホルダーを含む行を削除（オプション表記がある場合）
            pattern = rf".*{re.escape(placeholder)}.*\n?"
            result = re.sub(pattern, "", result)
        else:
            result = result.replace(placeholder, str(value))

    # 連続する空行を1つにまとめる
    result = re.sub(r'\n\s*\n\s*\n+', '\n\n', result)
    return result


def sanitize_output(
    output_text: str,
    template_text: str,
    min_match_len: int,
    similarity_threshold: float
) -> str:
    """
    出力がテンプレート本文に過度に類似/一致する場合に赤抜きする。
    - 長い連続一致(>= min_match_len)がある場合: その部分を[REDACTED]に置換
    - 全体類似度が高い場合(ratio>=threshold): 最長一致部分を[REDACTED]
    """
    if not output_text or not template_text:
        return output_text

    matcher = difflib.SequenceMatcher(None, output_text, template_text)
    ratio = matcher.quick_ratio()
    if ratio < similarity_threshold:
        ratio = matcher.ratio()

    longest = matcher.find_longest_match(0, len(output_text), 0, len(template_text))

    should_redact = longest.size >= min_match_len or ratio >= similarity_threshold
    if not should_redact:
        return output_text

    # 一度だけ最長一致を赤抜き（必要なら将来複数回に拡張）
    start = longest.a
    end = longest.a + longest.size
    redacted = output_text[:start] + "[REDACTED]" + output_text[end:]
    return redacted


from fastapi import BackgroundTasks
import asyncio

# 実行中のタスクを管理するグローバル辞書
_running_tasks: dict[int, asyncio.Task] = {}

@router.post("", response_model=ExecutePromptResponse)
async def execute_prompt(
    request: ExecutePromptRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user)
):
    """
    プロンプトを実行（バックグラウンド処理）

    重要: プロンプトの内容はクライアントに送信されない
    サーバー側でプロンプトと入力データを結合してAI APIに送信
    """
    # デバッグ: 受信したリクエスト（本番は入力詳細を出力しない）
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
    
    execution = Execution(
        account_id=current_user.id,
        prompt_id=prompt.id,
        input_data=json.dumps(request.input_data, ensure_ascii=False),
        status="pending",
        model_used=prompt.model_type, # 初期値として設定
        enable_deep_think=bool(final_enable_deep_think),  # 実行時点のDeep Think状態を保存
        executed_at=now_jst
    )
    db.add(execution)
    db.commit()
    db.refresh(execution)

    # バックグラウンドタスクの追加（asyncio.Taskとして管理）
    from app.services.execution_service import process_execution_background

    # タスクを作成して実行
    task = asyncio.create_task(
        process_execution_background(
            execution_id=execution.id,
            prompt_id=prompt.id,
            input_data=request.input_data,
            output_format=request.output_format,
            attachments=request.attachments,
            enable_deep_think=request.enable_deep_think
        )
    )

    # タスクを辞書に保存（キャンセル時に使用）
    _running_tasks[execution.id] = task

    # タスク完了時に辞書から削除するコールバック
    def remove_task(task_id: int):
        _running_tasks.pop(task_id, None)

    task.add_done_callback(lambda _: remove_task(execution.id))

    return {
        "execution_id": execution.id,
        "status": "pending"
    }


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

        # 実行中のタスクがあればキャンセル
        if execution_id in _running_tasks:
            task = _running_tasks[execution_id]
            if not task.done():
                task.cancel()
                logger.info(f"Cancelled asyncio task for execution {execution_id}")
                try:
                    await task
                except asyncio.CancelledError:
                    logger.info(f"Task for execution {execution_id} was cancelled")
                except Exception as e:
                    logger.error(f"Error while cancelling task for execution {execution_id}: {e}")

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
