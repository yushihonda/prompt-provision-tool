import time
import json
import base64
import logging
import asyncio
from typing import Optional
from sqlalchemy.orm import Session
from app.models import Execution, Prompt, Account, APIConfig, AccountType
from app.encryption import encryption_service
from app.services.openai_service import openai_service, OpenAIService
from app.services.gemini_service import gemini_service, GeminiService
from app.config import settings
from app.utils.file_export import export_content
from app.utils.pricing import calculate_token_cost
from app.api.execute import replace_placeholders, sanitize_output
from app.database import SessionLocal

logger = logging.getLogger(__name__)


def save_cancelled_execution(execution, execution_id: int, db: Session, start_time: float = None):
    """
    停止状態として実行ログを保存する共通関数

    Args:
        execution: Executionオブジェクト
        execution_id: 実行ID
        db: データベースセッション
        start_time: 開始時刻（実行時間を計算するため、Noneの場合は0）
    """
    execution.status = "cancelled"
    execution.error_message = "ユーザーによりキャンセルされました"

    # 実行時間を記録
    if start_time is not None:
        execution.execution_time = int((time.time() - start_time) * 1000)
    else:
        execution.execution_time = 0

    execution.tokens_used = 0
    execution.cost = 0.0  # キャンセル時は料金0
    execution.output_data = ""  # 出力データは空
    db.commit()
    logger.info(f"Execution {execution_id} saved as cancelled")


async def process_execution_background(
    execution_id: int,
    prompt_id: int,
    input_data: dict,
    output_format: str = "txt",
    attachments: list = None,
    enable_deep_think: Optional[bool] = None
):
    """
    バックグラウンドでプロンプトを実行し、結果をDBに保存する
    """
    db = SessionLocal()
    execution = None
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
        db.refresh(execution)  # コミット後にリフレッシュ

        # プロンプトの取得
        prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
        if not prompt:
            execution.status = "error"
            execution.error_message = "プロンプトが見つかりません"
            db.commit()
            return

        # アカウントのAPI設定を取得（子アカウントのみ）
        account = db.query(Account).filter(Account.id == execution.account_id).first()
        api_config = None
        if account and str(account.account_type) == AccountType.CHILD:
            api_config = db.query(APIConfig).filter(APIConfig.account_id == account.id).first()

        # ユーザーごとのAPIキーを取得（設定されていない場合はデフォルトを使用）
        openai_api_key = None
        gemini_api_key = None
        if api_config and api_config.is_enabled:
            openai_api_key = api_config.openai_api_key if api_config.openai_api_key else None
            gemini_api_key = api_config.gemini_api_key if api_config.gemini_api_key else None

        # ユーザーごとのAPIキーを使用してサービスを初期化（設定されていない場合はデフォルトを使用）
        user_openai_service = OpenAIService(api_key=openai_api_key) if openai_api_key else openai_service
        user_gemini_service = GeminiService(api_key=gemini_api_key) if gemini_api_key else gemini_service

        start_time = time.time()

        # プロンプトを復号化
        try:
            decrypted_prompt = encryption_service.decrypt(prompt.encrypted_content)
        except Exception as e:
            execution.status = "error"
            execution.error_message = "プロンプトの復号化に失敗しました"
            db.commit()
            return

        # 添付ファイルの処理
        attached_files = {}
        if attachments:
            for attachment in attachments:
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
        final_prompt = replace_placeholders(decrypted_prompt, input_data)

        # 添付ファイルの内容をプロンプトに追加（オプション）
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
            return

        # AIサービスの選択と実行
        try:
            # 許可モデルとサービス判定
            openai_models = {
                "gpt-5-pro",
                "gpt-5",
                "gpt-5.1",
                "gpt-5.1-thinking",
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

            if is_openai:
                # キャンセルチェック（API呼び出し直前）
                db.refresh(execution)
                if execution.status == "cancelled":
                    logger.info(f"Execution {execution_id} cancelled before OpenAI call")
                    # 停止状態としてデータを保存
                    execution.error_message = "ユーザーによりキャンセルされました"
                    execution.execution_time = 0
                    execution.tokens_used = 0
                    execution.cost = 0.0  # キャンセル時は料金0
                    db.commit()
                    return

                # OpenAI API呼び出し（キャンセルチェック付き）
                # 定期的にキャンセル状態をチェックしながらAPI呼び出しを実行
                async def check_cancellation_periodically():
                    """定期的にキャンセル状態をチェックし、キャンセルされていたら例外を投げる"""
                    check_interval = 1.0  # 1秒ごとにチェック
                    check_db = SessionLocal()
                    try:
                        while True:
                            await asyncio.sleep(check_interval)
                            # 新しいDBセッションでキャンセル状態をチェック
                            check_execution = check_db.query(Execution).filter(Execution.id == execution_id).first()
                            if check_execution and check_execution.status == "cancelled":
                                logger.info(f"Execution {execution_id} cancelled during OpenAI call (periodic check)")
                                raise asyncio.CancelledError("Execution was cancelled")
                    finally:
                        check_db.close()

                async def call_openai_api():
                    """OpenAI APIを呼び出す"""
                    return await user_openai_service.execute_prompt(
                        prompt=final_prompt,
                        model=model_str
                    )

                # キャンセルチェックタスクとAPI呼び出しタスクを並行実行
                try:
                    api_task = asyncio.create_task(call_openai_api())
                    check_task = asyncio.create_task(check_cancellation_periodically())

                    # どちらかが完了するまで待つ
                    done, pending = await asyncio.wait(
                        [api_task, check_task],
                        return_when=asyncio.FIRST_COMPLETED
                    )

                    # 残りのタスクをキャンセル
                    for task in pending:
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass

                    # APIタスクが完了した場合
                    if api_task in done:
                        try:
                            result = await api_task
                        except asyncio.CancelledError:
                            # キャンセルチェックタスクが先に完了した場合
                            db.refresh(execution)
                            save_cancelled_execution(execution, execution_id, db, start_time=start_time)
                            raise
                    else:
                        # キャンセルチェックタスクが先に完了した場合
                        db.refresh(execution)
                        save_cancelled_execution(execution, execution_id, db, start_time=start_time)
                        raise asyncio.CancelledError("Execution was cancelled")

                except asyncio.CancelledError:
                    # タスクがキャンセルされた場合
                    db.refresh(execution)
                    save_cancelled_execution(execution, execution_id, db, start_time=start_time)
                    raise  # CancelledErrorを再スロー
                except Exception as api_error:
                    # API呼び出し中にエラーが発生した場合、キャンセル状態をチェック
                    db.refresh(execution)
                    if execution.status == "cancelled":
                        logger.info(f"Execution {execution_id} was cancelled during OpenAI call")
                        save_cancelled_execution(execution, execution_id, db, start_time=start_time)
                        return
                    raise  # キャンセル以外のエラーは再スロー

                # API呼び出し後のキャンセルチェック（確実に最新状態を取得）
                db.refresh(execution)
                if execution.status == "cancelled":
                    logger.info(f"Execution {execution_id} cancelled after OpenAI call, saving as cancelled")
                    # 停止状態としてデータを保存（実行時間を記録）
                    execution.error_message = "ユーザーによりキャンセルされました"
                    execution.execution_time = int((time.time() - start_time) * 1000)
                    execution.tokens_used = 0
                    execution.cost = 0.0  # キャンセル時は料金0
                    execution.output_data = ""  # 出力データは空
                    db.commit()
                    return

            elif is_gemini:
                # キャンセルチェック（API呼び出し直前）
                db.refresh(execution)
                if execution.status == "cancelled":
                    logger.info(f"Execution {execution_id} cancelled before Gemini call")
                    save_cancelled_execution(execution, execution_id, db, start_time=start_time)
                    return

                # Gemini API呼び出し（キャンセルチェック付き）
                # 定期的にキャンセル状態をチェックしながらAPI呼び出しを実行
                async def check_cancellation_periodically():
                    """定期的にキャンセル状態をチェックし、キャンセルされていたら例外を投げる"""
                    check_interval = 1.0  # 1秒ごとにチェック
                    check_db = SessionLocal()
                    try:
                        while True:
                            await asyncio.sleep(check_interval)
                            # 新しいDBセッションでキャンセル状態をチェック
                            check_execution = check_db.query(Execution).filter(Execution.id == execution_id).first()
                            if check_execution and check_execution.status == "cancelled":
                                logger.info(f"Execution {execution_id} cancelled during Gemini call (periodic check)")
                                raise asyncio.CancelledError("Execution was cancelled")
                    finally:
                        check_db.close()

                async def call_gemini_api():
                    """Gemini APIを呼び出す"""
                    # Deep Think設定の優先順位:
                    # 1. リクエストで明示的に指定された場合（enable_deep_think）
                    # 2. プロンプトの設定（prompt.enable_deep_think）
                    # 3. デフォルト（True）
                    if enable_deep_think is not None:
                        deep_think_enabled = enable_deep_think
                    else:
                        # プロンプトの設定を使用（デフォルトはTrue）
                        deep_think_enabled = getattr(prompt, 'enable_deep_think', True)

                    return await user_gemini_service.execute_prompt(
                        prompt=final_prompt,
                        model=model_str,
                        enable_deep_think=deep_think_enabled
                    )

                # キャンセルチェックタスクとAPI呼び出しタスクを並行実行
                try:
                    api_task = asyncio.create_task(call_gemini_api())
                    check_task = asyncio.create_task(check_cancellation_periodically())

                    # どちらかが完了するまで待つ
                    done, pending = await asyncio.wait(
                        [api_task, check_task],
                        return_when=asyncio.FIRST_COMPLETED
                    )

                    # 残りのタスクをキャンセル
                    for task in pending:
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass

                    # APIタスクが完了した場合
                    if api_task in done:
                        try:
                            result = await api_task
                        except asyncio.CancelledError:
                            # キャンセルチェックタスクが先に完了した場合
                            db.refresh(execution)
                            save_cancelled_execution(execution, execution_id, db, start_time=start_time)
                            raise
                    else:
                        # キャンセルチェックタスクが先に完了した場合
                        db.refresh(execution)
                        save_cancelled_execution(execution, execution_id, db, start_time=start_time)
                        raise asyncio.CancelledError("Execution was cancelled")

                except asyncio.CancelledError:
                    # タスクがキャンセルされた場合
                    db.refresh(execution)
                    save_cancelled_execution(execution, execution_id, db, start_time=start_time)
                    raise  # CancelledErrorを再スロー
                except Exception as api_error:
                    # API呼び出し中にエラーが発生した場合、キャンセル状態をチェック
                    db.refresh(execution)
                    if execution.status == "cancelled":
                        logger.info(f"Execution {execution_id} was cancelled during Gemini call")
                        save_cancelled_execution(execution, execution_id, db, start_time=start_time)
                        return
                    raise  # キャンセル以外のエラーは再スロー

                # API呼び出し後のキャンセルチェック（確実に最新状態を取得）
                db.refresh(execution)
                if execution.status == "cancelled":
                    logger.info(f"Execution {execution_id} cancelled after Gemini call, saving as cancelled")
                    save_cancelled_execution(execution, execution_id, db, start_time=start_time)
                    return
            else:
                raise ValueError("サポートされていないモデルです")

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

        # キャンセルチェック（結果処理前）
        db.refresh(execution)
        if execution.status == "cancelled":
            logger.info(f"Execution {execution_id} was cancelled before result processing, saving as cancelled")
            save_cancelled_execution(execution, execution_id, db, start_time=start_time)
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
            logger.info(f"Execution {execution_id} was cancelled before result save, saving as cancelled")
            save_cancelled_execution(execution, execution_id, db, start_time=start_time)
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
        # 実行回数は成功・エラー・キャンセルすべてをカウント（実行が完了した場合）
        if status_result in ["success", "error", "cancelled"]:
            from datetime import datetime, timezone, timedelta
            account = db.query(Account).filter(Account.id == execution.account_id).first()
            if account:
                # 月が変わったかチェック（今月のデータをリセット）
                # JST（日本時間）で現在の月の開始日時を取得
                jst = timezone(timedelta(hours=9))
                current_month = datetime.now(jst).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                
                # last_month_resetがtimezone-naiveの場合はJSTとして解釈
                should_reset = False
                if account.last_month_reset is None:
                    should_reset = True
                else:
                    # timezone-awareかどうかを確認
                    if account.last_month_reset.tzinfo is None:
                        # timezone-naiveの場合はJSTとして解釈
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

                # 実行回数をインクリメント（今月と全期間）
                account.executions_this_month = (account.executions_this_month or 0) + 1
                account.total_executions = (account.total_executions or 0) + 1

                # トークン数と料金は成功時のみ更新
                if status_result == "success" and tokens_used and tokens_used > 0:
                    # 全期間の総計を更新
                    old_total_cost = float(account.total_cost or 0.0)
                    old_cost_this_month = float(account.cost_this_month or 0.0)
                    account.total_tokens = (account.total_tokens or 0) + tokens_used
                    account.total_cost = old_total_cost + float(execution.cost or 0.0)

                    # 今月のデータを更新
                    account.tokens_this_month = (account.tokens_this_month or 0) + tokens_used
                    account.cost_this_month = old_cost_this_month + float(execution.cost or 0.0)

                    logger.info(f"Updated account {account.id} totals: tokens={account.total_tokens}, cost=${account.total_cost:.6f} (added ${execution.cost:.6f}), this_month_tokens={account.tokens_this_month}, this_month_cost=${account.cost_this_month:.6f} (added ${execution.cost:.6f}), this_month_executions={account.executions_this_month}")
                else:
                    logger.info(f"Updated account {account.id} execution count: this_month_executions={account.executions_this_month} (status={status_result})")
            else:
                logger.warning(f"Account {execution.account_id} not found for execution {execution_id}")
        else:
            logger.info(f"Execution {execution_id}: Skipping account update (status={status_result}, not completed yet)")

        db.commit()
        logger.info(f"Execution {execution_id} completed with status: {status_result}")

    except Exception as e:
        logger.error(f"Background execution error: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        if execution:
            try:
                db.refresh(execution)
                execution.status = "error"
                execution.error_message = f"システムエラー: {str(e)}"
                db.commit()
            except Exception as db_error:
                logger.error(f"Failed to update execution status: {str(db_error)}")
    finally:
        db.close()
