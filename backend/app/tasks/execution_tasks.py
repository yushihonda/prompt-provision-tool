"""
プロンプト実行Celeryタスク
"""
import time
import json
import base64
import logging
import asyncio
from typing import Optional
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from app.celery_app import celery_app
from app.models import Execution, Prompt, Account, APIConfig, AccountType, WorkflowExecution, WorkflowSkill, Workflow
from app.encryption import encryption_service
from app.services.openai_service import openai_service, OpenAIService
from app.services.gemini_service import gemini_service, GeminiService
from app.services.redis_service import (
    publish_chunk,
    publish_complete,
    publish_error,
    publish_cancel,
    is_cancelled
)
from app.config import settings
from app.utils.pricing import calculate_token_cost
from app.utils.prompt_utils import replace_placeholders, sanitize_output
from app.services.execution_service import save_cancelled_execution
from app.database import SessionLocal

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    time_limit=3900,  # 65分
    soft_time_limit=3600,  # 60分
    max_retries=3,
    default_retry_delay=60
)
def execute_prompt_task(
    self,
    execution_id: int,
    prompt_id: int,
    input_data: dict,
    output_format: str = "txt",
    attachments: list = None,
    enable_deep_think: Optional[bool] = None
):
    """
    プロンプト実行タスク（ストリーミング対応）
    
    Args:
        execution_id: 実行ID
        prompt_id: プロンプトID
        input_data: 入力データ
        output_format: 出力形式
        attachments: 添付ファイル
        enable_deep_think: Deep Think有効化フラグ
    """
    db = SessionLocal()
    execution = None
    start_time = None
    
    try:
        # 実行ログの取得
        execution = db.query(Execution).filter(Execution.id == execution_id).first()
        if not execution:
            logger.error(f"Execution not found: {execution_id}")
            return

        # キャンセルチェック（開始時）
        if execution.status == "cancelled":
            logger.info(f"Execution {execution_id} already cancelled")
            save_cancelled_execution(execution, execution_id, db, start_time=None)
            return

        # ステータスをprocessingに更新（キャンセルチェック後）
        db.refresh(execution)
        if execution.status == "cancelled":
            logger.info(f"Execution {execution_id} cancelled before processing")
            save_cancelled_execution(execution, execution_id, db, start_time=None)
            return

        execution.status = "processing"
        db.commit()
        db.refresh(execution)

        # プロンプトの取得
        prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
        if not prompt:
            execution.status = "error"
            execution.error_message = "プロンプトが見つかりません"
            db.commit()
            publish_error(execution_id, "プロンプトが見つかりません")
            return

        # アカウントのAPI設定を取得（子アカウントのみ）
        account = db.query(Account).filter(Account.id == execution.account_id).first()
        api_config = None
        if account and str(account.account_type) == AccountType.CHILD:
            api_config = db.query(APIConfig).filter(APIConfig.account_id == account.id).first()

        # ユーザーごとのAPIキーを取得
        openai_api_key = None
        gemini_api_key = None
        if api_config and api_config.is_enabled:
            openai_api_key = api_config.openai_api_key if api_config.openai_api_key else None
            gemini_api_key = api_config.gemini_api_key if api_config.gemini_api_key else None

        # ユーザーごとのAPIキーを使用してサービスを初期化
        user_openai_service = OpenAIService(api_key=openai_api_key) if openai_api_key else openai_service
        user_gemini_service = GeminiService(api_key=gemini_api_key) if gemini_api_key else gemini_service

        start_time = time.time()

        # プロンプトを復号化（サーバー側のみ）
        try:
            decrypted_prompt = encryption_service.decrypt(prompt.encrypted_content)
        except Exception as e:
            execution.status = "error"
            execution.error_message = "プロンプトの復号化に失敗しました"
            db.commit()
            publish_error(execution_id, "プロンプトの復号化に失敗しました")
            return

        # 添付ファイルの処理
        attached_files = {}
        if attachments:
            for attachment in attachments:
                try:
                    try:
                        file_content = base64.b64decode(attachment.get("content", "")).decode('utf-8')
                    except:
                        file_content = attachment.get("content", "")
                    attached_files[attachment.get("filename", "")] = file_content
                except Exception as e:
                    logger.warning(f"添付ファイルの処理に失敗: {attachment.get('filename', 'unknown')} - {str(e)}")

        # プロンプトと入力データを結合
        final_prompt = replace_placeholders(decrypted_prompt, input_data)

        # 添付ファイルの内容をプロンプトに追加
        if attached_files:
            attachment_section = "\n\n## 添付ファイル\n\n"
            for filename, content in attached_files.items():
                attachment_section += f"### {filename}\n\n{content}\n\n"
            final_prompt += attachment_section

        # デバッグ: 最終的なプロンプトをログ出力（設定で制御）
        if settings.LOG_FINAL_PROMPT:
            logger.info(f"Final prompt (first 200 chars): {final_prompt[:200]}...")

        # キャンセルチェック（API呼び出し前）
        db.refresh(execution)
        if execution.status == "cancelled":
            logger.info(f"Execution {execution_id} cancelled before AI service call")
            save_cancelled_execution(execution, execution_id, db, start_time=start_time)
            publish_cancel(execution_id)
            return

        # AIサービスの選択と実行（ストリーミング対応）
        try:
            # 許可モデルとサービス判定
            openai_models = {
                "gpt-5-pro",
                "gpt-5",
                "gpt-5.1",
                "gpt-5.1-thinking",
                "gpt-5.2",
                "gpt-5.2-pro",
                "gpt-5.2-thinking",
                "gpt-4o",
                "gpt-4o-mini",
            }
            gemini_models = {
                "gemini-3-pro-preview",
                "gemini-3-pro-preview-deep-think",
                "gemini-2.5-pro",
                "gemini-2.5-pro-deep-think",
                "gemini-2.5-flash",
                "gemini-2.0-flash",
            }

            model_str = prompt.model_type or ""
            is_openai = model_str in openai_models
            is_gemini = model_str in gemini_models

            # 非同期処理を実行（asyncio.run()を使用）
            async def run_streaming_execution(start_time_param):
                """非同期ストリーミング実行"""
                import time as time_module  # 明示的にインポートしてローカル変数の問題を回避
                output_chunks = []
                long_running_warning_sent = False  # 長時間実行警告の送信フラグ
                LONG_RUNNING_THRESHOLD = 1800  # 30分（秒）
                
                if is_openai:
                    # キャンセルチェック
                    if is_cancelled(execution_id):
                        raise asyncio.CancelledError("Execution was cancelled")
                    
                    # ツール設定の取得（プロンプトから）
                    enable_code_interpreter = getattr(prompt, 'enable_code_interpreter', False)
                    enable_file_search = getattr(prompt, 'enable_file_search', False)
                    
                    # 推論モデルかどうかを判定
                    is_reasoning_model = user_openai_service._is_reasoning_model(model_str)
                    logger.info(f"Execution {execution_id}: Model {model_str} is_reasoning_model={is_reasoning_model}")
                    
                    # OpenAIストリーミング実行
                    if is_reasoning_model:
                        # 推論モデル（gpt-5.2-proなど）の場合は非ストリーミングにフォールバックされるため、
                        # 結果をチャンクに分割して送信する
                        logger.info(f"Execution {execution_id}: Processing reasoning model (non-streaming fallback)")
                        all_output = ""
                        chunk_count = 0
                        async for chunk in user_openai_service.execute_streaming(
                            prompt=final_prompt,
                            model=model_str,
                            enable_code_interpreter=enable_code_interpreter,
                            enable_file_search=enable_file_search
                        ):
                            # キャンセルチェック
                            if is_cancelled(execution_id):
                                publish_cancel(execution_id)
                                raise asyncio.CancelledError("Execution was cancelled")
                            
                            # 長時間実行警告チェック（30分以上）
                            if not long_running_warning_sent:
                                elapsed_time = time_module.time() - start_time_param
                                if elapsed_time >= LONG_RUNNING_THRESHOLD:
                                    logger.warning(f"Execution {execution_id}: 長時間実行中（{elapsed_time/60:.1f}分経過）。通常の実行時間を超過しています。")
                                    long_running_warning_sent = True
                            
                            # チャンクを蓄積
                            all_output += chunk
                            output_chunks.append(chunk)
                            chunk_count += 1
                            logger.info(f"Execution {execution_id}: Received chunk {chunk_count}, size: {len(chunk)}, total size: {len(all_output)}")
                        
                        # すべてのチャンクを受信した後、1000文字ごとに分割して送信
                        logger.info(f"Execution {execution_id}: All chunks received, total size: {len(all_output)}, splitting into 1000-char chunks")
                        chunk_size = 1000
                        for i in range(0, len(all_output), chunk_size):
                            chunk_to_send = all_output[i:i + chunk_size]
                            logger.info(f"Execution {execution_id}: Publishing chunk {i // chunk_size + 1} (size: {len(chunk_to_send)})")
                            publish_chunk(execution_id, chunk_to_send)
                        
                        # 最後のチャンク送信後に少し待機してから完了イベントを送信する
                        # これにより、フロントエンドが最後のチャンクを受信してから完了イベントを受信できる
                        if all_output:
                            await asyncio.sleep(0.1)  # 100ms待機
                            logger.info(f"Execution {execution_id}: All chunks published, waiting before complete event")
                        else:
                            logger.warning(f"Execution {execution_id}: No output to publish (chunk_count: {chunk_count})")
                    else:
                        # 通常のストリーミングモデル（gpt-4oなど）の場合は、チャンクをそのまま送信
                        async for chunk in user_openai_service.execute_streaming(
                            prompt=final_prompt,
                            model=model_str,
                            enable_code_interpreter=enable_code_interpreter,
                            enable_file_search=enable_file_search
                        ):
                            # キャンセルチェック
                            if is_cancelled(execution_id):
                                publish_cancel(execution_id)
                                raise asyncio.CancelledError("Execution was cancelled")
                            
                            # 長時間実行警告チェック（30分以上）
                            if not long_running_warning_sent:
                                elapsed_time = time_module.time() - start_time_param
                                if elapsed_time >= LONG_RUNNING_THRESHOLD:
                                    logger.warning(f"Execution {execution_id}: 長時間実行中（{elapsed_time/60:.1f}分経過）。通常の実行時間を超過しています。")
                                    long_running_warning_sent = True
                            
                            # チャンクをそのまま送信（リアルタイム表示）
                            publish_chunk(execution_id, chunk)
                            output_chunks.append(chunk)
                        
                        # 通常のストリーミングモデルでは、最後のチャンク送信後に少し待機
                        # これにより、フロントエンドが最後のチャンクを受信してから完了イベントを受信できる
                        await asyncio.sleep(0.1)  # 100ms待機
                    
                    # 結果を結合
                    output = "".join(output_chunks)
                    model_used = model_str
                    
                    # トークン数を計算（tiktokenライブラリを使用）
                    try:
                        import tiktoken
                        # モデルに応じたエンコーダーを取得
                        try:
                            encoding = tiktoken.encoding_for_model(model_str)
                        except KeyError:
                            # モデルが見つからない場合はcl100k_baseを使用（GPT-4など）
                            encoding = tiktoken.get_encoding("cl100k_base")
                        
                        # プロンプトと出力のトークン数を計算
                        prompt_tokens = len(encoding.encode(final_prompt))
                        output_tokens = len(encoding.encode(output))
                        tokens_used = prompt_tokens + output_tokens
                        
                        logger.info(f"Execution {execution_id}: Calculated tokens using tiktoken (prompt: {prompt_tokens}, output: {output_tokens}, total: {tokens_used})")
                    except ImportError:
                        logger.warning("tiktokenライブラリがインストールされていません。文字数から概算します。")
                        # フォールバック: 文字数から概算（1トークン ≈ 4文字）
                        tokens_used = len(final_prompt) // 4 + len(output) // 4
                    except Exception as e:
                        logger.warning(f"トークン数の計算に失敗: {str(e)}。文字数から概算します。")
                        # フォールバック: 文字数から概算
                        tokens_used = len(final_prompt) // 4 + len(output) // 4
                    
                elif is_gemini:
                    # キャンセルチェック
                    if is_cancelled(execution_id):
                        raise asyncio.CancelledError("Execution was cancelled")
                    
                    # Deep Think設定の優先順位
                    if enable_deep_think is not None:
                        deep_think_enabled = enable_deep_think
                    else:
                        deep_think_enabled = getattr(prompt, 'enable_deep_think', True)
                    
                    # ツール設定の取得（プロンプトから）
                    enable_web_search = getattr(prompt, 'enable_web_search', True)  # デフォルトはTrue（google_search）
                    enable_code_interpreter = getattr(prompt, 'enable_code_interpreter', False)
                    enable_file_search = getattr(prompt, 'enable_file_search', False)
                    
                    # Geminiストリーミング実行
                    # Geminiは通常ストリーミングをサポートしているが、大きなチャンクが来る可能性があるため、
                    # チャンクをそのまま送信する（リアルタイム表示）
                    async for chunk in user_gemini_service.execute_streaming(
                        prompt=final_prompt,
                        model=model_str,
                        enable_deep_think=deep_think_enabled,
                        enable_web_search=enable_web_search,
                        enable_code_interpreter=enable_code_interpreter,
                        enable_file_search=enable_file_search
                    ):
                        # キャンセルチェック
                        if is_cancelled(execution_id):
                            publish_cancel(execution_id)
                            raise asyncio.CancelledError("Execution was cancelled")
                        
                        # 長時間実行警告チェック（30分以上）
                        if not long_running_warning_sent:
                            elapsed_time = time_module.time() - start_time_param
                            if elapsed_time >= LONG_RUNNING_THRESHOLD:
                                logger.warning(f"Execution {execution_id}: 長時間実行中（{elapsed_time/60:.1f}分経過）。通常の実行時間を超過しています。")
                                long_running_warning_sent = True
                        
                        # チャンクをそのまま送信（リアルタイム表示）
                        publish_chunk(execution_id, chunk)
                        output_chunks.append(chunk)
                    
                    # 最後のチャンク送信後に少し待機してから完了イベントを送信する
                    # これにより、フロントエンドが最後のチャンクを受信してから完了イベントを受信できる
                    await asyncio.sleep(0.1)  # 100ms待機
                    
                    # 結果を結合
                    output = "".join(output_chunks)
                    model_used = model_str
                    
                    # トークン数を計算
                    # 注意: GeminiのストリーミングAPIでは、最後のチャンクにusage情報が含まれていない可能性がある
                    # そのため、非ストリーミングAPIでトークン数を取得する（追加のAPI呼び出しになるが、正確な値が必要）
                    # ただし、追加のAPI呼び出しはコストがかかるため、まずは文字数から概算を試みる
                    try:
                        # 文字数から概算（1トークン ≈ 4文字、日本語の場合は約2文字）
                        # より正確な方法: 非ストリーミングAPIでトークン数を取得（追加のAPI呼び出しになる）
                        # 暫定的に、文字数から概算する方法を使用
                        # 日本語と英語が混在する場合の概算: 1トークン ≈ 3文字（中間値）
                        prompt_tokens_estimated = len(final_prompt) // 3
                        output_tokens_estimated = len(output) // 3
                        tokens_used = prompt_tokens_estimated + output_tokens_estimated
                        
                        logger.info(f"Execution {execution_id}: Estimated tokens for Gemini using character count (prompt: {prompt_tokens_estimated}, output: {output_tokens_estimated}, total: {tokens_used})")
                        
                        # より正確な方法として、非ストリーミングAPIでトークン数を取得するオプション
                        # コメントアウト: 追加のAPI呼び出しになるため、コストがかかる
                        # 必要に応じて有効化可能
                        # result = await user_gemini_service.execute_prompt(
                        #     prompt=final_prompt,
                        #     model=model_str,
                        #     temperature=None,
                        #     max_tokens=1
                        # )
                        # if result.get("tokens", 0) > 0:
                        #     # プロンプトトークン数は取得できたが、出力トークン数は概算
                        #     prompt_tokens = result.get("tokens", 0)
                        #     output_tokens_estimated = len(output) // 3
                        #     tokens_used = prompt_tokens + output_tokens_estimated
                    except Exception as e:
                        logger.warning(f"トークン数の計算に失敗: {str(e)}")
                        # フォールバック: 文字数から概算
                        tokens_used = len(final_prompt) // 3 + len(output) // 3
                    
                else:
                    raise ValueError("サポートされていないモデルです")
                
                return {
                    "output": output,
                    "model": model_used,
                    "tokens": tokens_used
                }
            
            # 非同期処理を実行
            result = asyncio.run(run_streaming_execution(start_time))
            
            output = result["output"]
            model_used = result["model"]
            tokens_used = result["tokens"]
            status_result = "success"
            error_message = None

        except asyncio.CancelledError:
            # キャンセルされた場合
            db.refresh(execution)
            save_cancelled_execution(execution, execution_id, db, start_time=start_time)
            publish_cancel(execution_id)
            return
        except Exception as e:
            # エラーが発生した場合
            output = ""
            model_used = prompt.model_type
            tokens_used = 0
            status_result = "error"
            error_message = str(e)
            logger.error(f"Execution {execution_id} error: {str(e)}")
            publish_error(execution_id, str(e))

        # キャンセルチェック（結果処理前）
        db.refresh(execution)
        if execution.status == "cancelled":
            logger.info(f"Execution {execution_id} was cancelled before result processing")
            save_cancelled_execution(execution, execution_id, db, start_time=start_time)
            publish_cancel(execution_id)
            return

        # 実行時間の計算（ミリ秒）
        execution_time = int((time.time() - start_time) * 1000)

        # 出力のサニタイズ（テンプレ類似を赤抜き）
        if status_result == "success":
            try:
                output = sanitize_output(
                    output_text=output,
                    template_text=decrypted_prompt,
                    min_match_len=settings.SANITIZE_MIN_MATCH_LEN,
                    similarity_threshold=settings.SANITIZE_SIMILARITY_THRESHOLD,
                )
            except Exception:
                pass

        # キャンセルチェック（結果保存前）
        db.refresh(execution)
        if execution.status == "cancelled":
            logger.info(f"Execution {execution_id} was cancelled before result save")
            save_cancelled_execution(execution, execution_id, db, start_time=start_time)
            publish_cancel(execution_id)
            return

        # 実行ログの更新（キャンセルされていない場合のみ）
        execution.output_data = output
        execution.model_used = model_used
        execution.tokens_used = tokens_used
        
        # 料金を計算して保存
        if tokens_used and tokens_used > 0 and model_used:
            execution.cost = calculate_token_cost(model_used, tokens_used)
            logger.info(f"Execution {execution_id}: Calculated cost ${execution.cost:.6f} for model {model_used} with {tokens_used} tokens")
        else:
            execution.cost = 0.0
            logger.info(f"Execution {execution_id}: Cost set to 0.0 (tokens_used={tokens_used}, model_used={model_used})")
        
        execution.execution_time = execution_time
        execution.status = status_result
        execution.error_message = error_message

        # アカウントの総トークン数、総料金、実行回数を更新
        if status_result in ["success", "error", "cancelled"]:
            from datetime import datetime, timezone, timedelta
            account = db.query(Account).filter(Account.id == execution.account_id).first()
            if account:
                # 月が変わったかチェック（今月のデータをリセット）
                jst = timezone(timedelta(hours=9))
                current_month = datetime.now(jst).replace(day=1, hour=0, minute=0, second=0, microsecond=0)

                should_reset = False
                if account.last_month_reset is None:
                    should_reset = True
                else:
                    if account.last_month_reset.tzinfo is None:
                        last_reset_aware = account.last_month_reset.replace(tzinfo=jst)
                    else:
                        last_reset_aware = account.last_month_reset

                    if last_reset_aware < current_month:
                        should_reset = True

                if should_reset:
                    logger.info(f"Account {account.id}: Month changed, resetting monthly totals")
                    account.tokens_this_month = 0
                    account.cost_this_month = 0.0
                    account.executions_this_month = 0
                    account.last_month_reset = current_month

                # 実行回数をインクリメント
                account.executions_this_month = (account.executions_this_month or 0) + 1
                account.total_executions = (account.total_executions or 0) + 1

                # トークン数と料金は成功時のみ更新
                if status_result == "success" and tokens_used and tokens_used > 0:
                    old_total_cost = float(account.total_cost or 0.0)
                    old_cost_this_month = float(account.cost_this_month or 0.0)
                    account.total_tokens = (account.total_tokens or 0) + tokens_used
                    account.total_cost = old_total_cost + float(execution.cost or 0.0)
                    account.tokens_this_month = (account.tokens_this_month or 0) + tokens_used
                    account.cost_this_month = old_cost_this_month + float(execution.cost or 0.0)

                    logger.info(f"Updated account {account.id} totals: tokens={account.total_tokens}, cost=${account.total_cost:.6f}")

        db.commit()

        # 完了イベントをRedis Streamに送信
        # 最後のチャンク送信後に既に待機しているため、ここでは追加の待機は不要
        if status_result == "success":
            logger.info(f"Publishing complete event for execution {execution_id}")
            publish_complete(execution_id, {
                "model_used": model_used,
                "tokens_used": tokens_used,
                "execution_time": execution_time,
                "cost": float(execution.cost or 0.0)
            })
            logger.info(f"Complete event published for execution {execution_id}")
        else:
            logger.info(f"Publishing error event for execution {execution_id}")
            publish_error(execution_id, error_message or "実行エラーが発生しました")
            logger.info(f"Error event published for execution {execution_id}")

        logger.info(f"Execution {execution_id} completed with status: {status_result}")

        # ワークフロー実行の場合、次のステップを起動
        if execution.workflow_execution_id and status_result == "success":
            # リーダーステップ（workflow_skill_idがNone）の場合は、ワークフロー全体を完了としてマーク
            if execution.workflow_skill_id is None:
                try:
                    db.refresh(execution)
                    wf_exec = db.query(WorkflowExecution).filter(
                        WorkflowExecution.id == execution.workflow_execution_id
                    ).first()
                    if wf_exec:
                        wf_exec.status = "success"
                        wf_exec.completed_at = datetime.now(timezone(timedelta(hours=9)))
                        db.commit()
                        logger.info(f"WorkflowExecution {execution.workflow_execution_id} completed (leader step finished)")
                except Exception as wf_error:
                    logger.error(f"Failed to mark workflow execution as completed: {str(wf_error)}")
            else:
                # 通常のステップの場合は次のステップを起動
                try:
                    continue_workflow_execution.delay(execution.workflow_execution_id, execution.step_order)
                except Exception as wf_error:
                    logger.error(f"Failed to continue workflow execution: {str(wf_error)}")

    except Exception as e:
        logger.error(f"Task execution error: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        
        # リトライ可能なエラーかどうかを判定
        error_type = type(e).__name__
        error_msg = str(e).lower()
        
        # リトライ不可能なエラー（即座にエラーとして処理）
        non_retryable_errors = (
            ValueError,  # プロンプトが見つからない、モデルが存在しないなど
            asyncio.CancelledError,  # キャンセルされたエラー
        )
        
        # リトライ不可能なエラーメッセージのパターン
        non_retryable_patterns = [
            "プロンプトが見つかりません",
            "モデル.*は存在しない",
            "model_not_found",
            "does not exist",
            "authentication",
            "認証",
            "invalid api key",
        ]
        
        is_non_retryable = (
            isinstance(e, non_retryable_errors) or
            any(pattern in error_msg for pattern in non_retryable_patterns)
        )
        
        # リトライ可能なエラーの判定
        # OpenAI: APITimeoutError, APIError（認証エラーを除く）
        # Gemini: TimeoutError, DeadlineExceeded, ServiceUnavailable, ResourceExhausted
        # 一般的なネットワークエラー: ConnectionError, TimeoutError
        is_retryable = False
        if not is_non_retryable:
            # OpenAIエラー
            try:
                from openai import APITimeoutError, APIError
                if isinstance(e, (APITimeoutError, APIError)):
                    is_retryable = True
            except ImportError:
                pass
            
            # Geminiエラー
            try:
                from google.api_core import exceptions as google_exceptions
                if isinstance(e, (
                    asyncio.TimeoutError,
                    google_exceptions.DeadlineExceeded,
                    google_exceptions.ServiceUnavailable,
                    google_exceptions.ResourceExhausted
                )):
                    is_retryable = True
            except (ImportError, AttributeError):
                # google.api_coreが利用できない場合、タイムアウトエラーのみチェック
                if isinstance(e, asyncio.TimeoutError):
                    is_retryable = True
            
            # 一般的なネットワークエラー
            if isinstance(e, (ConnectionError, TimeoutError)):
                is_retryable = True
            
            # エラーメッセージから判定（タイムアウト、レート制限など）
            retryable_patterns = [
                "timeout",
                "timed out",
                "deadline",
                "rate limit",
                "rate_limit",
                "service unavailable",
                "resource exhausted",
                "connection",
                "network",
            ]
            if any(pattern in error_msg for pattern in retryable_patterns):
                is_retryable = True
        
        # リトライ処理
        if is_retryable and self.request.retries < self.max_retries:
            retry_count = self.request.retries + 1
            logger.warning(
                f"Execution {execution_id}: リトライ可能なエラーを検出。"
                f"リトライ {retry_count}/{self.max_retries} を実行します。"
                f"エラータイプ: {error_type}, エラー: {str(e)[:100]}"
            )
            try:
                # 60秒後にリトライ
                raise self.retry(countdown=60, exc=e)
            except Exception as retry_error:
                # retry()が例外を再発生させた場合、そのまま伝播
                raise retry_error
        
        # リトライ不可能なエラー、または最大リトライ回数に達した場合
        if execution:
            try:
                db.refresh(execution)
                execution.status = "error"
                if self.request.retries >= self.max_retries:
                    execution.error_message = f"システムエラー（{self.max_retries}回リトライ後も失敗）: {str(e)}"
                else:
                    execution.error_message = f"システムエラー: {str(e)}"
                db.commit()
                publish_error(execution_id, execution.error_message)
            except Exception as db_error:
                logger.error(f"Failed to update execution status: {str(db_error)}")
    finally:
        db.close()


@celery_app.task(
    bind=True,
    time_limit=300,  # 5分
    soft_time_limit=240,  # 4分
    max_retries=3,
    default_retry_delay=30
)
def continue_workflow_execution(
    self,
    workflow_execution_id: int,
    completed_step_order: int
):
    """
    ワークフロー実行の次のステップを起動
    
    Args:
        workflow_execution_id: ワークフロー実行ID
        completed_step_order: 完了したステップの順序
    """
    db = SessionLocal()
    try:
        # ワークフロー実行を取得
        wf_exec = db.query(WorkflowExecution).filter(
            WorkflowExecution.id == workflow_execution_id
        ).first()
        
        if not wf_exec:
            logger.error(f"WorkflowExecution {workflow_execution_id} not found")
            return
        
        # キャンセルチェック
        if wf_exec.status == "cancelled":
            logger.info(f"WorkflowExecution {workflow_execution_id} is cancelled")
            return
        
        # 次のステップを取得
        next_step_order = completed_step_order + 1
        wf_skill = (
            db.query(WorkflowSkill)
            .join(Prompt, Prompt.id == WorkflowSkill.prompt_id)
            .filter(
                WorkflowSkill.workflow_id == wf_exec.workflow_id,
                WorkflowSkill.step_order == next_step_order,
                Prompt.deleted_at.is_(None),
                Prompt.is_active == True,  # noqa: E712
            )
            .first()
        )
        
        # 前ステップの出力を取得
        previous_execution = (
            db.query(Execution)
            .filter(
                Execution.workflow_execution_id == workflow_execution_id,
                Execution.step_order == completed_step_order,
                Execution.status == "success"
            )
            .first()
        )

        # グローバル入力データを取得
        global_input = {}
        if wf_exec.global_input_data:
            try:
                global_input = json.loads(wf_exec.global_input_data) if isinstance(wf_exec.global_input_data, str) else wf_exec.global_input_data
            except (json.JSONDecodeError, TypeError):
                global_input = {}
        
        # 前ステップの出力をマージ（前ステップの出力を"previous_output"として追加）
        merged_input = dict(global_input)
        if previous_execution and previous_execution.output_data:
            try:
                previous_output = json.loads(previous_execution.output_data) if isinstance(previous_execution.output_data, str) else previous_execution.output_data
                merged_input["previous_output"] = previous_output
                merged_input["previous_step_result"] = previous_output  # 互換性のため
            except (json.JSONDecodeError, TypeError):
                # 出力がJSONでない場合は文字列として追加
                previous_output = previous_execution.output_data
                merged_input["previous_output"] = previous_output
                merged_input["previous_step_result"] = previous_output

            # 既存のプロンプトテンプレートとの互換性のためのエイリアス
            # 例: 解析ステップで {{research_data}} / {{analysis_result}} を参照しているケース
            try:
                if "research_data" not in merged_input:
                    merged_input["research_data"] = previous_output
                if "analysis_result" not in merged_input:
                    merged_input["analysis_result"] = previous_output
            except Exception:
                # previous_output がシリアライズ不可な型でもワークフロー自体は継続させる
                pass

        # これまでの全ステップ結果もまとめて渡す
        # リーダー用の最終ステップなどで、サブエージェントの出力一覧を精査できるようにする
        all_step_results = []
        try:
            # WorkflowExecution.executions は step_order 順で並ぶリレーション
            for exec_obj in wf_exec.executions:
                if exec_obj.status != "success":
                    continue

                raw_output = exec_obj.output_data
                parsed_output = raw_output
                if raw_output:
                    try:
                        parsed_output = json.loads(raw_output) if isinstance(raw_output, str) else raw_output
                    except (json.JSONDecodeError, TypeError):
                        # JSONでなければそのまま文字列として保持
                        parsed_output = raw_output

                all_step_results.append({
                    "step_order": exec_obj.step_order,
                    "workflow_skill_id": exec_obj.workflow_skill_id,
                    "prompt_id": exec_obj.prompt_id,
                    "output": parsed_output,
                })
        except Exception as hist_err:
            logger.warning(f"Failed to build all_step_results for workflow_execution {workflow_execution_id}: {str(hist_err)}")

        # ワークフロープロンプトからは
        # - previous_output / previous_step_result: 直前ステップの結果
        # - all_step_results: これまでの全成功ステップの結果一覧
        # - global_input_data: ワークフロー全体の入力データ（互換性用）
        # を利用できる
        merged_input["all_step_results"] = all_step_results
        # 互換性のため、ワークフロー全体の入力データもそのまま渡しておく
        merged_input.setdefault("global_input_data", global_input)

        # ここから先は「次にどのステップを起動するか」の分岐
        if not wf_skill:
            # ユーザー定義のStepは全て完了。
            # ここで「ワークフロー専用の統合プロンプト（リーダー）」を最後に1ステップとして実行する。
            # 各Workflowごとに leader_prompt_id を持たせており、それを必ず利用する。

            if not wf_exec.workflow or not wf_exec.workflow.leader_prompt_id:
                # 統合プロンプトが設定されていない場合はエラー扱い
                wf_exec.status = "error"
                wf_exec.error_message = "このワークフローには統合用プロンプト（leader_prompt_id）が設定されていません。管理画面から設定してください。"
                wf_exec.completed_at = datetime.now(timezone(timedelta(hours=9)))
                db.commit()
                logger.error(
                    f"WorkflowExecution {workflow_execution_id} error: leader_prompt_id is not configured "
                    f"for workflow_id={wf_exec.workflow_id}"
                )
                return

            leader_prompt_id = wf_exec.workflow.leader_prompt_id

            leader_prompt = (
                db.query(Prompt)
                .filter(
                    Prompt.id == leader_prompt_id,
                    Prompt.deleted_at.is_(None),
                    Prompt.is_active == True,  # noqa: E712
                )
                .first()
            )

            if not leader_prompt:
                wf_exec.status = "error"
                wf_exec.error_message = f"統合用プロンプト（ID={leader_prompt_id}）が見つからないか、利用できません。"
                wf_exec.completed_at = datetime.now(timezone(timedelta(hours=9)))
                db.commit()
                logger.error(
                    f"WorkflowExecution {workflow_execution_id} error: Leader prompt {leader_prompt_id} not found or inactive"
                )
                return

            # リーダー用Executionを作成（workflow_skill_idはNone）
            jst = timezone(timedelta(hours=9))
            leader_step_order = completed_step_order + 1

            leader_execution = Execution(
                account_id=wf_exec.account_id,
                prompt_id=leader_prompt.id,
                workflow_execution_id=workflow_execution_id,
                workflow_skill_id=None,
                step_order=leader_step_order,
                input_data=json.dumps(merged_input, ensure_ascii=False),
                status="pending",
                model_used=leader_prompt.model_type,
                enable_deep_think=bool(getattr(leader_prompt, "enable_deep_think", True)),
                output_format=wf_exec.executions[0].output_format if wf_exec.executions else "txt",
                executed_at=datetime.now(jst),
            )
            db.add(leader_execution)

            # ワークフロー実行側のメタ情報も更新（総ステップ数 +1 / 現在ステップをリーダーに）
            wf_exec.status = "processing"
            wf_exec.current_step = leader_step_order
            wf_exec.total_steps = (wf_exec.total_steps or leader_step_order)
            db.commit()
            db.refresh(leader_execution)

            # リーダーステップのCeleryタスクを起動
            execute_prompt_task.delay(
                execution_id=leader_execution.id,
                prompt_id=leader_prompt.id,
                input_data=merged_input,
                output_format=leader_execution.output_format,
                attachments=None,
                enable_deep_think=getattr(leader_prompt, "enable_deep_think", True),
            )

            logger.info(f"Started leader step (prompt_id={leader_prompt.id}) for WorkflowExecution {workflow_execution_id}")

            # 最後のサブエージェントのストリームに「リーダー開始」の通知を送る
            if previous_execution:
                try:
                    from app.services.redis_service import publish_workflow_next_step
                    workflow_name = None
                    if wf_exec:
                        workflow = db.query(Workflow).filter(Workflow.id == wf_exec.workflow_id).first()
                        if workflow:
                            workflow_name = workflow.name

                    publish_workflow_next_step(
                        previous_execution.id,
                        {
                            "next_execution_id": leader_execution.id,
                            "next_step_order": leader_step_order,
                            "step_name": "Leader",
                            "workflow_name": workflow_name,
                            "prompt_name": "Leader"
                        }
                    )
                except Exception as notify_error:
                    logger.warning(f"Failed to notify leader step start: {str(notify_error)}")

            return

        # ここから先は通常の「次のWorkflowSkillステップ」を起動する処理
        # 次のステップのExecutionレコードを作成
        prompt = wf_skill.prompt
        final_enable_deep_think = getattr(prompt, "enable_deep_think", True)
        if final_enable_deep_think is None:
            final_enable_deep_think = True
        
        jst = timezone(timedelta(hours=9))
        execution = Execution(
            account_id=wf_exec.account_id,
            prompt_id=prompt.id,
            workflow_execution_id=workflow_execution_id,
            workflow_skill_id=wf_skill.id,
            step_order=next_step_order,
            input_data=json.dumps(merged_input, ensure_ascii=False),
            status="pending",
            model_used=prompt.model_type,
            enable_deep_think=bool(final_enable_deep_think),
            output_format=wf_exec.executions[0].output_format if wf_exec.executions else "txt",
            executed_at=datetime.now(jst),
        )
        db.add(execution)
        
        # ワークフロー実行のステータスと現在のステップを更新
        wf_exec.status = "processing"
        wf_exec.current_step = next_step_order
        db.commit()
        db.refresh(execution)
        
        # 次のステップのCeleryタスクを起動
        execute_prompt_task.delay(
            execution_id=execution.id,
            prompt_id=prompt.id,
            input_data=merged_input,
            output_format=execution.output_format,
            attachments=None,
            enable_deep_think=final_enable_deep_think,
        )
        
        logger.info(f"Started next step {next_step_order} for WorkflowExecution {workflow_execution_id}")
        
        # 前ステップのストリームに「次のステップが起動された」というイベントを送信
        # これにより、フロントエンドが次のステップをバックグラウンドパネルに追加できる
        if previous_execution:
            try:
                from app.services.redis_service import publish_workflow_next_step
                # ワークフロー名を取得
                workflow_name = None
                if wf_exec:
                    workflow = db.query(Workflow).filter(Workflow.id == wf_exec.workflow_id).first()
                    if workflow:
                        workflow_name = workflow.name
                step_name = wf_skill.step_name or f"Step {next_step_order}"
                prompt_name = prompt.name if prompt else step_name
                publish_workflow_next_step(
                    previous_execution.id,
                    {
                        "next_execution_id": execution.id,
                        "next_step_order": next_step_order,
                        "step_name": step_name,
                        "workflow_name": workflow_name,
                        "prompt_name": prompt_name
                    }
                )
            except Exception as notify_error:
                logger.warning(f"Failed to notify next step start: {str(notify_error)}")
        
    except Exception as e:
        logger.error(f"Error continuing workflow execution: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        
        # ワークフロー実行をエラー状態に更新
        try:
            wf_exec = db.query(WorkflowExecution).filter(
                WorkflowExecution.id == workflow_execution_id
            ).first()
            if wf_exec:
                wf_exec.status = "error"
                wf_exec.error_message = f"ステップ {completed_step_order + 1} の起動に失敗: {str(e)}"
                db.commit()
        except Exception as db_error:
            logger.error(f"Failed to update workflow execution status: {str(db_error)}")
    finally:
        db.close()

