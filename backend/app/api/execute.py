from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.auth import get_current_user
from app.models import Account, Prompt, AccountPrompt, Execution
from app.schemas import ExecutePromptRequest, ExecutePromptResponse
from app.encryption import encryption_service
from app.services.openai_service import openai_service
from app.services.gemini_service import gemini_service
import json
import time
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/execute", tags=["実行"])


def replace_placeholders(prompt_template: str, input_data: dict) -> str:
    """
    プロンプトテンプレート内のプレースホルダーを入力データで置き換える
    
    プレースホルダーの形式: {variable_name}
    
    Args:
        prompt_template: プロンプトテンプレート
        input_data: 入力データ
        
    Returns:
        置き換え後のプロンプト
    """
    result = prompt_template
    for key, value in input_data.items():
        placeholder = f"{{{key}}}"
        result = result.replace(placeholder, str(value))
    return result


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
    
    # デバッグ: 受信したリクエストデータをログ出力
    logger.info(f"Execute request - prompt_id: {request.prompt_id}, input_data: {request.input_data}")
    
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
    
    # プロンプトと入力データを結合
    final_prompt = replace_placeholders(decrypted_prompt, request.input_data)
    
    # デバッグ: 最終的なプロンプトをログ出力
    logger.info(f"Final prompt (first 200 chars): {final_prompt[:200]}...")
    
    # AIサービスの選択と実行
    try:
        # model_typeは文字列なので、値で比較
        if prompt.model_type in ["gpt-4", "gpt-4-turbo-preview", "gpt-5-pro"]:
            # OpenAI
            result = await openai_service.execute_prompt(
                prompt=final_prompt,
                model=prompt.model_type
            )
        elif prompt.model_type in ["gemini-pro", "gemini-2.5-pro", "gemini-2.5-pro-deep-think"]:
            # Gemini
            result = await gemini_service.execute_prompt(
                prompt=final_prompt,
                model=prompt.model_type
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
    
    return {
        "output": output,
        "model_used": model_used,
        "tokens_used": tokens_used,
        "execution_time": execution_time,
        "status": status_result
    }

