from openai import AsyncOpenAI
from typing import Optional, Tuple
from app.config import settings
import logging
import asyncio
from openai import APITimeoutError, APIError

logger = logging.getLogger(__name__)


class OpenAIService:
    """OpenAI API連携サービス（直接API接続）"""

    # 推論モデル（Responses APIを使用）
    REASONING_MODELS = {
        "gpt-5.2-pro", "gpt-5.4-pro", "o4-mini",
    }

    # temperatureをサポートしないモデル
    NO_TEMPERATURE_MODELS = {
        "gpt-5.2", "gpt-5.2-pro",
        "gpt-5.4", "gpt-5.4-pro",
        "o4-mini",
    }

    # max_completion_tokensを使用する必要があるモデル（max_tokensの代わり）
    MAX_COMPLETION_TOKENS_MODELS = {
        "gpt-5.2",
        "gpt-5.4", "gpt-5.4-mini",
    }

    def __init__(self, api_key: Optional[str] = None):
        """
        Args:
            api_key: OpenAI APIキー（指定しない場合は設定ファイルから取得）
        """
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.demo_mode = not self.api_key or self.api_key.strip() == ""
        self.client: Optional[AsyncOpenAI] = None

        if self.demo_mode:
            logger.warning("⚠ OpenAI Service: デモモードで初期化")
            return

        # 直接OpenAI APIで初期化
        # Responses API（特にgpt-5-pro）は処理に時間がかかる可能性があるため、タイムアウトを延長
        # gpt-5-proは複雑な推論タスクで10分以上かかる場合がある
        self.client = AsyncOpenAI(
            api_key=self.api_key,
            timeout=600.0  # 10分（gpt-5-pro対応）
        )
        logger.info("✓ OpenAI Service: 直接OpenAI API接続で初期化")

    def _is_reasoning_model(self, model_name: str) -> bool:
        """推論モデルかどうかを判定"""
        # gpt-5.1-thinkingとgpt-5.2-thinkingはそれぞれgpt-5.1とgpt-5.2にreasoning_effort="high"を指定する形で使用
        if model_name == "gpt-5.1-thinking" or model_name == "gpt-5.2-thinking":
            return True
        return model_name in self.REASONING_MODELS

    def _get_reasoning_effort(self, model_name: str) -> Optional[str]:
        """推論モデルのreasoning_effortを返す"""
        if not self._is_reasoning_model(model_name):
            return None

        m = model_name.lower()
        # gpt-5.1-thinkingとgpt-5.2-thinkingはhighを返す
        if m == "gpt-5.1-thinking" or m == "gpt-5.2-thinking":
            return "high"
        # gpt-5-proとgpt-5.2-proはreasoning_effortを必要としない
        if m == "gpt-5-pro" or m == "gpt-5.2-pro":
            return None
        if "nano" in m:
            return "low"
        if "mini" in m:
            return "medium"
        return "high"

    def _convert_messages_to_responses_input(self, messages: list) -> list:
        """Chat Completions形式のメッセージを Responses API 形式へ変換"""
        response_input = []
        for message in messages:
            role = message.get("role", "user")
            content = message.get("content", "")

            if isinstance(content, str):
                # Responses APIでは type: "input_text" と text フィールドを使用
                content_parts = [{"type": "input_text", "text": content}]
            elif isinstance(content, list):
                # 既にResponses API形式の場合はそのまま使用
                content_parts = []
                for part in content:
                    if isinstance(part, dict):
                        part_type = part.get("type")
                        if part_type == "text":
                            # "text"を"input_text"に変換
                            content_parts.append({
                                "type": "input_text",
                                "text": part.get("text", "")
                            })
                        elif part_type == "input_text":
                            # 既にinput_text形式の場合はそのまま
                            content_parts.append(part)
                        else:
                            # その他の形式もそのまま
                            content_parts.append(part)
                    else:
                        content_parts.append(part)
            else:
                content_parts = [{"type": "input_text", "text": str(content)}]

            response_input.append({
                "role": role,
                "content": content_parts
            })
        return response_input

    async def _call_responses_api(
        self,
        model_name: str,
        messages: list,
        temperature: Optional[float],
        max_tokens: Optional[int],
    ) -> Tuple[str, int]:
        """Responses API を呼び出す（推論モデル向け）"""
        if not self.client:
            raise RuntimeError("OpenAI クライアントが未初期化です")

        reasoning_effort = self._get_reasoning_effort(model_name)

        # gpt-5.1-thinkingとgpt-5.2-thinkingの場合は実際のAPI呼び出し時にはそれぞれgpt-5.1とgpt-5.2を使用
        if model_name == "gpt-5.1-thinking":
            actual_model = "gpt-5.1"
        elif model_name == "gpt-5.2-thinking":
            actual_model = "gpt-5.2"
        else:
            actual_model = model_name

        kwargs = {
            "model": actual_model,
            "input": self._convert_messages_to_responses_input(messages)
        }

        if max_tokens:
            kwargs["max_output_tokens"] = max_tokens

        # temperatureパラメータの追加（gpt-5-proなど、temperatureをサポートするモデル向け）
        # gpt-5.1-thinking（実際にはgpt-5.1）とgpt-5.2-thinking（実際にはgpt-5.2）はtemperatureをサポートしない
        if model_name not in self.NO_TEMPERATURE_MODELS and actual_model not in self.NO_TEMPERATURE_MODELS:
            if temperature is not None:
                kwargs["temperature"] = temperature

        if reasoning_effort:
            kwargs["reasoning"] = {"effort": reasoning_effort}

        logger.info(f"→ Responses API呼び出し: {model_name}")
        logger.info(f"  Reasoning effort: {reasoning_effort}")
        if temperature is not None and model_name not in self.NO_TEMPERATURE_MODELS:
            logger.info(f"  Temperature: {temperature}")

        # デバッグモード時のみ詳細な情報を出力
        if settings.is_debug_mode:
            logger.debug(f"  Messages count: {len(messages)}")
            logger.debug(f"  Max tokens: {max_tokens}")
            logger.debug(f"  API parameters: {kwargs}")

        # リトライロジック（指数バックオフ）
        max_retries = 3
        base_delay = 2.0  # 初期待機時間（秒）

        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    logger.info(f"  → リトライ試行 {attempt + 1}/{max_retries}")
                response = await self.client.responses.create(**kwargs)
                if attempt > 0:
                    logger.info(f"  ✓ {attempt + 1}回目の試行で成功")
                break  # 成功したらループを抜ける
            except (APITimeoutError, asyncio.TimeoutError) as e:
                error_type = type(e).__name__
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
                    logger.error(f"✗ Responses API呼び出し失敗: タイムアウト（{max_retries}回試行後）")
                    logger.error(f"  エラータイプ: {error_type}")
                    raise Exception(
                        f"Responses APIのタイムアウト: {max_retries}回のリトライ後も失敗しました。"
                        "処理に時間がかかりすぎている可能性があります。"
                    )
            except APIError as e:
                # APIエラー（タイムアウト以外）は即座に失敗
                error_type = type(e).__name__
                error_msg = str(e)
                logger.error(f"✗ Responses API呼び出し失敗: {error_msg}")
                logger.error(f"  エラータイプ: {error_type}")
                # タイムアウト関連のエラーメッセージもチェック
                if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(
                            f"  ⚠ タイムアウト関連エラー検出 (試行 {attempt + 1}/{max_retries})。"
                            f"{delay:.1f}秒後にリトライします..."
                        )
                        await asyncio.sleep(delay)
                        continue
                raise
            except Exception as e:
                # その他のエラーもチェック
                error_type = type(e).__name__
                error_msg = str(e)
                logger.error(f"✗ Responses API呼び出し失敗: {error_msg}")
                logger.error(f"  エラータイプ: {error_type}")
                # タイムアウト関連のエラーメッセージをチェック
                if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(
                            f"  ⚠ タイムアウト関連エラー検出 (試行 {attempt + 1}/{max_retries})。"
                            f"{delay:.1f}秒後にリトライします..."
                        )
                        await asyncio.sleep(delay)
                        continue
                raise

        # Responses APIの出力を取得（長文対応）
        output_text = getattr(response, "output_text", None)
        if not output_text:
            # output_textがない場合はoutputから取得
            output = getattr(response, "output", None)
            if output:
                chunks = []
                for item in output:
                    content = getattr(item, "content", None) or (item.get("content") if isinstance(item, dict) else None)
                    if content:
                        for part in content:
                            text = getattr(part, "text", None) or (part.get("text") if isinstance(part, dict) else None)
                            if text:
                                chunks.append(text)
                output_text = "".join(chunks)

        # 長文レスポンスの処理（output_textがまだ空の場合）
        if not output_text:
            # その他の方法でレスポンスを取得
            if hasattr(response, "text"):
                output_text = response.text
            elif hasattr(response, "content"):
                content = response.content
                if isinstance(content, str):
                    output_text = content
                elif isinstance(content, list):
                    output_text = "".join(str(item) for item in content)

        # トークン使用量を取得
        usage = getattr(response, "usage", None) or (response.get("usage") if isinstance(response, dict) else None)
        if isinstance(usage, dict):
            total_tokens = usage.get("total_tokens") or (usage.get("input_tokens", 0) + usage.get("output_tokens", 0))
        else:
            total_tokens = getattr(usage, "total_tokens", None) or 0

        if not output_text:
            raise Exception("Responses APIの出力が空です")

        # 長文レスポンスのログ出力
        if len(output_text) > 10000:
            logger.info(f"  長文レスポンスを取得しました（{len(output_text)}文字）")

        logger.info(f"✓ Responses API呼び出し成功 (トークン: {total_tokens})")
        return output_text, total_tokens or 0

    async def _call_chat_completions_api(
        self,
        model_name: str,
        messages: list,
        temperature: float,
        max_tokens: Optional[int],
    ) -> Tuple[str, int]:
        """Chat Completions API を呼び出す（通常モデル向け）"""
        if not self.client:
            raise RuntimeError("OpenAI クライアントが未初期化です")

        kwargs = {
            "model": model_name,
            "messages": messages,
        }

        # GPT-5.1など、max_completion_tokensを使用する必要があるモデル
        if max_tokens:
            if model_name in self.MAX_COMPLETION_TOKENS_MODELS:
                kwargs["max_completion_tokens"] = max_tokens
            else:
                kwargs["max_tokens"] = max_tokens

        # gpt-5など、temperatureをサポートしないモデルは除外
        if model_name not in self.NO_TEMPERATURE_MODELS:
            if temperature is not None:
                kwargs["temperature"] = temperature
        else:
            logger.info(f"  {model_name}はtemperature非対応のため除外")

        logger.info(f"→ Chat Completions API呼び出し: {model_name}")

        # デバッグモード時のみ詳細な情報を出力
        if settings.is_debug_mode:
            logger.debug(f"  Messages: {len(messages)} messages")
            logger.debug(f"  Max tokens: {max_tokens}")
            logger.debug(f"  Temperature: {temperature}")
            logger.debug(f"  API parameters: {kwargs}")

        try:
            response = await self.client.chat.completions.create(**kwargs)

            # 長文レスポンス対応：contentがNoneの場合の処理
            message = response.choices[0].message
            output = message.content

            # contentがNoneの場合、他の方法で取得を試みる
            if output is None:
                if hasattr(message, "text"):
                    output = message.text
                elif hasattr(message, "parts"):
                    parts = message.parts
                    if parts:
                        output = "".join(str(part) for part in parts)

            if output is None:
                raise Exception("Chat Completions APIの出力が空です")

            tokens_used = response.usage.total_tokens

            # 長文レスポンスのログ出力
            if len(output) > 10000:
                logger.info(f"  長文レスポンスを取得しました（{len(output)}文字）")

            logger.info(f"✓ API呼び出し成功 (トークン: {tokens_used})")
            return output, tokens_used

        except Exception as e:
            logger.error(f"✗ Chat Completions API呼び出し失敗: {str(e)}")
            logger.error(f"  エラータイプ: {type(e).__name__}")
            logger.error(f"  モデル: {model_name}")

            # デバッグモード時のみ詳細な情報を出力
            if settings.is_debug_mode:
                if hasattr(e, 'response') and e.response is not None:
                    try:
                        error_detail = e.response.json() if hasattr(e.response, 'json') else str(e.response)
                        logger.debug(f"  レスポンス詳細: {error_detail}")
                    except Exception:
                        logger.debug(f"  レスポンス: {e.response}")
                import traceback
                logger.debug(f"  トレースバック:\n{traceback.format_exc()}")

            # より詳細なエラーメッセージを提供
            err_msg = str(e)
            if "does not exist" in err_msg or "model_not_found" in err_msg:
                raise Exception(
                    f"モデル '{model_name}' は存在しないか、アクセス権限がありません。"
                    f"利用可能なモデルを確認してください。"
                )
            raise

    async def execute_prompt(
        self,
        prompt: str,
        model: str = "gpt-4o",
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
    ) -> dict:
        """
        プロンプトを実行

        Args:
            prompt: 実行するプロンプト
            model: 使用するモデル
            temperature: 温度パラメータ
            max_tokens: 最大トークン数（Noneの場合は長文対応のデフォルト値を使用）

        Returns:
            {
                "output": str,
                "model": str,
                "tokens": int
            }
        """
        logger.info(f"{'='*60}")
        logger.info("プロンプト実行開始")
        logger.info(f"  モデル: {model}")
        logger.info(f"  プロンプト長: {len(prompt)} 文字")

        # デバッグモード時のみ詳細な情報を出力
        if settings.is_debug_mode:
            logger.debug(f"  プロンプト（最初の200文字）: {prompt[:200]}...")

        # 長文プロンプトの警告
        if len(prompt) > 100000:  # 10万文字以上
            logger.warning(f"  ⚠ 非常に長いプロンプトです（{len(prompt)}文字）。処理に時間がかかる可能性があります。")

        # max_tokensが指定されていない場合、長文対応のデフォルト値を設定
        if max_tokens is None:
            # 推論モデルはより大きな値を設定
            if self._is_reasoning_model(model):
                max_tokens = 32768  # 推論モデルは長文出力に対応
            else:
                max_tokens = 16384  # 通常モデルも長文出力に対応

        # 本番環境でのデモモード禁止
        if settings.is_production and self.demo_mode:
            raise Exception(
                "OpenAI APIキー未設定のため本番では実行できません。"
                "OPENAI_API_KEY を設定してください。"
            )

        # デモモード
        if self.demo_mode:
            logger.warning("⚠ デモモードで実行")
            return {
                "output": (
                    f"【デモモード】\n\n"
                    f"OpenAI APIキーが設定されていないため、実際のAI応答は生成されません。\n\n"
                    f"実際に使用するには、.envファイルにOPENAI_API_KEYを設定してください。\n\n"
                    f"入力プロンプト（最初の100文字）:\n{prompt[:100]}..."
                ),
                "model": f"{model} (demo)",
                "tokens": 100
            }

        # メッセージの構築
        messages = []
        if settings.ENABLE_PROMPT_GUARDRAILS:
            messages.append({"role": "system", "content": settings.GUARDRAIL_PREFIX})
            logger.debug("  ガードレール有効")
        messages.append({"role": "user", "content": prompt})

        try:
            # 推論モデルの場合はResponses API、それ以外はChat Completions API
            if self._is_reasoning_model(model):
                logger.info(f"  推論モデル: {model}")
                output, tokens_used = await self._call_responses_api(
                    model_name=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            else:
                logger.info(f"  通常モデル: {model}")
                output, tokens_used = await self._call_chat_completions_api(
                    model_name=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

            logger.info(f"✓ プロンプト実行成功")
            logger.info(f"{'='*60}")

            return {
                "output": output,
                "model": model,
                "tokens": tokens_used
            }

        except Exception as e:
            logger.error(f"✗ プロンプト実行失敗: {str(e)}")
            logger.error(f"  エラータイプ: {type(e).__name__}")

            # デバッグモード時のみ詳細なトレースバックを出力
            if settings.is_debug_mode:
                import traceback
                logger.debug(f"  トレースバック:\n{traceback.format_exc()}")

            logger.error(f"{'='*60}")

            err_msg = str(e)
            error_detail = err_msg
            if hasattr(e, '__cause__') and e.__cause__:
                error_detail = f"{err_msg} (原因: {str(e.__cause__)})"
            raise Exception(f"OpenAI API実行エラー: {error_detail}")

    async def execute_streaming(
        self,
        prompt: str,
        model: str = "gpt-4o",
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        messages_override: list = None,
    ):
        """
        ストリーミングでプロンプトを実行

        Args:
            prompt: 実行するプロンプト
            model: 使用するモデル
            temperature: 温度パラメータ
            max_tokens: 最大トークン数

        Yields:
            生成されたテキストのチャンク
        """
        logger.info(f"{'='*60}")
        logger.info("ストリーミング実行開始")
        logger.info(f"  モデル: {model}")

        # 推論モデルはストリーミング非対応のためフォールバック
        if self._is_reasoning_model(model):
            logger.info("  推論モデルのため非ストリーミングにフォールバック")
            result = await self.execute_prompt(
                prompt=prompt,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            yield result["output"]
            return

        if not self.client:
            raise RuntimeError("OpenAI クライアントが未初期化です")

        if messages_override:
            messages = messages_override
        else:
            messages = []
            if settings.ENABLE_PROMPT_GUARDRAILS:
                messages.append({"role": "system", "content": settings.GUARDRAIL_PREFIX})
            messages.append({"role": "user", "content": prompt})

        kwargs = {
            "model": model,
            "messages": messages,
            "stream": True
        }

        # GPT-5.1など、max_completion_tokensを使用する必要があるモデル
        if max_tokens:
            if model in self.MAX_COMPLETION_TOKENS_MODELS:
                kwargs["max_completion_tokens"] = max_tokens
            else:
                kwargs["max_tokens"] = max_tokens

        if model not in self.NO_TEMPERATURE_MODELS:
            if temperature is not None:
                kwargs["temperature"] = temperature

        logger.info("→ ストリーミングAPI呼び出し")
        try:
            stream = await self.client.chat.completions.create(**kwargs)

            chunk_count = 0
            total_length = 0
            tokens_used = 0
            last_chunk = None

            async for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content is not None:
                    content = delta.content
                    chunk_count += 1
                    total_length += len(content)
                    yield content

                # 最後のチャンクを保持（usage情報が含まれる可能性がある）
                last_chunk = chunk

                # usage情報が含まれている場合は取得
                if hasattr(chunk, "usage") and chunk.usage:
                    usage = chunk.usage
                    if hasattr(usage, "total_tokens"):
                        tokens_used = usage.total_tokens
                    elif isinstance(usage, dict):
                        tokens_used = usage.get("total_tokens", 0)

            # 最後のチャンクからusage情報を取得（まだ取得できていない場合）
            if tokens_used == 0 and last_chunk:
                if hasattr(last_chunk, "usage") and last_chunk.usage:
                    usage = last_chunk.usage
                    if hasattr(usage, "total_tokens"):
                        tokens_used = usage.total_tokens
                    elif isinstance(usage, dict):
                        tokens_used = usage.get("total_tokens", 0)

            logger.info(f"✓ ストリーミング完了 ({chunk_count} チャンク, 合計 {total_length} 文字, トークン: {tokens_used})")
            logger.info(f"{'='*60}")

            # トークン数が取得できなかった場合、tiktokenライブラリで計算
            if tokens_used == 0:
                try:
                    import tiktoken
                    # モデルに応じたエンコーダーを取得
                    try:
                        encoding = tiktoken.encoding_for_model(model)
                    except KeyError:
                        # モデルが見つからない場合はcl100k_baseを使用（GPT-4など）
                        encoding = tiktoken.get_encoding("cl100k_base")

                    # プロンプトと出力のトークン数を計算
                    prompt_tokens = len(encoding.encode(prompt))
                    # 出力はストリーミングで取得済みなので、ここでは概算
                    # 実際には、ストリーミング完了後に出力全体のトークン数を計算する必要がある
                    # ただし、出力は既にyieldされているため、ここでは計算できない
                    # そのため、execution_tasks.pyで計算する
                    tokens_used = prompt_tokens  # 暫定的にプロンプトトークンのみ
                except ImportError:
                    logger.warning("tiktokenライブラリがインストールされていません。トークン数の計算をスキップします。")
                except Exception as e:
                    logger.warning(f"トークン数の計算に失敗: {str(e)}")

        except Exception as e:
            logger.error(f"✗ ストリーミング失敗: {str(e)}")
            # フォールバック
            result = await self.execute_prompt(
                prompt=prompt,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens
            )
            yield result["output"]


# シングルトンインスタンス
openai_service = OpenAIService()
