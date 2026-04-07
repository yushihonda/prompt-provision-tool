#!/usr/bin/env python3
"""Seed a sample mixed-runtime workflow into the dev database.

Creates 5 skills + 1 workflow that exercises every supported runtime
in a single pipeline:

  1. search_step    -> HTTP provider (Gemini / OpenAI / Anthropic via remote-api)
  2. plan_step      -> Local Ollama qwen2.5-coder:14b (HTTP provider, local_preferred)
  3. code_step      -> Claude Code CLI (external_cli, temp_dir workspace, allow_write)
  4. verify_step    -> Codex CLI (external_cli, share_with_steps=[code_step], read_only)
  5. judge_step     -> Hard rule: forced remote HTTP provider, never CLI

Usage:
    cd backend
    python scripts/seed_mixed_runtime_workflow.py [--account-id 1] [--dry-run]

The script is idempotent: rerunning it deletes the old workflow with
the same name and recreates it with current skill IDs.

After running, log into the desktop app, navigate to the workflow,
and trigger it. Each step will route through resolve_execution_kind
to its declared runtime, with full provenance recorded in artifact
metadata.
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
    WorkflowSkill,
)
from app.services.coordinator_extensions import seed_default_adapters  # noqa: E402

WORKFLOW_NAME = "Mixed Runtime Demo (Claude + Codex + API)"


def execution_config_for(
    *,
    execution_kind: str,
    preferred_adapter: str | None = None,
    cli_runtime_hint: str | None = None,
    workspace_policy: str = "none",
    share_with_steps: list[str] | None = None,
    approval_policy: str = "read_only",
    allow_writes: bool = False,
    allow_shell: bool = False,
    required_capabilities: list[str] | None = None,
    cwd_hint: str | None = None,
) -> dict:
    """Build a config_json blob with execution_config inline."""
    return {
        "execution_config": {
            "schema_version": "1.0",
            "execution": {
                "execution_kind": execution_kind,
                "preferred_adapter": preferred_adapter,
                "candidate_adapters": [],
                "required_capabilities": required_capabilities or [],
                "cli_runtime_hint": cli_runtime_hint,
                "cwd_hint": cwd_hint,
            },
            "workspace": {
                "workspace_policy": workspace_policy,
                "share_with_steps": share_with_steps or [],
                "promote_on": "accepted",
                "cleanup_on": "failed",
            },
            "approval": {
                "policy": approval_policy,
                "allow_writes": allow_writes,
                "allow_shell": allow_shell,
            },
            "artifact_contract": {
                "expected_type": None,
                "must_include_files": False,
                "must_include_diff": False,
            },
        }
    }


def upsert_skill(db, *, name: str, prompt: str, model_type: str, account_id: int) -> Skill:
    existing = db.query(Skill).filter(Skill.name == name, Skill.deleted_at.is_(None)).first()
    encrypted = encryption_service.encrypt(prompt)
    if existing:
        existing.encrypted_content = encrypted
        existing.model_type = model_type
        db.commit()
        db.refresh(existing)
        skill = existing
    else:
        skill = Skill(
            name=name,
            description=f"Mixed-runtime demo step: {name}",
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
    # Make sure the account is granted the skill.
    if not db.query(AccountSkill).filter(
        AccountSkill.account_id == account_id, AccountSkill.skill_id == skill.id
    ).first():
        db.add(AccountSkill(account_id=account_id, skill_id=skill.id))
        db.commit()
    return skill


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--account-id", type=int, default=None,
                        help="Account that owns the workflow. Defaults to first account.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print actions without writing to DB.")
    parser.add_argument("--cwd", type=str, default=None,
                        help="Absolute cwd hint for CLI steps. Defaults to $HOME/nexmagi-mixed-demo.")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        # Ensure default adapters exist (claude-code-local, codex-local, etc.)
        if not args.dry_run:
            seed_default_adapters(db)

        if args.account_id is None:
            acct = db.query(Account).order_by(Account.id.asc()).first()
            if acct is None:
                print("ERROR: no accounts in DB. Create one via the admin UI first.", file=sys.stderr)
                sys.exit(1)
            account_id = acct.id
            print(f"using account_id={account_id} ({acct.username})")
        else:
            account_id = args.account_id

        cwd_hint = args.cwd or os.path.join(os.path.expanduser("~"), "nexmagi-mixed-demo")
        os.makedirs(cwd_hint, exist_ok=True)
        print(f"cwd_hint={cwd_hint}")

        # Define the 5 step prompts.
        steps = [
            {
                "name": "demo-search-step",
                "model_type": "gpt-4o-mini",
                "prompt": (
                    "You are a research agent. Given the user's topic, list 3 short bullet "
                    "points summarizing the most important facts. Be concise."
                ),
                "config": execution_config_for(
                    execution_kind="provider",
                    required_capabilities=[],
                    approval_policy="read_only",
                ),
                "skill_order": 1,
                "agent_profile": "explore",
            },
            {
                "name": "demo-plan-step",
                "model_type": "qwen2.5-coder:14b",
                "prompt": (
                    "You are a planning agent. Given the research notes, produce a 5-step "
                    "implementation plan for the topic. Use numbered list."
                ),
                "config": execution_config_for(
                    execution_kind="provider",
                    required_capabilities=[],
                    approval_policy="read_only",
                ),
                "skill_order": 2,
                "agent_profile": "plan",
            },
            {
                "name": "demo-code-step",
                "model_type": "claude_code",
                "prompt": (
                    "You are a coding agent invoked via Claude Code CLI. Implement the plan "
                    "above by writing the requested files into the working directory. When "
                    "done, summarize what you changed."
                ),
                "config": execution_config_for(
                    execution_kind="external_cli",
                    preferred_adapter="claude-code-local",
                    cli_runtime_hint="claude_code",
                    workspace_policy="temp_dir",
                    approval_policy="allow_write",
                    allow_writes=True,
                    allow_shell=False,
                    required_capabilities=["file_read", "file_write", "workspace_aware"],
                    cwd_hint=cwd_hint,
                ),
                "skill_order": 3,
                "agent_profile": "implement",
            },
            {
                "name": "demo-verify-step",
                "model_type": "codex",
                "prompt": (
                    "You are a verification agent invoked via Codex CLI. Inspect the files "
                    "in the working directory (do NOT modify them) and report whether they "
                    "match the plan. Output PASS or FAIL on the first line, then explain."
                ),
                "config": execution_config_for(
                    execution_kind="external_cli",
                    preferred_adapter="codex-local",
                    cli_runtime_hint="codex",
                    workspace_policy="temp_dir",
                    share_with_steps=["task_3"],  # share with code step (workflow_skill_id=3 -> task_3)
                    approval_policy="read_only",
                    required_capabilities=["file_read"],
                    cwd_hint=cwd_hint,
                ),
                "skill_order": 4,
                "agent_profile": "verification",
            },
            {
                "name": "demo-judge-step",
                "model_type": "gpt-4o-mini",
                "prompt": (
                    "You are a judge. Given the verification report, decide if the work is "
                    "ACCEPTED or REJECTED. Output the decision on the first line, then a "
                    "one-sentence rationale."
                ),
                "config": execution_config_for(
                    execution_kind="auto",  # judge is hard-routed to remote regardless
                    approval_policy="read_only",
                ),
                "skill_order": 5,
                "agent_profile": "verification",
            },
        ]

        if args.dry_run:
            print("--- DRY RUN ---")
            for s in steps:
                print(f"  step {s['skill_order']}: {s['name']} model={s['model_type']}")
                print(f"    config={json.dumps(s['config'], ensure_ascii=False)}")
            return

        # Create skills.
        skill_rows = []
        for s in steps:
            sk = upsert_skill(
                db,
                name=s["name"],
                prompt=s["prompt"],
                model_type=s["model_type"],
                account_id=account_id,
            )
            skill_rows.append((sk, s))
            print(f"  upserted skill id={sk.id} name={sk.name}")

        # Delete prior demo workflow if it exists.
        prior = db.query(Workflow).filter(
            Workflow.name == WORKFLOW_NAME,
            Workflow.deleted_at.is_(None) if hasattr(Workflow, "deleted_at") else True,
        ).first()
        if prior:
            db.query(WorkflowSkill).filter(WorkflowSkill.workflow_id == prior.id).delete()
            db.delete(prior)
            db.commit()
            print(f"  removed prior workflow id={prior.id}")

        # Create workflow.
        wf = Workflow(
            name=WORKFLOW_NAME,
            description=(
                "Demo workflow that exercises every runtime: HTTP provider for "
                "search/plan/judge, Claude Code CLI for code, Codex CLI for verify."
            ),
            is_active=True,
            created_by=account_id,
        )
        db.add(wf)
        db.commit()
        db.refresh(wf)
        print(f"created workflow id={wf.id} name={wf.name}")

        # Attach steps with execution_config.
        for sk, spec in skill_rows:
            ws = WorkflowSkill(
                workflow_id=wf.id,
                skill_id=sk.id,
                skill_order=spec["skill_order"],
                skill_name=spec["name"],
                config_json=json.dumps(spec["config"], ensure_ascii=False),
                agent_profile=spec.get("agent_profile"),
            )
            db.add(ws)
        db.commit()
        print(f"attached {len(skill_rows)} steps to workflow")

        print()
        print("=== DONE ===")
        print(f"workflow_id: {wf.id}")
        print(f"workflow_name: {wf.name}")
        print()
        print("Next steps:")
        print(f"  1. Make sure account_id={account_id} can see the workflow (admin UI)")
        print("  2. Open the desktop app and trigger the workflow")
        print(f"  3. CLI steps will execute in: {cwd_hint}")
        print("  4. Check artifact metadata in mysql for selection_reason / runtime / changed_files")
    finally:
        db.close()


if __name__ == "__main__":
    main()
