"""
Executor: ローカル環境の API キーで LLM を呼び出す

OpenAI / Gemini SDK を直接使用して、バンドルの final_prompt を実行する。
リトライ、tiktoken トークン計算、エラー分類を含む。
"""
import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

from .config import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# リトライ設定（Celery から移植）
# ---------------------------------------------------------------------------
MAX_RETRIES = 3
RETRY_DELAY = 10  # 秒

# リトライ不可能なエラーパターン
NON_RETRYABLE_PATTERNS = [
    "authentication", "invalid api key", "model_not_found",
    "does not exist", "認証", "スキルが見つかりません",
]


def _is_retryable(error: Exception) -> bool:
    """エラーがリトライ可能か判定"""
    msg = str(error).lower()
    if any(p in msg for p in NON_RETRYABLE_PATTERNS):
        return False
    # ネットワーク/タイムアウト系はリトライ
    retryable_patterns = ["timeout", "timed out", "rate limit", "rate_limit",
                          "service unavailable", "resource exhausted", "connection"]
    if any(p in msg for p in retryable_patterns):
        return True
    if isinstance(error, (ConnectionError, TimeoutError, OSError)):
        return True
    return False


def _count_tokens(text: str, model: str) -> int:
    """tiktoken でトークン数を計算（フォールバック: 文字数概算）"""
    try:
        import tiktoken
        try:
            encoding = tiktoken.encoding_for_model(model)
        except KeyError:
            encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"tiktoken error: {e}")
    # フォールバック
    return len(text) // 4 if not any(ord(c) > 127 for c in text[:100]) else len(text) // 3


@dataclass
class ExecutionResult:
    output: str
    model_used: str
    tokens_used: int
    execution_time_ms: int
    token_accounting_source: str = "unavailable"


# ---------------------------------------------------------------------------
# OpenAI Models
# ---------------------------------------------------------------------------
OPENAI_MODELS = {
    "gpt-5.4", "gpt-5.4-mini", "gpt-5.4-pro", "gpt-5.4-thinking",
    "gpt-5.2", "gpt-5.2-pro", "gpt-5.2-thinking",
    "o4-mini",                        # 推論/コード コスパ
}

# Responses API が必要なモデル
OPENAI_REASONING_MODELS = {"gpt-5.2-pro", "gpt-5.4-pro", "o4-mini"}

# Thinking モデル（reasoning_effort=high にマップ）
OPENAI_THINKING_MODELS = {"gpt-5.2-thinking", "gpt-5.4-thinking"}

GEMINI_MODELS = {
    "gemini-3.1-pro-preview", "gemini-3.1-pro-preview-deep-think",
    "gemini-3-pro-preview", "gemini-3-pro-preview-deep-think",
    "gemini-2.5-pro", "gemini-2.5-flash",  # コスパ
}

# ---------------------------------------------------------------------------
# Claude Models
# ---------------------------------------------------------------------------
CLAUDE_MODELS = {
    "claude-sonnet-4-6", "claude-sonnet-4-6-thinking",
    "claude-opus-4-6", "claude-opus-4-6-thinking",
    "claude-haiku-4-5",
}


def classify_executor_failure(error: Exception) -> str:
    msg = str(error).lower()
    if isinstance(error, TimeoutError) or "timeout" in msg or "timed out" in msg:
        return "timeout"
    if isinstance(error, ConnectionError) or "connection" in msg or "unreachable" in msg:
        return "connection_error"
    if isinstance(error, OSError):
        return "os_error"
    if (
        "api key" in msg
        or "api キー" in msg
        or "設定されていません" in msg
        or "認証" in msg
        or "authentication" in msg
    ):
        return "missing_credentials"
    if "サポートされていないモデル" in msg or "model_not_found" in msg or "does not exist" in msg:
        return "unsupported_model"
    if "インストールされていません" in msg or "package" in msg:
        return "dependency_missing"
    return "unknown_error"


async def execute_bundle_once(
    bundle: dict,
    model_override: str = None,
    on_chunk=None,
) -> ExecutionResult:
    """
    バンドルの内容に基づいて LLM を呼び出す（リトライ付き）。

    Args:
        bundle: サーバーから取得した run bundle
        model_override: モデルを上書き (CLI --model で指定)
        on_chunk: チャンクコールバック async (chunk: str) → None

    Returns:
        ExecutionResult
    """
    ALL_SUPPORTED_MODELS = OPENAI_MODELS | GEMINI_MODELS | CLAUDE_MODELS
    model = model_override or bundle["model"]
    if model not in ALL_SUPPORTED_MODELS:
        raise ValueError(
            f"サポートされていないモデル: {model}\n"
            f"利用可能: {', '.join(sorted(ALL_SUPPORTED_MODELS))}"
        )
    prompt = bundle["final_prompt"]
    enable_deep_think = bundle.get("enable_deep_think", True)

    bundle_keys = bundle.get("api_keys") or {}
    openai_key = bundle_keys.get("openai") or config.openai_api_key
    gemini_key = bundle_keys.get("gemini") or config.gemini_api_key
    anthropic_key = bundle_keys.get("anthropic") or config.anthropic_api_key

    start = time.time()
    if model in OPENAI_MODELS:
        result = await _execute_openai(prompt, model, api_key=openai_key, on_chunk=on_chunk)
    elif model in GEMINI_MODELS:
        result = await _execute_gemini(prompt, model, enable_deep_think, api_key=gemini_key, on_chunk=on_chunk)
    elif model in CLAUDE_MODELS:
        result = await _execute_claude(prompt, model, api_key=anthropic_key, on_chunk=on_chunk)
    else:
        raise ValueError(f"サポートされていないモデル: {model}")

    elapsed_ms = int((time.time() - start) * 1000)
    result.execution_time_ms = elapsed_ms
    return result


async def execute_bundle(
    bundle: dict,
    model_override: str = None,
    on_chunk=None,
) -> ExecutionResult:
    prompt = bundle["final_prompt"]
    model = model_override or bundle["model"]
    last_error = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            result = await execute_bundle_once(bundle, model_override=model_override, on_chunk=on_chunk)
            if result.token_accounting_source != "provider_usage":
                prompt_tokens = _count_tokens(prompt, model)
                output_tokens = _count_tokens(result.output, model)
                result.tokens_used = prompt_tokens + output_tokens
                result.token_accounting_source = "tiktoken_estimate"
            return result
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES and _is_retryable(e):
                delay = RETRY_DELAY * (attempt + 1)
                logger.warning(f"Retry {attempt + 1}/{MAX_RETRIES} in {delay}s: {e}")
                await asyncio.sleep(delay)
            else:
                raise

    raise last_error


async def _execute_openai(prompt: str, model: str, api_key: str = None, on_chunk=None) -> ExecutionResult:
    """OpenAI API で実行（ストリーミング対応）"""
    try:
        from openai import AsyncOpenAI
    except ImportError:
        raise RuntimeError("openai パッケージがインストールされていません: pip install openai")

    if not api_key:
        api_key = config.openai_api_key
    if not api_key:
        raise ValueError("OpenAI API キーが設定されていません（ユーザー設定または OPENAI_API_KEY 環境変数）")

    client = AsyncOpenAI(api_key=api_key, timeout=config.request_timeout)

    actual_model = model
    reasoning_effort = None
    if model in OPENAI_THINKING_MODELS:
        actual_model = model.replace("-thinking", "")
        reasoning_effort = "high"

    # Responses API モデル（ストリーミング非対応）
    if model in OPENAI_REASONING_MODELS:
        resp = await client.responses.create(
            model=actual_model,
            input=[{"role": "user", "content": prompt}],
            max_output_tokens=16384,
        )
        output = resp.output_text or ""
        tokens_used = (resp.usage.input_tokens or 0) + (resp.usage.output_tokens or 0) if resp.usage else 0
        token_accounting_source = "provider_usage" if resp.usage else "unavailable"
        if on_chunk and output:
            await on_chunk(output)
    else:
        # Chat Completions API（ストリーミング）
        kwargs = {
            "model": actual_model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
        }
        if actual_model.startswith("gpt-5"):
            kwargs["max_completion_tokens"] = 16384
        else:
            kwargs["max_tokens"] = 4096
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort

        output = ""
        tokens_used = 0
        stream = await client.chat.completions.create(**kwargs)
        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                output += delta.content
                if on_chunk:
                    await on_chunk(delta.content)
            if hasattr(chunk, "usage") and chunk.usage:
                tokens_used = getattr(chunk.usage, "total_tokens", 0)

        if tokens_used == 0:
            tokens_used = len(prompt) // 4 + len(output) // 4
            token_accounting_source = "char_estimate"
        else:
            token_accounting_source = "provider_usage"

    logger.info(f"OpenAI execution complete: model={model}, tokens={tokens_used}, output_len={len(output)}")
    return ExecutionResult(
        output=output,
        model_used=model,
        tokens_used=tokens_used,
        execution_time_ms=0,
        token_accounting_source=token_accounting_source,
    )


async def _execute_gemini(prompt: str, model: str, enable_deep_think: bool, api_key: str = None, on_chunk=None) -> ExecutionResult:
    """Gemini API で実行"""
    try:
        from google import genai as genai_new
    except ImportError:
        raise RuntimeError("google-genai パッケージがインストールされていません: pip install google-genai")

    if not api_key:
        api_key = config.gemini_api_key
    if not api_key:
        raise ValueError("Gemini API キーが設定されていません（ユーザー設定または GEMINI_API_KEY 環境変数）")

    client = genai_new.Client(
        api_key=api_key,
        http_options={"headers": {"Referer": "https://prompt-provision-tool.local"}},
    )

    # モデル名正規化
    model_name = model.replace("-deep-think", "")
    is_deep_think = "deep-think" in model or enable_deep_think

    # Gemini 2.5/3 系の Deep Think 設定
    generation_config = {}
    if is_deep_think and ("2.5" in model_name or "3" in model_name):
        generation_config["thinking_config"] = {"thinking_budget": 24576}

    response = await asyncio.to_thread(
        client.models.generate_content,
        model=model_name,
        contents=prompt,
        config=generation_config if generation_config else None,
    )

    output = ""
    if response.candidates:
        for part in response.candidates[0].content.parts:
            if hasattr(part, "text") and part.text:
                output += part.text
                if on_chunk:
                    await on_chunk(part.text)

    tokens_used = 0
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        um = response.usage_metadata
        tokens_used = (getattr(um, "prompt_token_count", 0) or 0) + (
            getattr(um, "candidates_token_count", 0) or 0
        )
        token_accounting_source = "provider_usage"
    else:
        token_accounting_source = "unavailable"

    if tokens_used == 0:
        tokens_used = len(prompt) // 3 + len(output) // 3
        token_accounting_source = "char_estimate"

    logger.info(f"Gemini execution complete: model={model}, tokens={tokens_used}, output_len={len(output)}")
    return ExecutionResult(
        output=output,
        model_used=model,
        tokens_used=tokens_used,
        execution_time_ms=0,
        token_accounting_source=token_accounting_source,
    )


async def _execute_claude(prompt: str, model: str, api_key: str = None, on_chunk=None) -> ExecutionResult:
    """Claude API で実行（ストリーミング対応）"""
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("anthropic パッケージがインストールされていません: pip install anthropic")

    if not api_key:
        api_key = config.anthropic_api_key
    if not api_key:
        raise ValueError("Anthropic API キーが設定されていません（ユーザー設定または ANTHROPIC_API_KEY 環境変数）")

    client = anthropic.AsyncAnthropic(api_key=api_key, timeout=config.request_timeout)

    # Thinking モデルの場合はサフィックスを除去して extended_thinking を有効化
    actual_model = model
    use_thinking = False
    if model.endswith("-thinking"):
        actual_model = model.replace("-thinking", "")
        use_thinking = True

    max_tokens = 16384
    if "opus" in actual_model:
        max_tokens = 32768

    # Thinking モード時は budget_tokens を設定（max_tokens の80%）
    stream_kwargs = {
        "model": actual_model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if use_thinking:
        stream_kwargs["thinking"] = {
            "type": "enabled",
            "budget_tokens": int(max_tokens * 0.8),
        }

    output = ""
    tokens_used = 0

    async with client.messages.stream(**stream_kwargs) as stream:
        async for text in stream.text_stream:
            output += text
            if on_chunk:
                await on_chunk(text)
        response = await stream.get_final_message()

    if response.usage:
        tokens_used = (response.usage.input_tokens or 0) + (response.usage.output_tokens or 0)
        token_accounting_source = "provider_usage"
    else:
        token_accounting_source = "unavailable"

    if tokens_used == 0:
        tokens_used = len(prompt) // 4 + len(output) // 4
        token_accounting_source = "char_estimate"

    logger.info(f"Claude execution complete: model={model}, tokens={tokens_used}, output_len={len(output)}")
    return ExecutionResult(
        output=output,
        model_used=model,
        tokens_used=tokens_used,
        execution_time_ms=0,
        token_accounting_source=token_accounting_source,
    )
