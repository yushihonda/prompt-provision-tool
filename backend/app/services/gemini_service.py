from google import generativeai as genai
from typing import Optional, Tuple
from app.config import settings
import logging
import asyncio

try:
    from google.api_core import exceptions as google_exceptions
except ImportError:
    # google-api-core がインストールされていない場合のフォールバック
    google_exceptions = None

logger = logging.getLogger(__name__)


class GeminiService:
    """
    Gemini API連携サービス（直接API接続）

    有料版の使用について:
    - Google Cloud Platformで課金を有効にすることで有料版として使用可能
    - 同じAPIキーを使用し、使用量に応じて課金されます
    - 無料枠の制限を超えた場合、自動的に有料版に切り替わります

    サポートモデル:
    - gemini-3-pro-preview: Gemini 3.0 Pro（最新モデル）
    - gemini-2.0-flash: Gemini 2.0 Flash
    - gemini-2.5-flash: Gemini 2.5 Flash
    - gemini-2.5-pro: Gemini 2.5 Pro（無料枠: 1日100リクエストまで、有料版で制限なし）
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Args:
            api_key: Gemini APIキー（指定しない場合は設定ファイルから取得）
        """
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.demo_mode = not self.api_key or self.api_key.strip() == ""

        if not self.demo_mode:
            genai.configure(api_key=self.api_key)
            logger.info("✓ Gemini Service: 直接Gemini API接続で初期化")
        else:
            logger.warning("⚠ Gemini Service: デモモードで初期化")

    def _normalize_model_name(self, model_name: str) -> str:
        """
        モデル名を正規化

        Args:
            model_name: モデル名（様々な形式に対応）

        Returns:
            正規化されたモデル名（Gemini APIで使用可能な形式）

        サポートされるモデル名:
        - gemini-3-pro-preview → gemini-3-pro-preview (Gemini 3.0 Pro)
        - gemini-2.0-flash → gemini-2.0-flash (Gemini 2.0 Flash)
        - gemini-2.5-flash → gemini-2.5-flash (Gemini 2.5 Flash)
        - gemini-2.5-pro → gemini-2.5-pro (Gemini 2.5 Pro)
        """
        # gemini/ プレフィックスを削除
        if model_name.startswith("gemini/"):
            model_name = model_name[len("gemini/"):]

        # モデル名のマッピング（Gemini APIの正しいモデル名に変換）
        model_mapping = {
            # 3.0 シリーズ
            "gemini-3-pro-preview": "gemini-3-pro-preview",
            "Gemini-3-Pro-Preview": "gemini-3-pro-preview",
            "gemini-3-pro": "gemini-3-pro-preview",
            "Gemini-3-Pro": "gemini-3-pro-preview",
            # 2.0 シリーズ
            "gemini-2.0-flash": "gemini-2.0-flash",
            "Gemini-2.0-Flash": "gemini-2.0-flash",
            # 2.5 シリーズ
            "gemini-2.5-flash": "gemini-2.5-flash",
            "Gemini-2.5-Flash": "gemini-2.5-flash",
            "gemini-2.5-pro": "gemini-2.5-pro",
            "Gemini-2.5-Pro": "gemini-2.5-pro",
        }

        # マッピングがあれば使用、なければそのまま返す
        return model_mapping.get(model_name, model_name)

    async def execute_prompt(
        self,
        prompt: str,
        model: str = "gemini-2.5-pro",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> dict:
        """
        プロンプトを実行

        Args:
            prompt: 実行するプロンプト
            model: 使用するモデル
                - gemini-3-pro-preview: Gemini 3.0 Pro（最新モデル）
                - gemini-2.0-flash: Gemini 2.0 Flash
                - gemini-2.5-flash: Gemini 2.5 Flash
                - gemini-2.5-pro: Gemini 2.5 Pro（無料枠: 1日100リクエストまで、有料版で制限なし）
            temperature: 温度パラメータ
            max_tokens: 最大トークン数（Noneの場合は長文対応のデフォルト値を使用）

        Returns:
            {
                "output": str,
                "model": str,
                "tokens": int
            }
        """
        model_name = self._normalize_model_name(model)

        logger.info(f"{'='*60}")
        logger.info("プロンプト実行開始 (Gemini)")
        logger.info(f"  モデル: {model_name}")
        logger.info(f"  プロンプト長: {len(prompt)} 文字")

        # デバッグモード時のみ詳細な情報を出力
        if settings.is_debug_mode:
            logger.debug(f"  プロンプト（最初の200文字）: {prompt[:200]}...")

        # 長文プロンプトの警告
        if len(prompt) > 100000:  # 10万文字以上
            logger.warning(f"  ⚠ 非常に長いプロンプトです（{len(prompt)}文字）。処理に時間がかかる可能性があります。")

        # max_tokensが指定されていない場合、長文対応のデフォルト値を設定
        if max_tokens is None:
            # Proモデルはより大きな値を設定
            if "pro" in model_name.lower():
                max_tokens = 32768  # Proモデルは長文出力に対応
            else:
                max_tokens = 16384  # Flashモデルも長文出力に対応

        # 本番環境でのデモモード禁止
        if settings.is_production and self.demo_mode:
            raise Exception(
                "Gemini APIキー未設定のため本番では実行できません。"
                "GEMINI_API_KEY を設定してください。"
            )

        # デモモード
        if self.demo_mode:
            logger.warning("⚠ デモモードで実行")
            return {
                "output": (
                    f"【デモモード】\n\n"
                    f"Gemini APIキーが設定されていないため、実際のAI応答は生成されません。\n\n"
                    f"実際に使用するには、.envファイルにGEMINI_API_KEYを設定してください。\n\n"
                    f"入力プロンプト（最初の100文字）:\n{prompt[:100]}..."
                ),
                "model": f"{model_name} (demo)",
                "tokens": 100
            }

        try:
            # プロンプトにガードレールを追加
            prompt_text = prompt
            if settings.ENABLE_PROMPT_GUARDRAILS:
                prompt_text = f"{settings.GUARDRAIL_PREFIX}\n\n{prompt}"
                logger.debug("  ガードレール有効")

            # Gemini APIを呼び出す
            gen_model = genai.GenerativeModel(model_name)

            generation_config = {}
            if temperature is not None:
                generation_config["temperature"] = temperature
            if max_tokens:
                generation_config["max_output_tokens"] = max_tokens

            logger.info(f"→ Gemini API呼び出し: {model_name}")
            if temperature is not None:
                logger.info(f"  Temperature: {temperature}")

            # デバッグモード時のみ詳細な情報を出力
            if settings.is_debug_mode:
                logger.debug(f"  プロンプト（最初の200文字）: {prompt_text[:200]}...")
                logger.debug(f"  Generation config: {generation_config}")

            # リトライロジック（指数バックオフ）
            max_retries = 3
            base_delay = 2.0  # 初期待機時間（秒）

            for attempt in range(max_retries):
                try:
                    if attempt > 0:
                        logger.info(f"  → リトライ試行 {attempt + 1}/{max_retries}")
                    # 非同期APIを使用
                    loop = asyncio.get_event_loop()
                    response = await loop.run_in_executor(
                        None,
                        lambda: gen_model.generate_content(
                            prompt_text,
                            generation_config=generation_config if generation_config else None
                        )
                    )
                    if attempt > 0:
                        logger.info(f"  ✓ {attempt + 1}回目の試行で成功")
                    break  # 成功したらループを抜ける
                except Exception as e:
                    error_type = type(e).__name__
                    error_msg = str(e)

                    # タイムアウトエラーのチェック
                    is_timeout = (
                        isinstance(e, asyncio.TimeoutError) or
                        (google_exceptions and isinstance(e, google_exceptions.DeadlineExceeded)) or
                        "timeout" in error_msg.lower() or
                        "timed out" in error_msg.lower() or
                        "deadline" in error_msg.lower()
                    )

                    if is_timeout:
                        if attempt < max_retries - 1:
                            delay = base_delay * (2 ** attempt)  # 指数バックオフ
                            logger.warning(
                                f"  ⚠ タイムアウトエラー (試行 {attempt + 1}/{max_retries})。"
                                f"エラータイプ: {error_type}。"
                                f"{delay:.1f}秒後にリトライします..."
                            )
                            await asyncio.sleep(delay)
                            continue
                        else:
                            logger.error(f"✗ Gemini API呼び出し失敗: タイムアウト（{max_retries}回試行後）")
                            logger.error(f"  エラータイプ: {error_type}")
                            raise Exception(
                                f"Gemini APIのタイムアウト: {max_retries}回のリトライ後も失敗しました。"
                                "処理に時間がかかりすぎている可能性があります。"
                            )

                    # Google APIエラーのチェック（タイムアウト以外）
                    if google_exceptions and isinstance(e, google_exceptions.GoogleAPIError):
                        logger.error(f"✗ Gemini API呼び出し失敗: {error_msg}")
                        logger.error(f"  エラータイプ: {error_type}")
                        raise

                    # その他のエラー
                    logger.error(f"✗ Gemini API呼び出し失敗: {error_msg}")
                    logger.error(f"  エラータイプ: {error_type}")
                    raise

            # レスポンスの処理（長文対応）
            output = None

            # まずtext属性から取得を試みる
            if hasattr(response, "text"):
                output = response.text

            # textが取得できない場合、partsから取得
            if not output and hasattr(response, "parts"):
                parts = response.parts
                if parts:
                    text_parts = []
                    for part in parts:
                        if hasattr(part, "text"):
                            text_parts.append(part.text)
                        elif isinstance(part, dict) and "text" in part:
                            text_parts.append(part["text"])
                        else:
                            text_parts.append(str(part))
                    output = "".join(text_parts)

            # それでも取得できない場合、candidatesから取得
            if not output and hasattr(response, "candidates"):
                candidates = response.candidates
                if candidates and len(candidates) > 0:
                    candidate = candidates[0]
                    if hasattr(candidate, "content"):
                        content = candidate.content
                        if hasattr(content, "parts"):
                            parts = content.parts
                            text_parts = []
                            for part in parts:
                                if hasattr(part, "text"):
                                    text_parts.append(part.text)
                                else:
                                    text_parts.append(str(part))
                            output = "".join(text_parts)

            # トークン使用量の取得（利用可能な場合）
            tokens_used = 0
            if hasattr(response, "usage_metadata"):
                usage = response.usage_metadata
                tokens_used = getattr(usage, "total_token_count", 0) or 0

            if not output:
                raise Exception("Gemini APIの出力が空です")

            # 長文レスポンスのログ出力
            if len(output) > 10000:
                logger.info(f"  長文レスポンスを取得しました（{len(output)}文字）")

            logger.info(f"✓ Gemini API呼び出し成功 (トークン: {tokens_used})")
            logger.info(f"{'='*60}")

            return {
                "output": output,
                "model": model_name,
                "tokens": tokens_used
            }

        except Exception as e:
            logger.error(f"✗ プロンプト実行失敗: {str(e)}")
            logger.error(f"  エラータイプ: {type(e).__name__}")
            logger.error(f"  モデル: {model_name}")

            # デバッグモード時のみ詳細なトレースバックを出力
            if settings.is_debug_mode:
                import traceback
                logger.debug(f"  トレースバック:\n{traceback.format_exc()}")

            logger.error(f"{'='*60}")

            err_msg = str(e)
            error_detail = err_msg
            if hasattr(e, '__cause__') and e.__cause__:
                error_detail = f"{err_msg} (原因: {str(e.__cause__)})"
            if "does not exist" in err_msg or "not found" in err_msg.lower() or "model_not_found" in err_msg.lower():
                raise Exception(
                    f"モデル '{model_name}' は存在しないか、アクセス権限がありません。"
                    f"利用可能なモデルを確認してください。"
                )
            raise Exception(f"Gemini API実行エラー: {error_detail}")

    async def execute_streaming(
        self,
        prompt: str,
        model: str = "gemini-2.5-pro",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ):
        """
        ストリーミングでプロンプトを実行

        Args:
            prompt: 実行するプロンプト
            model: 使用するモデル
                - gemini-3-pro-preview: Gemini 3.0 Pro（最新モデル）
                - gemini-2.0-flash: Gemini 2.0 Flash
                - gemini-2.5-flash: Gemini 2.5 Flash
                - gemini-2.5-pro: Gemini 2.5 Pro（無料枠: 1日100リクエストまで、有料版で制限なし）
            temperature: 温度パラメータ
            max_tokens: 最大トークン数

        Yields:
            生成されたテキストのチャンク
        """
        model_name = self._normalize_model_name(model)

        logger.info(f"{'='*60}")
        logger.info("ストリーミング実行開始 (Gemini)")
        logger.info(f"  モデル: {model_name}")

        if self.demo_mode:
            logger.warning("⚠ デモモードで実行")
            yield "【デモモード】Gemini APIキーが設定されていません。"
            return

        prompt_text = prompt
        if settings.ENABLE_PROMPT_GUARDRAILS:
            prompt_text = f"{settings.GUARDRAIL_PREFIX}\n\n{prompt}"

        gen_model = genai.GenerativeModel(model_name)

        generation_config = {}
        if temperature is not None:
            generation_config["temperature"] = temperature
        if max_tokens:
            generation_config["max_output_tokens"] = max_tokens

        if temperature is not None:
            logger.info(f"  Temperature: {temperature}")

        logger.info("→ ストリーミングAPI呼び出し")
        try:
            # ストリーミングAPIを使用
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: gen_model.generate_content(
                    prompt_text,
                    generation_config=generation_config if generation_config else None,
                    stream=True
                )
            )

            chunk_count = 0
            total_length = 0
            for chunk in response:
                # 複数の方法でテキストを取得
                text = None
                if hasattr(chunk, "text"):
                    text = chunk.text
                elif hasattr(chunk, "parts"):
                    parts = chunk.parts
                    if parts:
                        text_parts = []
                        for part in parts:
                            if hasattr(part, "text"):
                                text_parts.append(part.text)
                            else:
                                text_parts.append(str(part))
                        text = "".join(text_parts)
                elif hasattr(chunk, "candidates") and chunk.candidates:
                    candidate = chunk.candidates[0]
                    if hasattr(candidate, "content"):
                        content = candidate.content
                        if hasattr(content, "parts"):
                            parts = content.parts
                            text_parts = []
                            for part in parts:
                                if hasattr(part, "text"):
                                    text_parts.append(part.text)
                                else:
                                    text_parts.append(str(part))
                            text = "".join(text_parts)

                if text:
                    chunk_count += 1
                    total_length += len(text)
                    yield text

            logger.info(f"✓ ストリーミング完了 ({chunk_count} チャンク, 合計 {total_length} 文字)")
            logger.info(f"{'='*60}")

        except Exception as e:
            logger.error(f"✗ ストリーミング失敗: {str(e)}")
            logger.error(f"  エラータイプ: {type(e).__name__}")
            logger.error(f"  モデル: {model_name}")

            # デバッグモード時のみ詳細なトレースバックを出力
            if settings.is_debug_mode:
                import traceback
                logger.debug(f"  トレースバック:\n{traceback.format_exc()}")

            # フォールバック
            try:
                result = await self.execute_prompt(
                    prompt=prompt,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens
                )
                yield result["output"]
            except Exception as fallback_error:
                logger.error(f"✗ フォールバックも失敗: {str(fallback_error)}")
                yield f"【エラー】Gemini API実行エラー: {str(fallback_error)}"


# シングルトンインスタンス
gemini_service = GeminiService()
