"""
Executor: ローカル環境の API キーで LLM を呼び出す

OpenAI / Gemini SDK を直接使用して、バンドルの final_prompt を実行する。
リトライ、tiktoken トークン計算、エラー分類を含む。

External CLI 経路 (claude / codex / generic) は `_execute_external_cli`
にディスパッチされる。Rust 実装 (desktop/src-tauri/src/external_cli_runner.rs)
の契約をミラーしているので、artifact provenance は Rust 経路と同形になる。
"""
import asyncio
import logging
import os
import shlex
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

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
    # external_cli 実行は構造化された meta dict を返し、backend が
    # build_external_cli_provenance() で利用する。HTTP 実行では None のまま。
    # uploader 経由でラウンドトリップし、desktop (Rust) ランタイムと同形の
    # 来歴をアーティファクトに持たせる。
    external_cli_meta: Optional[dict] = None
    provider_meta: Optional[dict] = None


# ---------------------------------------------------------------------------
# OpenAI モデル
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
# Claude モデル
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

    External CLI バンドル (`bundle["execution_kind"] == "external_cli"`) は
    `_execute_external_cli` に分岐する。HTTP/internal バンドルは従来どおり
    OpenAI / Gemini / Claude のいずれかの provider SDK を呼ぶ。

    Args:
        bundle: サーバーから取得した run bundle
        model_override: モデルを上書き（CLI --model で指定）
        on_chunk: チャンクコールバック async (chunk: str) -> None

    Returns:
        ExecutionResult
    """
    # ── External CLI 経路 ────────────────────────────────────────────
    # routing 層 (backend/coordinator_service.py) が
    # execution_kind=external_cli を返した場合、bundle に
    # external_cli_payload が同梱される。HTTP provider 用の
    # final_prompt / model キーは存在しないか無視される。
    if bundle.get("execution_kind") == "external_cli":
        payload = bundle.get("external_cli_payload")
        if not isinstance(payload, dict):
            raise ValueError(
                "external_cli bundle missing external_cli_payload"
            )
        return await _execute_external_cli(payload, on_chunk=on_chunk)

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
        http_options={"headers": {"Referer": "https://nexmagi.local"}},
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


# ============================================================================
# External CLI 実行器 — claude / codex / generic
#
# Tauri Rust ランナーの契約 (desktop/src-tauri/src/external_cli_runner.rs)
# をミラーし、backend の build_external_cli_provenance() が desktop 経路と
# 同じ形式でメタデータを利用できるようにする。
#
# 本番向け堅牢化（Rust と同期必須）:
# - cwd 検証: 絶対パス、存在確認、ディレクトリ確認
# - subprocess: shell=False、argv リスト（シェルインジェクション防止）
# - 環境変数: 最小限の許可リスト（PATH, HOME, USER, LANG, LC_ALL,
#   LOGNAME, TERM, TZ）; worker 環境のシークレットは継承しない
# - タイムアウト: asyncio.wait_for で強制; タイムアウト時はプロセスグループ
#   全体を SIGKILL（start_new_session=True で killpg 可能にする）
# - 出力切り詰め: stdout/stderr を MAX_STREAM_BYTES（各 1MB、Rust と同値）で制限
# - プロンプトは stdin 経由のみで送信（argv に埋め込まない）し、
#   `ps` 出力と command_line_preview に表示させない
# - command_line_preview は shlex クォートして 400 文字で切り詰め、
#   プロンプトはプレビューに含めない
# - ログにプロンプト全文は出力しない
# - approval_policy="ask_before_shell" はここでは read_only に格下げ。
#   Python worker にはユーザーに確認する UI がないため。これは Rust 側の
#   保守的なデフォルトと一致する。対話的承認が必要なステップは desktop
#   ランタイムで実行すること。
# ============================================================================

# ステータス列挙文字列 —
# desktop/src-tauri/src/external_cli_traits.rs:ExternalCliExecutionStatus と一致必須
EXTERNAL_CLI_STATUS_SUCCEEDED = "succeeded"
EXTERNAL_CLI_STATUS_FAILED = "failed"
EXTERNAL_CLI_STATUS_TIMED_OUT = "timed_out"
EXTERNAL_CLI_STATUS_CANCELLED = "cancelled"
EXTERNAL_CLI_STATUS_MISSING_BINARY = "missing_binary"
EXTERNAL_CLI_STATUS_AUTH_REQUIRED = "auth_required"
EXTERNAL_CLI_STATUS_CAPABILITY_MISMATCH = "capability_mismatch"
EXTERNAL_CLI_STATUS_UNSUPPORTED = "unsupported"

MAX_STREAM_BYTES = 1024 * 1024  # 1 MB per stream, matching Rust runner
MAX_COMMAND_PREVIEW_CHARS = 400
DEFAULT_EXTERNAL_CLI_TIMEOUT_MS = 15 * 60 * 1000  # 15 min default


def _validate_external_cli_cwd(cwd_value: Any) -> str:
    """Rust の runner.rs:validate_cwd() をミラーする。

    ルール:
    - 空でない文字列であること
    - 絶対パスであること
    - 存在すること
    - ディレクトリであること

    注意: Rust は追加で「HOME 配下」を強制するが、ここでは強制しない。
    コンテナ環境ではワーカーユーザーの HOME が /root や /home/<svc-user> で、
    正当なワークスペースは /tmp や /var 配下にあるため。コンテナ分離が
    同等の境界を提供する。Python で再度有効化する場合は、seed の cwd_hint
    も HOME 配下に変更すること。
    """
    if not isinstance(cwd_value, str) or not cwd_value:
        raise ValueError("external_cli payload missing cwd")
    p = Path(cwd_value)
    if not p.is_absolute():
        raise ValueError(f"external_cli cwd must be absolute: {cwd_value}")
    if not p.exists():
        raise ValueError(f"external_cli cwd does not exist: {cwd_value}")
    if not p.is_dir():
        raise ValueError(f"external_cli cwd is not a directory: {cwd_value}")
    return str(p)


def _build_minimal_env() -> dict:
    """起動する CLI 用の最小限の環境変数を構築する。

    CLI がバイナリを見つけ、ユーザー設定を読み、i18n を描画するために
    必要な最小限のセットだけを残し、それ以外は意図的に除外する。
    ワーカープロセスの環境には OPENAI_API_KEY / GEMINI_API_KEY / DB 認証情報
    が含まれ得るが、それらを子 CLI プロセスに漏洩させてはならない。

    CLI 自身の認証（例: ~/.config/claude）は HOME 経由でディスクから読み取る。
    """
    allowlist = (
        "PATH", "HOME", "USER", "LOGNAME",
        "LANG", "LC_ALL", "LC_CTYPE",
        "TERM", "TZ",
        # Claude Code が参照する環境変数
        "CLAUDE_CONFIG_DIR",
    )
    env = {}
    for key in allowlist:
        val = os.environ.get(key)
        if val is not None:
            env[key] = val
    if "PATH" not in env:
        env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    return env


def _truncate_stream(data: bytes) -> tuple[str, bool]:
    """キャプチャしたストリームを Rust と同じ方法でデコード＋切り詰めする。"""
    truncated = False
    if len(data) > MAX_STREAM_BYTES:
        data = data[:MAX_STREAM_BYTES]
        truncated = True
    text = data.decode("utf-8", errors="replace")
    return text, truncated


def _build_command_preview(command: str, args: list[str]) -> str:
    """プロンプトを含まない shlex クォート済みプレビュー。Rust と同様に
    `command_line_preview` は監査/UI 表示用であり、再実行用ではない。
    """
    parts = [command, *args]
    preview = " ".join(shlex.quote(p) for p in parts)
    if len(preview) > MAX_COMMAND_PREVIEW_CHARS:
        preview = preview[: MAX_COMMAND_PREVIEW_CHARS - 3] + "..."
    return preview


def _format_external_cli_output(
    runtime: str,
    status: str,
    exit_code: Optional[int],
    stdout: str,
    stderr: str,
) -> str:
    """finalize_execution が Execution.output_data に格納する人間可読な
    `output` フィールドを構築する。Rust ランタイムと同じレイアウトにし、
    アーティファクトビューアがどちらのソースでも同一に表示できるようにする。
    """
    parts = [
        f"[external_cli {runtime}]",
        f"status: {status}",
    ]
    if exit_code is not None:
        parts.append(f"exit_code: {exit_code}")
    parts.append("--- stdout ---")
    parts.append(stdout if stdout else "(empty)")
    parts.append("--- stderr ---")
    parts.append(stderr if stderr else "(empty)")
    return "\n".join(parts)


async def _execute_external_cli(
    payload: dict,
    on_chunk=None,
) -> ExecutionResult:
    """外部 CLI（claude / codex / generic）を起動し出力をキャプチャする。
    Tauri Rust ランナーの契約をミラーする。

    `payload` は
    `backend/app/services/external_cli_adapters.build_external_cli_payload`
    が生成する dict。

    返される ExecutionResult の `external_cli_meta` に、backend が
    POST /complete で期待する完全な来歴 dict を格納する。
    """
    runtime = str(payload.get("runtime") or "generic")
    adapter_id = payload.get("adapter_id")
    adapter_name = payload.get("adapter_name")
    command = str(payload.get("command") or "claude")
    args_raw = payload.get("args") or []
    if not isinstance(args_raw, list):
        raise ValueError("external_cli payload args must be a list")
    args = [str(a) for a in args_raw]

    prompt = str(payload.get("prompt") or "")
    task_id = payload.get("task_id")
    workflow_run_id = payload.get("workflow_run_id")
    task_role = payload.get("task_role")
    selection_reason = payload.get("selection_reason")
    approval_policy = payload.get("approval_policy")
    required_capabilities = list(payload.get("required_capabilities") or [])
    allow_writes = bool(payload.get("allow_writes", False))
    allow_shell = bool(payload.get("allow_shell", False))
    workspace_id = payload.get("workspace_id")
    workspace_mode = payload.get("workspace_mode")
    workspace_path = payload.get("workspace_path")

    timeout_ms = int(payload.get("timeout_ms") or DEFAULT_EXTERNAL_CLI_TIMEOUT_MS)
    if timeout_ms <= 0:
        timeout_ms = DEFAULT_EXTERNAL_CLI_TIMEOUT_MS
    timeout_s = timeout_ms / 1000.0

    # 承認ポリシー格下げ: Python worker には対話的 UI がないため、
    # `ask_before_shell` を強制的に read_only にする。承認者が
    # 接続されていない場合の Rust ランナーの「デフォルト拒否」方針と一致。
    if approval_policy == "ask_before_shell":
        logger.info(
            "external_cli: ask_before_shell approval requested but no "
            "approver wired in worker — downgrading allow_shell to false"
        )
        allow_shell = False

    cwd = _validate_external_cli_cwd(workspace_path or payload.get("cwd"))
    env = _build_minimal_env()

    started_at_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    command_preview = _build_command_preview(command, args)
    logger.info(
        "external_cli spawn: runtime=%s adapter=%s task_id=%s cwd=%s "
        "preview=%r approval=%s allow_writes=%s allow_shell=%s",
        runtime, adapter_name, task_id, cwd, command_preview,
        approval_policy, allow_writes, allow_shell,
    )

    spawn_start = time.monotonic()
    status = EXTERNAL_CLI_STATUS_FAILED
    exit_code: Optional[int] = None
    stdout_text = ""
    stderr_text = ""
    stdout_truncated = False
    stderr_truncated = False
    capability_check_passed = True  # backend already enforced this; we don't re-check

    try:
        proc = await asyncio.create_subprocess_exec(
            command,
            *args,
            cwd=cwd,
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            # 新しいプロセスグループで起動し、タイムアウト時にツリー全体を
            # kill できるようにする。これがないと claude が子 node/npx
            # プロセスを孤児にする可能性がある。
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        finished_at_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        duration_ms = int((time.monotonic() - spawn_start) * 1000)
        logger.warning("external_cli missing binary: command=%s err=%s", command, exc)
        meta = _build_external_cli_meta(
            adapter_id=adapter_id, adapter_name=adapter_name,
            runtime=runtime, status=EXTERNAL_CLI_STATUS_MISSING_BINARY,
            cwd=cwd, command=command, command_preview=command_preview,
            exit_code=None, duration_ms=duration_ms,
            stdout_truncated=False, stderr_truncated=False,
            changed_files=[], capability_check_passed=capability_check_passed,
            task_id=task_id, workflow_run_id=workflow_run_id,
            selection_reason=selection_reason, approval_policy=approval_policy,
            required_capabilities=required_capabilities,
            allow_writes=allow_writes, allow_shell=allow_shell,
            workspace_id=workspace_id, workspace_mode=workspace_mode,
            workspace_path=workspace_path,
            started_at=started_at_iso, finished_at=finished_at_iso,
        )
        out_text = _format_external_cli_output(
            runtime, EXTERNAL_CLI_STATUS_MISSING_BINARY, None, "", str(exc)
        )
        return ExecutionResult(
            output=out_text,
            model_used=runtime,
            tokens_used=0,
            execution_time_ms=duration_ms,
            token_accounting_source="unavailable",
            external_cli_meta=meta,
        )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(input=prompt.encode("utf-8")),
            timeout=timeout_s,
        )
        exit_code = proc.returncode
        status = (
            EXTERNAL_CLI_STATUS_SUCCEEDED if exit_code == 0
            else EXTERNAL_CLI_STATUS_FAILED
        )
        stdout_text, stdout_truncated = _truncate_stream(stdout_bytes)
        stderr_text, stderr_truncated = _truncate_stream(stderr_bytes)
    except asyncio.TimeoutError:
        # リーダーだけでなくプロセスグループ全体を kill する。
        try:
            import signal
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception as kill_err:  # noqa: BLE001
            logger.warning("external_cli kill failed: %s", kill_err)
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            pass
        status = EXTERNAL_CLI_STATUS_TIMED_OUT
        exit_code = None
        # kill 前にバッファされていた出力を可能な限りキャプチャする。
        try:
            partial_out = await proc.stdout.read() if proc.stdout else b""
            partial_err = await proc.stderr.read() if proc.stderr else b""
            stdout_text, stdout_truncated = _truncate_stream(partial_out)
            stderr_text, stderr_truncated = _truncate_stream(partial_err)
        except Exception:
            pass
    except Exception as exc:  # noqa: BLE001
        logger.exception("external_cli unexpected error: %s", exc)
        status = EXTERNAL_CLI_STATUS_FAILED
        exit_code = None
        stderr_text = f"executor error: {type(exc).__name__}: {exc}"

    duration_ms = int((time.monotonic() - spawn_start) * 1000)
    finished_at_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    logger.info(
        "external_cli finished: runtime=%s status=%s exit_code=%s duration_ms=%s "
        "stdout_bytes=%s stderr_bytes=%s",
        runtime, status, exit_code, duration_ms,
        len(stdout_text), len(stderr_text),
    )

    meta = _build_external_cli_meta(
        adapter_id=adapter_id, adapter_name=adapter_name,
        runtime=runtime, status=status,
        cwd=cwd, command=command, command_preview=command_preview,
        exit_code=exit_code, duration_ms=duration_ms,
        stdout_truncated=stdout_truncated, stderr_truncated=stderr_truncated,
        changed_files=[],  # Python worker はまだ fs スナップショットを取らない
        capability_check_passed=capability_check_passed,
        task_id=task_id, workflow_run_id=workflow_run_id,
        selection_reason=selection_reason, approval_policy=approval_policy,
        required_capabilities=required_capabilities,
        allow_writes=allow_writes, allow_shell=allow_shell,
        workspace_id=workspace_id, workspace_mode=workspace_mode,
        workspace_path=workspace_path,
        started_at=started_at_iso, finished_at=finished_at_iso,
    )

    out_text = _format_external_cli_output(
        runtime, status, exit_code, stdout_text, stderr_text
    )

    # CLI が失敗した場合は raise してデーモンのエラーパスを実行し、
    # DB で実行を失敗としてマークする。このブランチでは meta dict は
    # 失われる（uploader.upload_error は運ばない）が、失敗ログと
    # worker ログが原因を示すため許容範囲。meta は成功時のみ永続化する。
    if status not in (EXTERNAL_CLI_STATUS_SUCCEEDED,):
        # 例外の属性としてサイドチャネルで meta を埋め込む。呼び出し側が
        # 必要なら抽出できるが、公開契約は「失敗時は raise」。
        err = RuntimeError(
            f"external_cli {runtime} status={status} exit_code={exit_code}"
        )
        setattr(err, "external_cli_meta", meta)
        setattr(err, "external_cli_output", out_text)
        raise err

    return ExecutionResult(
        output=out_text,
        model_used=runtime,
        tokens_used=0,
        execution_time_ms=duration_ms,
        token_accounting_source="unavailable",
        external_cli_meta=meta,
    )


def _build_external_cli_meta(
    *,
    adapter_id, adapter_name, runtime, status, cwd, command, command_preview,
    exit_code, duration_ms, stdout_truncated, stderr_truncated, changed_files,
    capability_check_passed, task_id, workflow_run_id, selection_reason,
    approval_policy, required_capabilities, allow_writes, allow_shell,
    workspace_id, workspace_mode, workspace_path, started_at, finished_at,
) -> dict:
    """backend の build_external_cli_provenance() が利用する dict を構築する。
    キーは安定した契約であり、Rust の
    `external_cli_runtime.rs::build_external_cli_meta` とミラー必須。
    """
    return {
        "adapter_id": adapter_id,
        "adapter_name": adapter_name,
        "runtime": runtime,
        "status": status,
        "cwd": cwd,
        "command": command,
        "command_line_preview": command_preview,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
        "changed_files": changed_files,
        "capability_check_passed": capability_check_passed,
        "task_id": task_id,
        "workflow_run_id": workflow_run_id,
        "selection_reason": selection_reason,
        "approval_policy": approval_policy,
        "required_capabilities": required_capabilities,
        "allow_writes": allow_writes,
        "allow_shell": allow_shell,
        "workspace_id": workspace_id,
        "workspace_mode": workspace_mode,
        "workspace_path": workspace_path,
        "started_at": started_at,
        "finished_at": finished_at,
        "executor_source": "local_worker.python",
    }
