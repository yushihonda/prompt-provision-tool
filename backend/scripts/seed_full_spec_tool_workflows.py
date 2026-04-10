"""Seed two full-spec test workflows that build a small HTML/CSS/JS tool.

Two workflows are created so the user can compare runtime mixes side by
side. Both produce the same kind of artifact (a small interactive web
tool) but exercise different parent + group layouts:

  WF1: [test-full] tool builder (parent=CLI claude, parallel impl)
       parent runtime  : external_cli (claude-code-local, claude-sonnet-4-6)
       group 1 serial  : research_step               -> API
       group 2 parallel: claude_impl + codex_impl    -> CLI claude / CLI codex
       group 3 serial  : verify_step                 -> API

  WF2: [test-full] tool builder (parent=API, serial)
       parent runtime  : provider (gpt-5.4)
       group 1 serial  : research_step  -> API
       group 2 serial  : claude_impl    -> CLI claude
       group 3 serial  : codex_impl     -> CLI codex
       group 4 serial  : verify_step    -> API

Idempotent: rerunning deletes existing workflows with the same names
and recreates them. Skill rows are upserted by name.

Usage (inside the backend container so DB env is loaded):

    docker exec -w /app -e PYTHONPATH=/app nexmagi-backend \
        python scripts/seed_full_spec_tool_workflows.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Make `app.*` importable when run from backend/.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.database import SessionLocal  # noqa: E402
from app.encryption import encryption_service  # noqa: E402
from app.models import (  # noqa: E402
    Account,
    AccountSkill,
    Skill,
    Workflow,
    WorkflowGroup,
    WorkflowSkill,
)
from app.services.coordinator_extensions import seed_default_adapters  # noqa: E402

# ----- constants ---------------------------------------------------------

API_MODEL = "gpt-5.4"
# Hard-coded host path. expanduser() would resolve to /root inside the
# backend container; the Rust runner validates against the host $HOME so
# we need the literal /Users/hondayushi value.
CLI_CWD_HINT = "/Users/hondayushi/nexmagi-cli-workspace"

CLAUDE_ADAPTER = "claude-code-local"
CLAUDE_RUNTIME = "claude_code"
CLAUDE_CLI_MODEL = "claude-sonnet-4-6"

CODEX_ADAPTER = "codex-local"
CODEX_RUNTIME = "codex"
CODEX_CLI_MODEL = "gpt-5-codex"

WF1_NAME = "[test-full] tool builder (parent=CLI claude, parallel impl)"
WF2_NAME = "[test-full] tool builder (parent=API, serial)"

# Skill names — shared across both workflows so we don't double-create.
SKILL_RESEARCH = "[test-full] tool research"
SKILL_CLAUDE_IMPL = "[test-full] tool claude impl"
SKILL_CODEX_IMPL = "[test-full] tool codex impl"
SKILL_VERIFY = "[test-full] tool verify"
SKILL_PARENT_LEADER = "[test-full] tool leader"  # parent skill content holder

# ----- execution_config builders -----------------------------------------


def api_execution_config() -> dict:
    """HTTP provider runtime, read-only, no workspace."""
    return {
        "execution_config": {
            "schema_version": "1.0",
            "execution": {
                "execution_kind": "provider",
                "preferred_adapter": None,
                "candidate_adapters": [],
                "required_capabilities": [],
                "cli_runtime_hint": None,
                "cwd_hint": None,
                "cli_model": None,
            },
            "workspace": {
                "workspace_policy": "none",
                "share_with_steps": [],
                "promote_on": "accepted",
                "cleanup_on": "failed",
            },
            "approval": {
                "policy": "read_only",
                "allow_writes": False,
                "allow_shell": False,
            },
            "artifact_contract": {
                "expected_type": None,
                "must_include_files": False,
                "must_include_diff": False,
            },
        }
    }


def cli_execution_config(*, adapter: str, runtime_hint: str, cli_model: str) -> dict:
    """External CLI runtime config (claude-code-local / codex-local)."""
    return {
        "execution_config": {
            "schema_version": "1.0",
            "execution": {
                "execution_kind": "external_cli",
                "preferred_adapter": adapter,
                "candidate_adapters": [adapter],
                "required_capabilities": ["file_write", "shell_exec"],
                "cli_runtime_hint": runtime_hint,
                "cwd_hint": CLI_CWD_HINT,
                "cli_model": cli_model,
            },
            "workspace": {
                "workspace_policy": "temp_dir",
                "share_with_steps": [],
                "promote_on": "accepted",
                "cleanup_on": "failed",
            },
            "approval": {
                "policy": "allow_write",
                "allow_writes": True,
                "allow_shell": True,
            },
            "artifact_contract": {
                "expected_type": None,
                "must_include_files": False,
                "must_include_diff": False,
            },
        }
    }


def claude_cli_config() -> dict:
    return cli_execution_config(
        adapter=CLAUDE_ADAPTER,
        runtime_hint=CLAUDE_RUNTIME,
        cli_model=CLAUDE_CLI_MODEL,
    )


def codex_cli_config() -> dict:
    return cli_execution_config(
        adapter=CODEX_ADAPTER,
        runtime_hint=CODEX_RUNTIME,
        cli_model=CODEX_CLI_MODEL,
    )


# ----- skill prompts -----------------------------------------------------

RESEARCH_PROMPT = (
    "あなたはWebツール調査エージェントです。ユーザーが作りたいツール"
    "(HTML/CSS/JS の小さな単一ページツール) について、"
    "以下を箇条書きで簡潔にまとめてください:\n"
    "  1. ツールの目的と想定ユースケース\n"
    "  2. 必要な UI 要素 (入力フィールド、ボタン、表示エリア等)\n"
    "  3. 計算/変換ロジックの概要\n"
    "  4. 注意点 (バリデーション、エッジケース)\n"
    "出力は次のステップ (実装) がすぐ作業できる粒度にしてください。"
)

CLAUDE_IMPL_PROMPT = (
    "あなたは Claude Code CLI 経由で動く実装エージェントです。"
    "前のステップで作成された research_notes に従って、"
    "単一の index.html (CSS/JS 埋め込み or 同フォルダの style.css / script.js) として"
    "動くツールを作業ディレクトリに書き出してください。"
    "実装後、何を作ったかを 3 行以内で要約してください。"
)

CODEX_IMPL_PROMPT = (
    "あなたは OpenAI Codex CLI 経由で動く実装エージェントです。"
    "前のステップの research_notes に従って、"
    "単一の index.html (CSS/JS 埋め込み or 同フォルダの style.css / script.js) として"
    "動くツールを作業ディレクトリに書き出してください。"
    "実装後、何を作ったかを 3 行以内で要約してください。"
)

VERIFY_PROMPT = (
    "あなたは品質チェックエージェントです。"
    "前段で作成された実装結果(テキスト要約 + あれば変更ファイル一覧)を読み、"
    "以下を1行ずつ判定して報告してください:\n"
    "  - HTML/CSS/JS が論理的に動作する見込みか (ACCEPT/REJECT)\n"
    "  - 不足している UI 要素\n"
    "  - 改善提案 (1〜2件)\n"
    "1行目は ACCEPTED または REJECTED を出力してください。"
)

PARENT_LEADER_PROMPT = (
    "あなたはツール開発ワークフローのリーダーです。"
    "全ての子ステップの成果物 (research_notes / 実装サマリ / verify 結果) を統合し、"
    "ユーザー向けに以下を日本語で出力してください:\n"
    "  1. 何を作ったか (1段落)\n"
    "  2. 採用した実装の出所 (claude / codex / 両方併記など)\n"
    "  3. 次にユーザーが行うべき確認手順 (箇条書き)"
)


# ----- helpers -----------------------------------------------------------


def upsert_skill(
    db, *, name: str, prompt: str, model_type: str, account_id: int, description: str
) -> Skill:
    existing = (
        db.query(Skill).filter(Skill.name == name, Skill.deleted_at.is_(None)).first()
    )
    encrypted = encryption_service.encrypt(prompt)
    if existing:
        existing.encrypted_content = encrypted
        existing.model_type = model_type
        existing.description = description
        db.commit()
        db.refresh(existing)
        skill = existing
    else:
        skill = Skill(
            name=name,
            description=description,
            encrypted_content=encrypted,
            model_type=model_type,
            is_active=True,
            allows_file_output=False,
            enable_deep_think=False,
            created_by=account_id,
        )
        db.add(skill)
        db.commit()
        db.refresh(skill)
    if not (
        db.query(AccountSkill)
        .filter(
            AccountSkill.account_id == account_id, AccountSkill.skill_id == skill.id
        )
        .first()
    ):
        db.add(AccountSkill(account_id=account_id, skill_id=skill.id))
        db.commit()
    return skill


def delete_workflow_by_name(db, name: str) -> None:
    rows = db.query(Workflow).filter(Workflow.name == name).all()
    for wf in rows:
        db.query(WorkflowSkill).filter(WorkflowSkill.workflow_id == wf.id).delete()
        db.query(WorkflowGroup).filter(WorkflowGroup.workflow_id == wf.id).delete()
        db.delete(wf)
    db.commit()


def build_workflow(
    db,
    *,
    name: str,
    description: str,
    creator_id: int,
    parent_config: dict | None,  # workflow.config_json execution wrapper or None for legacy API
    groups_spec: list[dict],
) -> Workflow:
    """Create one workflow with the given group/step layout.

    `groups_spec` items shape:
        {
          "name": str,
          "execution_type": "serial" | "parallel",
          "steps": [
              {
                "skill": Skill, "step_name": str,
                "config": dict (execution_config wrapper) or None,
                "agent_profile": str
              },
              ...
          ],
        }
    """
    parent_content = (
        f"あなたはテスト用ワークフロー [{name}] のリーダーです。"
        f"ツール作成 (HTML/CSS/JS) の各子ステップ結果を統合してユーザーに報告してください。"
    )
    wf = Workflow(
        name=name,
        description=description,
        is_active=True,
        created_by=creator_id,
        encrypted_parent_content=encryption_service.encrypt(parent_content),
        parent_model_type=API_MODEL,
        parent_enable_deep_think=False,
        parent_skill_mode="required",
        supervisor_mode="disabled",
        config_json=json.dumps(parent_config, ensure_ascii=False) if parent_config else None,
    )
    db.add(wf)
    db.flush()

    skill_order_counter = 0
    for grp_idx, grp_spec in enumerate(groups_spec, start=1):
        grp = WorkflowGroup(
            workflow_id=wf.id,
            group_order=grp_idx,
            group_name=grp_spec["name"],
            execution_type=grp_spec["execution_type"],
            skip_on_condition_fail=True,
            dynamic_mode="static",
            config_json=None,
        )
        db.add(grp)
        db.flush()

        for in_grp_idx, step in enumerate(grp_spec["steps"], start=1):
            skill_order_counter += 1
            ws = WorkflowSkill(
                workflow_id=wf.id,
                skill_id=step["skill"].id,
                skill_order=skill_order_counter,
                skill_name=step["step_name"],
                config_json=json.dumps(step["config"], ensure_ascii=False)
                if step["config"]
                else None,
                agent_profile=step.get("agent_profile") or "default",
                group_id=grp.id,
                order_in_group=in_grp_idx,
                on_error="stop",
                max_retries=0,
                retry_delay_seconds=5,
                quality_gate_type="disabled",
                max_reflection_loops=0,
            )
            db.add(ws)

    db.commit()
    db.refresh(wf)
    return wf


# ----- main --------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--account-id",
        type=int,
        default=None,
        help="Account that owns the workflows. Defaults to first PARENT account.",
    )
    args = parser.parse_args()

    # Don't create the directory from inside the container — the path is
    # the host path. The host machine should already have it (created by
    # the earlier seed scripts); print a reminder if not.
    print(f"cwd_hint (host path): {CLI_CWD_HINT}")

    db = SessionLocal()
    try:
        seed_default_adapters(db)

        if args.account_id is None:
            acct = (
                db.query(Account)
                .filter(Account.account_type == "PARENT", Account.is_active == True)  # noqa: E712
                .order_by(Account.id.asc())
                .first()
            )
            if acct is None:
                print("ERROR: no PARENT account found.", file=sys.stderr)
                return 1
            account_id = acct.id
            print(f"using account_id={account_id} ({acct.username})")
        else:
            account_id = args.account_id

        # ----- upsert reusable skills -----
        sk_research = upsert_skill(
            db,
            name=SKILL_RESEARCH,
            prompt=RESEARCH_PROMPT,
            model_type=API_MODEL,
            account_id=account_id,
            description="Tool research step (API).",
        )
        sk_claude = upsert_skill(
            db,
            name=SKILL_CLAUDE_IMPL,
            prompt=CLAUDE_IMPL_PROMPT,
            model_type=API_MODEL,  # placeholder; CLI adapter overrides
            account_id=account_id,
            description="Tool implementation via Claude Code CLI.",
        )
        sk_codex = upsert_skill(
            db,
            name=SKILL_CODEX_IMPL,
            prompt=CODEX_IMPL_PROMPT,
            model_type=API_MODEL,  # placeholder; CLI adapter overrides
            account_id=account_id,
            description="Tool implementation via OpenAI Codex CLI.",
        )
        sk_verify = upsert_skill(
            db,
            name=SKILL_VERIFY,
            prompt=VERIFY_PROMPT,
            model_type=API_MODEL,
            account_id=account_id,
            description="Tool quality verification step (API).",
        )
        print("  upserted 4 skills (research / claude_impl / codex_impl / verify)")

        # ----- WF1: parent=CLI claude, parallel impl group -----
        delete_workflow_by_name(db, WF1_NAME)
        wf1 = build_workflow(
            db,
            name=WF1_NAME,
            description="親=CLI(claude). 直列 research → 並列 claude+codex 実装 → 直列 verify",
            creator_id=account_id,
            parent_config=claude_cli_config(),
            groups_spec=[
                {
                    "name": "1. 調査",
                    "execution_type": "serial",
                    "steps": [
                        {
                            "skill": sk_research,
                            "step_name": "research",
                            "config": api_execution_config(),
                            "agent_profile": "explore",
                        },
                    ],
                },
                {
                    "name": "2. 並列実装",
                    "execution_type": "parallel",
                    "steps": [
                        {
                            "skill": sk_claude,
                            "step_name": "claude_impl",
                            "config": claude_cli_config(),
                            "agent_profile": "implement",
                        },
                        {
                            "skill": sk_codex,
                            "step_name": "codex_impl",
                            "config": codex_cli_config(),
                            "agent_profile": "implement",
                        },
                    ],
                },
                {
                    "name": "3. 検証",
                    "execution_type": "serial",
                    "steps": [
                        {
                            "skill": sk_verify,
                            "step_name": "verify",
                            "config": api_execution_config(),
                            "agent_profile": "verification",
                        },
                    ],
                },
            ],
        )
        print(f"created WF1 id={wf1.id} name={wf1.name!r}")

        # ----- WF2: parent=API, fully serial -----
        delete_workflow_by_name(db, WF2_NAME)
        wf2 = build_workflow(
            db,
            name=WF2_NAME,
            description="親=API. 直列 research → claude_impl → codex_impl → verify",
            creator_id=account_id,
            parent_config=api_execution_config(),
            groups_spec=[
                {
                    "name": "1. 調査",
                    "execution_type": "serial",
                    "steps": [
                        {
                            "skill": sk_research,
                            "step_name": "research",
                            "config": api_execution_config(),
                            "agent_profile": "explore",
                        },
                    ],
                },
                {
                    "name": "2. Claude 実装",
                    "execution_type": "serial",
                    "steps": [
                        {
                            "skill": sk_claude,
                            "step_name": "claude_impl",
                            "config": claude_cli_config(),
                            "agent_profile": "implement",
                        },
                    ],
                },
                {
                    "name": "3. Codex 実装",
                    "execution_type": "serial",
                    "steps": [
                        {
                            "skill": sk_codex,
                            "step_name": "codex_impl",
                            "config": codex_cli_config(),
                            "agent_profile": "implement",
                        },
                    ],
                },
                {
                    "name": "4. 検証",
                    "execution_type": "serial",
                    "steps": [
                        {
                            "skill": sk_verify,
                            "step_name": "verify",
                            "config": api_execution_config(),
                            "agent_profile": "verification",
                        },
                    ],
                },
            ],
        )
        print(f"created WF2 id={wf2.id} name={wf2.name!r}")

        print()
        print("=== DONE ===")
        print(f"  WF1 (parent=CLI claude, parallel impl): id={wf1.id}")
        print(f"  WF2 (parent=API, serial):               id={wf2.id}")
        print(f"  CLI cwd: {CLI_CWD_HINT}")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
