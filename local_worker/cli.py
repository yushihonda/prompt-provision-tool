#!/usr/bin/env python3
"""
ローカル実行 CLI - 汎用ワークフロー実行フレームワーク

使い方:
  # 常駐ワーカー (UIから実行すると自動で処理)
  python -m local_worker daemon --token $TOKEN

  # スキル一覧
  python -m local_worker list skills

  # ワークフロー一覧
  python -m local_worker list workflows

  # スキル単体実行
  python -m local_worker skill 260 --input '{"topic":"AI最新動向"}'

  # ワークフロー直列実行
  python -m local_worker workflow 3 --mode serial --input '{"topic":"AI記事"}'

  # ワークフロー並列実行
  python -m local_worker workflow 3 --mode parallel --input '{"topic":"AI記事"}'

環境変数 (.env.worker):
  WORKER_SERVER_URL     サーバー URL (default: http://localhost:8000)
  OPENAI_API_KEY        OpenAI API キー
  GEMINI_API_KEY        Gemini API キー
  WORKER_MAX_CONCURRENT 最大同時実行数 (default: 8)
"""
import argparse
import asyncio
import json
import logging
import sys
from typing import Optional

from .config import config

BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"
GREEN = "\033[32m"
CYAN = "\033[36m"


def setup_logging(level: str = "WARNING"):
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.WARNING),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _get_token(args) -> str:
    """JWT トークンを取得"""
    if args.token:
        return args.token

    # dev-login で自動取得
    try:
        import httpx
        resp = httpx.get(f"{config.server_url}/api/auth/dev-login?role=user", timeout=5)
        if resp.status_code == 200:
            token = resp.json()["access_token"]
            username = resp.json().get("username", "?")
            print(f"{DIM}(dev-login: {username}){RESET}")
            return token
    except Exception:
        pass

    print("エラー: --token が必要です", file=sys.stderr)
    print(f"  取得: curl -s {config.server_url}/api/auth/dev-login?role=user | jq -r .access_token", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

async def cmd_list(args):
    from .engine import list_skills, list_workflows
    token = _get_token(args)

    if args.target == "skills":
        skills = await list_skills(token)
        print(f"\n{BOLD}利用可能なスキル ({len(skills)}){RESET}")
        print(f"{'─'*50}")
        for s in skills:
            sid = s.get("id", "?")
            name = s.get("name", "?")
            model = s.get("model_type", "?")
            print(f"  {GREEN}{sid:>4}{RESET}  {name}  {DIM}({model}){RESET}")

    elif args.target == "workflows":
        workflows = await list_workflows(token)
        print(f"\n{BOLD}利用可能なワークフロー ({len(workflows)}){RESET}")
        print(f"{'─'*50}")
        for wf_data in workflows:
            wf = wf_data.get("workflow", wf_data)
            wid = wf.get("id", "?")
            name = wf.get("name", "?")
            skills_list = wf_data.get("skills", [])
            skill_names = ", ".join(s.get("name", "?") for s in skills_list)
            print(f"  {CYAN}{wid:>4}{RESET}  {name}")
            if skill_names:
                print(f"        {DIM}skills: {skill_names}{RESET}")
    print()


# ---------------------------------------------------------------------------
# skill (単体実行)
# ---------------------------------------------------------------------------

async def cmd_skill(args):
    from .engine import execute_skill
    token = _get_token(args)

    input_data = _parse_input(args.input, args.input_file)

    result = await execute_skill(
        skill_id=args.skill_id,
        input_data=input_data,
        token=token,
        model_override=getattr(args, "model", None),
    )

    # 結果表示
    print(f"\n{BOLD}=== 出力 ==={RESET}")
    print(result.output)
    print(f"{BOLD}=== / 出力 ==={RESET}")
    print(f"\n  {DIM}model: {result.model_used}, tokens: {result.tokens_used}, time: {result.execution_time_ms}ms{RESET}")

    # ファイル保存
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(result.output)
        print(f"  保存: {args.output}")


# ---------------------------------------------------------------------------
# workflow (直列/並列)
# ---------------------------------------------------------------------------

async def cmd_workflow(args):
    from .engine import execute_workflow_groups, get_workflow_detail
    token = _get_token(args)

    input_data = _parse_input(args.input, args.input_file)
    model = getattr(args, "model", None)

    results = await execute_workflow_groups(
        args.workflow_id, input_data, token,
        max_concurrent=args.max_concurrent, model_override=model,
    )

    # mode 変数は結果表示で使うので取得しておく
    mode = "groups"

    # 結果サマリー
    print(f"\n{BOLD}=== 全ステップ結果 ==={RESET}")
    for i, r in enumerate(results):
        if r is None:
            continue
        step = r.get("step", f"Step {i+1}")
        status = r.get("status", "success")
        result = r.get("result")
        if status == "success" and result:
            print(f"\n{BOLD}--- {step} ---{RESET}")
            print(result.output[:500])
            if len(result.output) > 500:
                print(f"{DIM}... ({len(result.output) - 500} chars 省略){RESET}")
        elif status == "error":
            print(f"\n{BOLD}--- {step} (エラー) ---{RESET}")
            print(r.get("error", "不明"))

    # 出力ファイル保存
    if args.output and results:
        parts = []
        for r in results:
            if r and r.get("result"):
                parts.append(f"## {r['step']}\n\n{r['result'].output}")
        with open(args.output, "w", encoding="utf-8") as f:
            f.write("\n\n---\n\n".join(parts))
        print(f"\n  保存: {args.output}")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

async def cmd_daemon(args):
    from .daemon import WorkerDaemon
    token = _get_token(args)
    daemon = WorkerDaemon(
        token=token,
        max_concurrent=args.max_concurrent,
        poll_interval=args.poll_interval,
    )
    await daemon.start()


def _parse_input(input_str: Optional[str], input_file: Optional[str]) -> dict:
    if input_file:
        with open(input_file, "r", encoding="utf-8") as f:
            return json.loads(f.read())
    if input_str:
        try:
            return json.loads(input_str)
        except json.JSONDecodeError:
            return {"topic": input_str}
    return {}


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="ローカル実行 CLI - スキル/ワークフロー汎用実行フレームワーク",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--log-level", default="WARNING")
    parser.add_argument("--token", type=str, help="ユーザー JWT (省略時はdev-login)")

    sub = parser.add_subparsers(dest="command")

    # list
    list_p = sub.add_parser("list", help="スキル/ワークフロー一覧")
    list_p.add_argument("target", choices=["skills", "workflows"])

    MODEL_HELP = ("API/モデル指定 (例: gpt-4o, gpt-5.2, gemini-2.5-pro, gemini-2.5-flash)。"
                  "省略時はスキルに設定されたモデルを使用")

    # skill
    skill_p = sub.add_parser("skill", help="スキル単体実行")
    skill_p.add_argument("skill_id", type=int, help="スキル ID")
    skill_p.add_argument("--input", type=str, help="入力 JSON or テキスト")
    skill_p.add_argument("--input-file", type=str, help="入力 JSON ファイル")
    skill_p.add_argument("--output", "-o", type=str, help="出力ファイル")
    skill_p.add_argument("--model", type=str, help=MODEL_HELP)

    # workflow
    wf_p = sub.add_parser("workflow", help="ワークフロー実行")
    wf_p.add_argument("workflow_id", type=int, help="ワークフロー ID")
    wf_p.add_argument("--mode", choices=["serial", "parallel"], default=None, help="実行モード (省略時はワークフロー設定を使用)")
    wf_p.add_argument("--input", type=str, help="入力 JSON or テキスト")
    wf_p.add_argument("--input-file", type=str, help="入力 JSON ファイル")
    wf_p.add_argument("--output", "-o", type=str, help="出力ファイル")
    wf_p.add_argument("--model", type=str, help=MODEL_HELP)
    wf_p.add_argument("--max-concurrent", type=int, default=config.max_concurrent)

    # daemon (常駐ワーカー)
    daemon_p = sub.add_parser("daemon", help="常駐ワーカー (UIから自動実行)")
    daemon_p.add_argument("--max-concurrent", type=int, default=config.max_concurrent)
    daemon_p.add_argument("--poll-interval", type=float, default=config.poll_interval_seconds)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    setup_logging(args.log_level)

    if args.command == "list":
        asyncio.run(cmd_list(args))
    elif args.command == "skill":
        asyncio.run(cmd_skill(args))
    elif args.command == "workflow":
        asyncio.run(cmd_workflow(args))
    elif args.command == "daemon":
        asyncio.run(cmd_daemon(args))


if __name__ == "__main__":
    main()
