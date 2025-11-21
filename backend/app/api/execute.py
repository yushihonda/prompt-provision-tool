from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session
from app.database import get_db
from app.auth import get_current_user
from app.models import Account, Prompt, AccountPrompt, Execution
from app.schemas import ExecutePromptRequest, ExecutePromptResponse
from app.encryption import encryption_service
from app.services.openai_service import openai_service
from app.services.gemini_service import gemini_service
from app.config import settings
from app.utils.file_export import export_content, parse_attached_files
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


@router.post("", response_model=ExecutePromptResponse)
async def execute_prompt(
    request: ExecutePromptRequest,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user)
):
    """
    プロンプトを実行

    重要: プロンプトの内容はクライアントに送信されない
    サーバー側でプロンプトと入力データを結合してAI APIに送信
    """
    start_time = time.time()

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

    # プロンプトを復号化
    try:
        decrypted_prompt = encryption_service.decrypt(prompt.encrypted_content)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="プロンプトの復号化に失敗しました"
        )

    # 添付ファイルの処理
    attached_files = {}
    if request.attachments:
        for attachment in request.attachments:
            try:
                # Base64デコードを試みる（失敗した場合はテキストとして扱う）
                try:
                    file_content = base64.b64decode(attachment.content).decode('utf-8')
                except:
                    file_content = attachment.content
                attached_files[attachment.filename] = file_content
            except Exception as e:
                logger.warning(f"添付ファイルの処理に失敗: {attachment.filename} - {str(e)}")

    # プロンプトと入力データを結合
    final_prompt = replace_placeholders(decrypted_prompt, request.input_data)

    # 添付ファイルの内容をプロンプトに追加（オプション）
    if attached_files:
        attachment_section = "\n\n## 添付ファイル\n\n"
        for filename, content in attached_files.items():
            attachment_section += f"### {filename}\n\n{content}\n\n"
        final_prompt += attachment_section

    # デバッグ: 最終的なプロンプトをログ出力（設定で制御）
    if settings.LOG_FINAL_PROMPT:
        logger.info(f"Final prompt (first 200 chars): {final_prompt[:200]}...")

    # AIサービスの選択と実行
    try:
        # 許可モデル
        allowed_models = {
            # OpenAI
            "gpt-5-pro",  # 最上位モデル
            "gpt-5",
            "gpt-5.1",  # 最新モデル
            "gpt-4o-mini",  # コスパ最適化モデル
            # Gemini
            "gemini-3-pro-preview",  # Gemini 3.0 Pro（最新モデル）
            "gemini-2.5-pro",  # 無料枠: 1日100リクエストまで（有料版で制限なし）
            "gemini-2.5-flash",
            "gemini-2.0-flash",  # コスパ最適化モデル
        }
        # モデルのルーティング（OpenAI / Gemini 判定を拡張）
        model_str = prompt.model_type or ""
        if model_str not in allowed_models:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="サポートされていないモデルです（許可モデルのみ使用可能）"
            )
        is_openai = model_str in {"gpt-5-pro", "gpt-5", "gpt-5.1", "gpt-4o-mini"}
        is_gemini = model_str in {"gemini-3-pro-preview", "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash"}

        if is_openai:
            # OpenAI
            result = await openai_service.execute_prompt(
                prompt=final_prompt,
                model=model_str
            )
        elif is_gemini:
            # Gemini
            result = await gemini_service.execute_prompt(
                prompt=final_prompt,
                model=model_str
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="サポートされていないモデルです"
            )

        output = result["output"]
        model_used = result["model"]
        tokens_used = result["tokens"]
        status_result = "success"
        error_message = None

    except Exception as e:
        output = ""
        model_used = prompt.model_type
        tokens_used = 0
        status_result = "error"
        error_message = str(e)

    # 実行時間の計算（ミリ秒）
    execution_time = int((time.time() - start_time) * 1000)

    # 出力のサニタイズ（テンプレ類似を赤抜き）
    try:
        output = sanitize_output(
            output_text=output,
            template_text=decrypted_prompt,
            min_match_len=settings.SANITIZE_MIN_MATCH_LEN,
            similarity_threshold=settings.SANITIZE_SIMILARITY_THRESHOLD,
        )
    except Exception:
        # サニタイズに失敗しても処理は継続
        pass

    # 実行ログの保存
    execution = Execution(
        account_id=current_user.id,
        prompt_id=prompt.id,
        input_data=json.dumps(request.input_data, ensure_ascii=False),
        output_data=output,
        model_used=model_used,
        tokens_used=tokens_used,
        execution_time=execution_time,
        status=status_result,
        error_message=error_message
    )
    db.add(execution)
    db.commit()

    # エラーがあった場合は例外を投げる
    if status_result == "error":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"AI実行エラー: {error_message}"
        )

    # ファイル出力の処理
    file_output = None
    if request.output_format and request.output_format.lower() != "txt":
        try:
            file_bytes, filename = export_content(
                content=output,
                output_format=request.output_format,
                filename=f"output_{prompt.id}_{int(time.time())}"
            )
            # Base64エンコードして返す
            file_base64 = base64.b64encode(file_bytes).decode('utf-8')
            file_output = {
                "filename": filename,
                "content": file_base64,
                "format": request.output_format.lower(),
                "size": len(file_bytes)
            }
        except Exception as e:
            logger.error(f"ファイル出力エラー: {str(e)}")
            # ファイル出力に失敗しても処理は継続（テキスト出力を返す）

    return {
        "output": output,
        "model_used": model_used,
        "tokens_used": tokens_used,
        "execution_time": execution_time,
        "status": status_result,
        "file_output": file_output
    }
