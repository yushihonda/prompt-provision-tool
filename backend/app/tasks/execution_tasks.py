"""
プロンプト実行Celeryタスク
"""
import time
import json
import base64
import logging
import asyncio
from typing import Optional
from sqlalchemy.orm import Session
from app.celery_app import celery_app
from app.models import Execution, Prompt, Account, APIConfig, AccountType
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
            async def run_streaming_execution():
                """非同期ストリーミング実行"""
                output_chunks = []
                long_running_warning_sent = False  # 長時間実行警告の送信フラグ
                LONG_RUNNING_THRESHOLD = 1800  # 30分（秒）
                
                if is_openai:
                    # キャンセルチェック
                    if is_cancelled(execution_id):
                        raise asyncio.CancelledError("Execution was cancelled")
                    
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
                            model=model_str
                        ):
                            # キャンセルチェック
                            if is_cancelled(execution_id):
                                publish_cancel(execution_id)
                                raise asyncio.CancelledError("Execution was cancelled")
                            
                            # 長時間実行警告チェック（30分以上）
                            if not long_running_warning_sent:
                                elapsed_time = time.time() - start_time
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
                            import time
                            time.sleep(0.1)  # 100ms待機
                            logger.info(f"Execution {execution_id}: All chunks published, waiting before complete event")
                        else:
                            logger.warning(f"Execution {execution_id}: No output to publish (chunk_count: {chunk_count})")
                    else:
                        # 通常のストリーミングモデル（gpt-4oなど）の場合は、チャンクをそのまま送信
                        async for chunk in user_openai_service.execute_streaming(
                            prompt=final_prompt,
                            model=model_str
                        ):
                            # キャンセルチェック
                            if is_cancelled(execution_id):
                                publish_cancel(execution_id)
                                raise asyncio.CancelledError("Execution was cancelled")
                            
                            # 長時間実行警告チェック（30分以上）
                            if not long_running_warning_sent:
                                elapsed_time = time.time() - start_time
                                if elapsed_time >= LONG_RUNNING_THRESHOLD:
                                    logger.warning(f"Execution {execution_id}: 長時間実行中（{elapsed_time/60:.1f}分経過）。通常の実行時間を超過しています。")
                                    long_running_warning_sent = True
                            
                            # チャンクをそのまま送信（リアルタイム表示）
                            publish_chunk(execution_id, chunk)
                            output_chunks.append(chunk)
                        
                        # 通常のストリーミングモデルでは、最後のチャンク送信後に少し待機
                        # これにより、フロントエンドが最後のチャンクを受信してから完了イベントを受信できる
                        import time
                        time.sleep(0.1)  # 100ms待機
                    
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
                    
                    # Geminiストリーミング実行
                    # Geminiは通常ストリーミングをサポートしているが、大きなチャンクが来る可能性があるため、
                    # チャンクをそのまま送信する（リアルタイム表示）
                    async for chunk in user_gemini_service.execute_streaming(
                        prompt=final_prompt,
                        model=model_str,
                        enable_deep_think=deep_think_enabled
                    ):
                        # キャンセルチェック
                        if is_cancelled(execution_id):
                            publish_cancel(execution_id)
                            raise asyncio.CancelledError("Execution was cancelled")
                        
                        # 長時間実行警告チェック（30分以上）
                        if not long_running_warning_sent:
                            elapsed_time = time.time() - start_time
                            if elapsed_time >= LONG_RUNNING_THRESHOLD:
                                logger.warning(f"Execution {execution_id}: 長時間実行中（{elapsed_time/60:.1f}分経過）。通常の実行時間を超過しています。")
                                long_running_warning_sent = True
                        
                        # チャンクをそのまま送信（リアルタイム表示）
                        publish_chunk(execution_id, chunk)
                        output_chunks.append(chunk)
                    
                    # 最後のチャンク送信後に少し待機してから完了イベントを送信する
                    # これにより、フロントエンドが最後のチャンクを受信してから完了イベントを受信できる
                    import time
                    time.sleep(0.1)  # 100ms待機
                    
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
            result = asyncio.run(run_streaming_execution())
            
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

