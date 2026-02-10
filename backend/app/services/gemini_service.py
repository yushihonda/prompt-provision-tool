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

# 新しいSDK (google-genai) を試行（Deep Think機能用）
try:
    from google import genai as genai_new
    from google.genai import types
    NEW_SDK_AVAILABLE = True
except ImportError:
    NEW_SDK_AVAILABLE = False

logger = logging.getLogger(__name__)

if not NEW_SDK_AVAILABLE:
    logger.warning("google-genai SDK が利用できません。Deep Think機能は使用できません。")


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
            # 古いSDKを初期化（後方互換性のため）
            genai.configure(api_key=self.api_key)

            # 新しいSDKを初期化（Deep Think機能用）
            if NEW_SDK_AVAILABLE:
                try:
                    self.genai_client = genai_new.Client(api_key=self.api_key)
                    logger.info("✓ Gemini Service: 直接Gemini API接続で初期化（新SDK対応）")
                except Exception as e:
                    logger.warning(f"⚠ 新SDKの初期化に失敗: {e}。古いSDKを使用します。")
                    self.genai_client = None
            else:
                self.genai_client = None
                logger.info("✓ Gemini Service: 直接Gemini API接続で初期化（旧SDKのみ）")
        else:
            self.genai_client = None
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
            "gemini-3-pro-preview-deep-think": "gemini-3-pro-preview", # Deep Think版もベースモデルは同じ
            # 2.0 シリーズ
            "gemini-2.0-flash": "gemini-2.0-flash",
            "Gemini-2.0-Flash": "gemini-2.0-flash",
            # 2.5 シリーズ
            "gemini-2.5-flash": "gemini-2.5-flash",
            "Gemini-2.5-Flash": "gemini-2.5-flash",
            "gemini-2.5-pro": "gemini-2.5-pro",
            "Gemini-2.5-Pro": "gemini-2.5-pro",
            "gemini-2.5-pro-deep-think": "gemini-2.5-pro", # Deep Think版もベースモデルは同じ
        }

        # マッピングがあれば使用、なければそのまま返す
        return model_mapping.get(model_name, model_name)

    def _is_gemini_3_model(self, model_name: str) -> bool:
        """
        モデルがGemini 3系かどうかを判定

        Args:
            model_name: モデル名

        Returns:
            Gemini 3系の場合True
        """
        return "3" in model_name or "gemini-3" in model_name.lower()

    def _is_gemini_25_model(self, model_name: str) -> bool:
        """
        モデルがGemini 2.5系かどうかを判定

        Args:
            model_name: モデル名

        Returns:
            Gemini 2.5系の場合True
        """
        return "2.5" in model_name or "gemini-2.5" in model_name.lower()

    async def execute_prompt(
        self,
        prompt: str,
        model: str = "gemini-2.5-pro",
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        thinking_budget: Optional[int] = None,
        thinking_level: Optional[str] = None,
        enable_deep_think: bool = True,
        enable_web_search: bool = True,
        enable_code_interpreter: bool = False,
        enable_file_search: bool = False
    ) -> dict:
        """
        プロンプトを実行

        Args:
            prompt: 実行するプロンプト
            model: 使用するモデル
                - gemini-3-pro-preview: Gemini 3.0 Pro（最新モデル、Deep Think対応）
                - gemini-2.0-flash: Gemini 2.0 Flash
                - gemini-2.5-flash: Gemini 2.5 Flash（Deep Think対応）
                - gemini-2.5-pro: Gemini 2.5 Pro（Deep Think対応、無料枠: 1日100リクエストまで、有料版で制限なし）
                ※モデル名に "-deep-think" を付与するとDeep Think機能が強制的に有効になります
            temperature: 温度パラメータ
            max_tokens: 最大トークン数（Noneの場合は長文対応のデフォルト値を使用）
            thinking_budget: 思考バジェット（Gemini 2.5系用、0〜24576、Noneの場合は自動設定）
            thinking_level: 思考レベル（Gemini 3系用、"low"または"high"、Noneの場合は"high"）
            enable_deep_think: Deep Think機能を有効にするか（デフォルト: True、Falseの場合は旧SDKを使用）

        Returns:
            {
                "output": str,
                "model": str,
                "tokens": int
            }
        """
        # モデル名からDeep Think設定を判定（サフィックスがある場合は有効化）
        if "-deep-think" in model:
            enable_deep_think = True
            model = model.replace("-deep-think", "")

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

            # Deep Think設定の自動判定
            use_new_sdk = NEW_SDK_AVAILABLE and self.genai_client is not None
            is_gemini_3 = self._is_gemini_3_model(model_name)
            is_gemini_25 = self._is_gemini_25_model(model_name)

            # Deep Thinkが有効で、対応モデルの場合のみ新SDKを使用
            should_use_deep_think = enable_deep_think and (is_gemini_3 or is_gemini_25)

            # 新しいSDKを使用してDeep Think機能を有効化
            if use_new_sdk and should_use_deep_think:
                try:
                    logger.info(f"→ Gemini API呼び出し（新SDK + Deep Think）: {model_name}")

                    # Deep Think設定の準備
                    config_params = {}

                    if is_gemini_3:
                        # Gemini 3系: thinking_levelを使用
                        if thinking_level is None:
                            thinking_level = "high"  # デフォルトは高推論
                        config_params["thinking_level"] = thinking_level
                        logger.info(f"  Thinking Level: {thinking_level}")
                    elif is_gemini_25:
                        # Gemini 2.5系: thinking_budgetを使用
                        if thinking_budget is None:
                            thinking_budget = 8192  # デフォルト値
                        config_params["thinking_config"] = types.ThinkingConfig(
                            thinking_budget=thinking_budget
                        )
                        logger.info(f"  Thinking Budget: {thinking_budget}")

                    if temperature is not None:
                        config_params["temperature"] = temperature
                    if max_tokens:
                        config_params["max_output_tokens"] = max_tokens

                    # ツールを有効化
                    try:
                        # 新しいSDKではtypes.Tool()の形式で設定
                        if "tools" not in config_params:
                            config_params["tools"] = []
                        
                        tools_added = []
                        
                        # Google Searchツール（web_search）
                        if enable_web_search:
                            has_google_search = any(
                                (isinstance(tool, types.Tool) and hasattr(tool, "google_search")) or
                                (isinstance(tool, dict) and "google_search" in tool)
                                for tool in config_params.get("tools", [])
                            )
                            if not has_google_search:
                                config_params["tools"].append(types.Tool(google_search=types.GoogleSearch()))
                                tools_added.append("Google Search")
                        
                        # Code Interpreterツール
                        if enable_code_interpreter:
                            has_code_execution = any(
                                (isinstance(tool, types.Tool) and hasattr(tool, "code_execution")) or
                                (isinstance(tool, dict) and "code_execution" in tool)
                                for tool in config_params.get("tools", [])
                            )
                            if not has_code_execution:
                                config_params["tools"].append(types.Tool(code_execution=types.ToolCodeExecution()))
                                tools_added.append("Code Interpreter")
                        
                        # File Searchツール
                        if enable_file_search:
                            has_file_search = any(
                                (isinstance(tool, types.Tool) and hasattr(tool, "file_search")) or
                                (isinstance(tool, dict) and "file_search" in tool)
                                for tool in config_params.get("tools", [])
                            )
                            if not has_file_search:
                                config_params["tools"].append(types.Tool(file_search=types.FileSearch()))
                                tools_added.append("File Search")
                        
                        if tools_added:
                            logger.info(f"  ツール有効化: {', '.join(tools_added)}")
                    except Exception as tool_error:
                        logger.warning(f"  ツールの設定に失敗: {tool_error}")

                    if temperature is not None:
                        logger.info(f"  Temperature: {temperature}")

                    # デバッグモード時のみ詳細な情報を出力
                    if settings.is_debug_mode:
                        logger.debug(f"  プロンプト（最初の200文字）: {prompt_text[:200]}...")
                        logger.debug(f"  Config: {config_params}")

                    # リトライロジック（指数バックオフ）
                    max_retries = 3
                    base_delay = 2.0

                    for attempt in range(max_retries):
                        try:
                            if attempt > 0:
                                logger.info(f"  → リトライ試行 {attempt + 1}/{max_retries}")

                            # 新しいSDKでAPI呼び出し
                            loop = asyncio.get_event_loop()
                            config = types.GenerateContentConfig(**config_params)
                            response = await loop.run_in_executor(
                                None,
                                lambda: self.genai_client.models.generate_content(
                                    model=model_name,
                                    contents=prompt_text,
                                    config=config
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
                                "timeout" in error_msg.lower() or
                                "timed out" in error_msg.lower() or
                                "deadline" in error_msg.lower()
                            )

                            if is_timeout:
                                if attempt < max_retries - 1:
                                    delay = base_delay * (2 ** attempt)
                                    logger.warning(
                                        f"  ⚠ タイムアウトエラー (試行 {attempt + 1}/{max_retries})。"
                                        f"{delay:.1f}秒後にリトライします..."
                                    )
                                    await asyncio.sleep(delay)
                                    continue
                                else:
                                    logger.error(f"✗ Gemini API呼び出し失敗: タイムアウト（{max_retries}回試行後）")
                                    raise Exception(
                                        f"Gemini APIのタイムアウト: {max_retries}回のリトライ後も失敗しました。"
                                    )

                            # その他のエラー
                            logger.error(f"✗ Gemini API呼び出し失敗: {error_msg}")
                            if attempt < max_retries - 1:
                                delay = base_delay * (2 ** attempt)
                                await asyncio.sleep(delay)
                                continue
                            raise

                    # レスポンスの処理
                    output = None
                    if hasattr(response, "text"):
                        output = response.text
                    elif hasattr(response, "candidates") and response.candidates:
                        candidate = response.candidates[0]
                        if hasattr(candidate, "content"):
                            content = candidate.content
                            if hasattr(content, "parts"):
                                text_parts = []
                                for part in content.parts:
                                    if hasattr(part, "text"):
                                        text_parts.append(part.text)
                                output = "".join(text_parts)

                    # トークン使用量の取得
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

                except Exception as new_sdk_error:
                    logger.warning(f"新SDKでの呼び出しに失敗: {new_sdk_error}。旧SDKにフォールバックします。")
                    # 旧SDKにフォールバック（下記のコードに続く）

            # 旧SDKを使用（後方互換性のため、または新SDKが利用できない場合）
            logger.info(f"→ Gemini API呼び出し（旧SDK）: {model_name}")

            # 旧SDK用のツールリストを構築
            old_sdk_tools = []
            tools_log = []
            
            if enable_web_search:
                old_sdk_tools.append("google_search_retrieval")
                tools_log.append("Google Search")
            
            if enable_code_interpreter:
                old_sdk_tools.append("code_execution")
                tools_log.append("Code Interpreter")
            
            if enable_file_search:
                old_sdk_tools.append("file_search")
                tools_log.append("File Search")
            
            # Gemini APIを呼び出す
            gen_model = genai.GenerativeModel(
                model_name,
                tools=old_sdk_tools if old_sdk_tools else None
            )

            generation_config = {}
            if temperature is not None:
                generation_config["temperature"] = temperature
            if max_tokens:
                generation_config["max_output_tokens"] = max_tokens

            if temperature is not None:
                logger.info(f"  Temperature: {temperature}")
            if tools_log:
                logger.info(f"  ツール有効化: {', '.join(tools_log)}")

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
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        thinking_budget: Optional[int] = None,
        thinking_level: Optional[str] = None,
        enable_deep_think: bool = True,
        enable_web_search: bool = True,
        enable_code_interpreter: bool = False,
        enable_file_search: bool = False
    ):
        """
        ストリーミングでプロンプトを実行

        Args:
            prompt: 実行するプロンプト
            model: 使用するモデル
                - gemini-3-pro-preview: Gemini 3.0 Pro（最新モデル、Deep Think対応）
                - gemini-2.0-flash: Gemini 2.0 Flash
                - gemini-2.5-flash: Gemini 2.5 Flash（Deep Think対応）
                - gemini-2.5-pro: Gemini 2.5 Pro（Deep Think対応、無料枠: 1日100リクエストまで、有料版で制限なし）
                ※モデル名に "-deep-think" を付与するとDeep Think機能が強制的に有効になります
            temperature: 温度パラメータ
            max_tokens: 最大トークン数
            thinking_budget: 思考バジェット（Gemini 2.5系用、0〜24576、Noneの場合は自動設定）
            thinking_level: 思考レベル（Gemini 3系用、"low"または"high"、Noneの場合は"high"）
            enable_deep_think: Deep Think機能を有効にするか（デフォルト: True、Falseの場合は旧SDKを使用）

        Yields:
            生成されたテキストのチャンク
        """
        # モデル名からDeep Think設定を判定（サフィックスがある場合は有効化）
        if "-deep-think" in model:
            enable_deep_think = True
            model = model.replace("-deep-think", "")

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

        # Deep Think設定の自動判定
        use_new_sdk = NEW_SDK_AVAILABLE and self.genai_client is not None
        is_gemini_3 = self._is_gemini_3_model(model_name)
        is_gemini_25 = self._is_gemini_25_model(model_name)
        should_use_deep_think = enable_deep_think and (is_gemini_3 or is_gemini_25)

        logger.info("→ ストリーミングAPI呼び出し")
        try:
            # 新しいSDKを使用してDeep Think機能を有効化（ストリーミングは新SDKでサポートされていない可能性があるため、旧SDKにフォールバック）
            # 注: ストリーミングは現時点では旧SDKを使用
            # 旧SDK用のツールリストを構築
            old_sdk_tools = []
            tools_log = []
            
            if enable_web_search:
                old_sdk_tools.append("google_search_retrieval")
                tools_log.append("Google Search")
            
            if enable_code_interpreter:
                old_sdk_tools.append("code_execution")
                tools_log.append("Code Interpreter")
            
            if enable_file_search:
                old_sdk_tools.append("file_search")
                tools_log.append("File Search")
            
            gen_model = genai.GenerativeModel(
                model_name,
                tools=old_sdk_tools if old_sdk_tools else None
            )

            generation_config = {}
            if temperature is not None:
                generation_config["temperature"] = temperature
            if max_tokens:
                generation_config["max_output_tokens"] = max_tokens

            if temperature is not None:
                logger.info(f"  Temperature: {temperature}")
            if tools_log:
                logger.info(f"  ツール有効化: {', '.join(tools_log)}")

            if should_use_deep_think:
                logger.info(f"  Deep Think機能: 有効（ストリーミングでは旧SDKを使用）")
            elif enable_deep_think is False:
                logger.info(f"  Deep Think機能: 無効（ユーザー指定）")

            # ストリーミングAPIを使用（旧SDK）
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
            tokens_used = 0
            last_chunk = None
            
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

                # 最後のチャンクを保持（usage情報が含まれる可能性がある）
                last_chunk = chunk
                
                # usage情報が含まれている場合は取得
                if hasattr(chunk, "usage_metadata") and chunk.usage_metadata:
                    usage = chunk.usage_metadata
                    if hasattr(usage, "total_token_count"):
                        tokens_used = usage.total_token_count
                    elif isinstance(usage, dict):
                        tokens_used = usage.get("total_token_count", 0)

            # 最後のチャンクからusage情報を取得（まだ取得できていない場合）
            if tokens_used == 0 and last_chunk:
                if hasattr(last_chunk, "usage_metadata") and last_chunk.usage_metadata:
                    usage = last_chunk.usage_metadata
                    if hasattr(usage, "total_token_count"):
                        tokens_used = usage.total_token_count
                    elif isinstance(usage, dict):
                        tokens_used = usage.get("total_token_count", 0)

            logger.info(f"✓ ストリーミング完了 ({chunk_count} チャンク, 合計 {total_length} 文字, トークン: {tokens_used})")
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
