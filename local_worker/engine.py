"""
汎用ローカル実行エンジン

全ての AI 処理をローカルで実行する。サーバーはスキル配信と結果保存のみ。

3つの実行モード:
  1. skill   - スキルを単体実行
  2. serial  - ワークフローを直列実行 (前ステップの出力を次に渡す)
  3. parallel - ワークフローを並列実行 (全ステップ同時→最後に統合)
"""
import asyncio
import json
import logging
import time
from typing import Optional, Callable

import httpx

from .config import config
from .executor import execute_bundle, ExecutionResult

logger = logging.getLogger(__name__)

# ANSI
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
RED = "\033[31m"

STEP_COLORS = [BLUE, MAGENTA, GREEN, CYAN, YELLOW, RED]


def _color(idx: int) -> str:
    return STEP_COLORS[idx % len(STEP_COLORS)]


# ---------------------------------------------------------------------------
# Server API helpers
# ---------------------------------------------------------------------------

async def _api(method: str, path: str, token: str, json_body=None) -> dict:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(base_url=config.server_url, timeout=120) as client:
        if method == "GET":
            resp = await client.get(path, headers=headers)
        else:
            resp = await client.post(path, headers=headers, json=json_body or {})
        if resp.status_code != 200:
            raise RuntimeError(f"API error {resp.status_code}: {resp.text[:200]}")
        return resp.json()


async def list_skills(token: str) -> list:
    """利用可能なスキル一覧（全件取得）"""
    all_items = []
    skip = 0
    limit = 100
    while True:
        data = await _api("GET", f"/api/user/skills?skip={skip}&limit={limit}", token)
        items = data if isinstance(data, list) else data.get("items", data)
        if not items:
            break
        all_items.extend(items)
        total = data.get("total") if isinstance(data, dict) else None
        if total is not None and len(all_items) >= total:
            break
        if len(items) < limit:
            break
        skip += limit
    return all_items


async def list_workflows(token: str) -> list:
    """利用可能なワークフロー一覧"""
    data = await _api("GET", "/api/user/workflows", token)
    return data if isinstance(data, list) else []


async def get_workflow_detail(workflow_id: int, token: str) -> dict:
    """ワークフロー詳細(スキル一覧含む)"""
    return await _api("GET", f"/api/user/workflows/{workflow_id}", token)


# ---------------------------------------------------------------------------
# Execute single skill
# ---------------------------------------------------------------------------

async def execute_skill(
    skill_id: int,
    input_data: dict,
    token: str,
    output_format: str = "txt",
    model_override: str = None,
) -> ExecutionResult:
    """
    スキルを単体でローカル実行する。

    1. サーバーに Execution 作成 (run_mode=local)
    2. バンドル取得 (スキル復号)
    3. ローカルで LLM 実行 (--model で API/モデル選択可能)
    4. 結果をサーバーに送信
    """
    print(f"\n{BOLD}--- スキル実行 (skill_id={skill_id}) ---{RESET}")

    # 1. Execution 作成
    resp = await _api("POST", "/api/execute", token, {
        "skill_id": skill_id,
        "input_data": input_data,
        "output_format": output_format,
        "run_mode": "local",
    })
    execution_id = resp["execution_id"]
    job_token = resp.get("job_token", "")
    print(f"  Execution ID: {execution_id}")

    # 2. バンドル取得
    bundle = await _fetch_bundle(execution_id, job_token)
    actual_model = model_override or bundle["model"]
    print(f"  Model: {actual_model}, Prompt: {len(bundle['final_prompt'])} chars")

    # 3. ローカル LLM 実行
    print(f"  {YELLOW}実行中...{RESET}", end="", flush=True)
    start = time.time()
    result = await execute_bundle(bundle, model_override=model_override)
    elapsed = time.time() - start
    result.execution_time_ms = int(elapsed * 1000)
    print(f"\r  {GREEN}完了{RESET} ({elapsed:.1f}s, {result.tokens_used} tokens, {len(result.output)} chars)")

    # 4. 結果送信
    await _upload_result(execution_id, job_token, result)

    return result


# ---------------------------------------------------------------------------
# Workflow: Serial (直列)
# ---------------------------------------------------------------------------

async def execute_workflow_serial(
    workflow_id: int,
    global_input: dict,
    token: str,
    model_override: str = None,
) -> list:
    """
    ワークフローを直列実行する。
    各ステップの出力が次のステップの入力になる。
    """
    detail = await get_workflow_detail(workflow_id, token)
    wf = detail.get("workflow", {})
    skills = detail.get("skills", [])

    print(f"\n{BOLD}{'='*60}")
    print(f"  ワークフロー直列実行: {wf.get('name', workflow_id)}")
    print(f"  ステップ数: {len(skills)}")
    print(f"{'='*60}{RESET}")

    results = []
    previous_output = ""

    for i, skill in enumerate(skills):
        skill_name = skill.get("skill_name") or skill.get("skill_name") or f"Step {i+1}"
        skill_id = skill["skill_id"]
        color = _color(i)

        print(f"\n{color}{BOLD}[Step {i+1}/{len(skills)}] {skill_name}{RESET}")

        # 入力データ構築: グローバル入力 + 前ステップの出力
        step_input = dict(global_input)
        if previous_output:
            step_input["previous_output"] = previous_output
            step_input["previous_step_result"] = previous_output
            step_input["research_data"] = previous_output
            step_input["analysis_result"] = previous_output

        # 実行
        result = await execute_skill(skill_id, step_input, token, model_override=model_override)
        results.append({"step": skill_name, "result": result})

        # 出力プレビュー
        preview = result.output[:200].replace("\n", " ")
        print(f"  {DIM}>>> {preview}...{RESET}")

        # 次のステップに渡す
        previous_output = result.output

    print(f"\n{BOLD}{'='*60}")
    print(f"  直列実行完了: {len(results)} ステップ")
    print(f"{'='*60}{RESET}")

    return results


# ---------------------------------------------------------------------------
# Workflow: Parallel (並列)
# ---------------------------------------------------------------------------

async def execute_workflow_parallel(
    workflow_id: int,
    global_input: dict,
    token: str,
    max_concurrent: int = 8,
    model_override: str = None,
) -> list:
    """
    ワークフローを並列実行する。
    全ステップを同時に実行し、最後に全結果をまとめる。
    """
    detail = await get_workflow_detail(workflow_id, token)
    wf = detail.get("workflow", {})
    skills = detail.get("skills", [])

    print(f"\n{BOLD}{'='*60}")
    print(f"  ワークフロー並列実行: {wf.get('name', workflow_id)}")
    print(f"  ステップ数: {len(skills)}, 最大同時: {max_concurrent}")
    print(f"{'='*60}{RESET}")

    semaphore = asyncio.Semaphore(max_concurrent)
    results = [None] * len(skills)
    start_time = time.time()

    async def run_step(i, skill):
        skill_name = skill.get("skill_name") or skill.get("skill_name") or f"Step {i+1}"
        skill_id = skill["skill_id"]
        color = _color(i)

        async with semaphore:
            print(f"  {color}[{skill_name}]{RESET} 開始...")

            try:
                result = await execute_skill(skill_id, global_input, token, model_override=model_override)
                results[i] = {"step": skill_name, "result": result, "status": "success"}
                print(f"  {color}[{skill_name}]{RESET} {GREEN}完了{RESET} ({len(result.output)} chars)")
            except Exception as e:
                results[i] = {"step": skill_name, "result": None, "status": "error", "error": str(e)}
                print(f"  {color}[{skill_name}]{RESET} {RED}エラー: {e}{RESET}")

    # 全ステップを並列で起動
    print(f"\n  {YELLOW}全 {len(skills)} ステップを並列実行中...{RESET}\n")
    tasks = [run_step(i, skill) for i, skill in enumerate(skills)]
    await asyncio.gather(*tasks)

    elapsed = time.time() - start_time
    success_count = sum(1 for r in results if r and r["status"] == "success")

    print(f"\n{BOLD}{'='*60}")
    print(f"  並列実行完了: {success_count}/{len(skills)} 成功, {elapsed:.1f}s")
    print(f"{'='*60}{RESET}")

    return results


# ---------------------------------------------------------------------------
# Workflow: Group-based (グループベース実行)
# ---------------------------------------------------------------------------

async def execute_workflow_groups(
    workflow_id: int,
    global_input: dict,
    token: str,
    max_concurrent: int = 8,
    model_override: str = None,
) -> list:
    """
    ワークフローをグループ構造に従って実行する。
    グループ間は直列、グループ内は設定に従い直列 or 並列。
    最後に親スキルが実行される。
    """
    detail = await get_workflow_detail(workflow_id, token)
    wf = detail.get("workflow", detail)
    groups = wf.get("groups", []) or detail.get("groups", [])

    if not groups:
        # フォールバック: グループなし → 旧形式直列実行
        return await execute_workflow_serial(workflow_id, global_input, token, model_override=model_override)

    print(f"\n{BOLD}{'='*60}")
    print(f"  ワークフロー実行: {wf.get('name', workflow_id)}")
    print(f"  グループ数: {len(groups)}")
    print(f"{'='*60}{RESET}")

    # 実行フロー表示
    flow_parts = []
    for g in groups:
        etype = g.get("execution_type", "serial")
        gname = g.get("group_name", f"G{g['group_order']}")
        skill_names = ", ".join(s.get("skill_name", "?") for s in g.get("skills", []))
        color = BLUE if etype == "parallel" else YELLOW
        tag = "並列" if etype == "parallel" else "直列"
        flow_parts.append(f"  {color}[{tag}]{RESET} {gname}: {skill_names}")
    print("\n  実行フロー:")
    for part in flow_parts:
        print(f"  {part}")
    print(f"  → {MAGENTA}親スキル（統合）{RESET}\n")

    all_results = []
    previous_output = ""
    semaphore = asyncio.Semaphore(max_concurrent)

    for gi, group in enumerate(groups):
        etype = group.get("execution_type", "serial")
        gname = group.get("group_name", f"グループ {gi+1}")
        skills = group.get("skills", [])
        color = _color(gi)
        tag = "並列" if etype == "parallel" else "直列"

        print(f"\n{color}{BOLD}[Group {gi+1}: {tag}] {gname}{RESET}")

        if etype == "parallel":
            # 並列: 全スキルを同時実行
            group_results = [None] * len(skills)

            async def _run_parallel(idx, skill):
                skill_id = skill["skill_id"]
                skill_name = skill.get("skill_name", f"Skill {idx+1}")
                step_input = dict(global_input)
                if previous_output:
                    step_input["previous_output"] = previous_output
                    step_input["previous_step_result"] = previous_output
                    step_input["research_data"] = previous_output
                    step_input["analysis_result"] = previous_output

                async with semaphore:
                    result = await execute_skill(skill_id, step_input, token, model_override=model_override)
                    group_results[idx] = {"step": skill_name, "result": result, "status": "success"}

            tasks = [_run_parallel(i, s) for i, s in enumerate(skills)]
            await asyncio.gather(*tasks, return_exceptions=True)

            # 並列結果を結合して次のグループに渡す
            outputs = []
            for r in group_results:
                if r and r.get("result"):
                    all_results.append(r)
                    outputs.append(r["result"].output)
            previous_output = "\n\n---\n\n".join(outputs)

        else:
            # 直列: 順番に実行、出力を次に渡す
            for si, skill in enumerate(skills):
                skill_id = skill["skill_id"]
                skill_name = skill.get("skill_name", f"Skill {si+1}")
                step_input = dict(global_input)
                if previous_output:
                    step_input["previous_output"] = previous_output
                    step_input["previous_step_result"] = previous_output
                    step_input["research_data"] = previous_output
                    step_input["analysis_result"] = previous_output

                result = await execute_skill(skill_id, step_input, token, model_override=model_override)
                all_results.append({"step": skill_name, "result": result, "status": "success"})
                previous_output = result.output

                preview = result.output[:150].replace("\n", " ")
                print(f"  {DIM}>>> {preview}...{RESET}")

    print(f"\n{BOLD}{'='*60}")
    print(f"  全グループ完了: {len(all_results)} ステップ")
    print(f"{'='*60}{RESET}")

    return all_results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _fetch_bundle(execution_id: int, job_token: str) -> dict:
    headers = {"Authorization": f"Bearer {job_token}"}
    async with httpx.AsyncClient(base_url=config.server_url, timeout=30) as client:
        resp = await client.get(f"/api/worker/executions/{execution_id}/bundle", headers=headers)
        if resp.status_code != 200:
            raise RuntimeError(f"Bundle fetch failed: {resp.status_code} {resp.text[:200]}")
        return resp.json()


async def _upload_result(execution_id: int, job_token: str, result: ExecutionResult):
    headers = {"Authorization": f"Bearer {job_token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(base_url=config.server_url, timeout=60) as client:
        resp = await client.post(
            f"/api/worker/executions/{execution_id}/complete",
            headers=headers,
            json={
                "output": result.output,
                "tokens_used": result.tokens_used,
                "model_used": result.model_used,
                "execution_time_ms": result.execution_time_ms,
            },
        )
        if resp.status_code != 200:
            logger.warning(f"Upload failed for {execution_id}: {resp.status_code}")
