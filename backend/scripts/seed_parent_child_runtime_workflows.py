"""Seed two test workflows that exercise the 4-level execution_config:

  WF1 — parent = API (HTTP provider), child step = CLI (claude-code-local)
  WF2 — parent = CLI (claude-code-local), child step = API (HTTP provider)

Runs against the live DB (no FastAPI involvement). Idempotent on
workflow name — if a workflow with the same name already exists it is
deleted and recreated so re-running this seed leaves the DB in a known
state.

Usage (inside the backend container, so DB host + ENCRYPTION_KEY come
from the container env):

    docker exec nexmagi-backend python scripts/seed_parent_child_runtime_workflows.py
"""
from __future__ import annotations

import json
import sys
from typing import Optional

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import (
    Account,
    Skill,
    Workflow,
    WorkflowGroup,
    WorkflowSkill,
)
from app.encryption import encryption_service


# ----- Constants ---------------------------------------------------------

API_MODEL = "gpt-5.4"

# Runtime registry. Each entry defines how to build an execution_config
# for that runtime. "api" is the HTTP provider path; the others are
# external CLI adapters.
RUNTIMES = {
    "api": {
        "kind": "api",
        "label": "API",
    },
    "claude": {
        "kind": "cli",
        "label": "CLI(claude)",
        "adapter": "claude-code-local",
        "runtime_hint": "claude_code",
        "cli_model_type": API_MODEL,  # placeholder; CLI adapter overrides
    },
    "codex": {
        "kind": "cli",
        "label": "CLI(codex)",
        "adapter": "codex-local",
        "runtime_hint": "codex",
        "cli_model_type": "codex",
    },
}
# Hard-coded cwd used as a fallback when no Tauri client has written
# back a real workspace_path. Two constraints:
#   1. Must exist on whichever process actually spawns claude
#      (the backend Docker container OR the host Tauri runtime).
#   2. The Rust runner enforces "under HOME" for security
#      (external_cli_runner.rs:validate_cwd) so the path MUST resolve
#      somewhere inside the user's $HOME on the host.
# We hard-code the host path; the backend Docker worker container is
# expected to mount the same path or have its own equivalent. For the
# Tauri-only path the directory just needs to exist on the developer
# host (the seed script does NOT create this — host responsibility).
CLI_CWD_HINT = "/Users/hondayushi/nexmagi-cli-workspace"

def _label(runtime_key: str) -> str:
    return RUNTIMES[runtime_key]["label"]


def wf_name(parent_rt: str, child_rt: str) -> str:
    return f"[test] parent={_label(parent_rt)}, child={_label(child_rt)}"


def skill_name(runtime_key: str) -> str:
    return f"[test] child skill {_label(runtime_key)}"


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


def cli_execution_config(runtime_key: str) -> dict:
    """External CLI runtime config for the given runtime key.

    cwd_hint is a fixed host directory under $HOME (external_cli_runner
    validates "under HOME"). The directory is created on demand by the
    seed script.
    """
    rt = RUNTIMES[runtime_key]
    assert rt["kind"] == "cli", f"runtime {runtime_key} is not a CLI runtime"
    return {
        "execution_config": {
            "schema_version": "1.0",
            "execution": {
                "execution_kind": "external_cli",
                "preferred_adapter": rt["adapter"],
                "candidate_adapters": [rt["adapter"]],
                "required_capabilities": ["file_write", "shell_exec"],
                "cli_runtime_hint": rt["runtime_hint"],
                "cwd_hint": CLI_CWD_HINT,
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


def execution_config_for(runtime_key: str) -> dict:
    """Dispatch helper: api -> api_execution_config, else cli_execution_config."""
    if RUNTIMES[runtime_key]["kind"] == "api":
        return api_execution_config()
    return cli_execution_config(runtime_key)


# ----- helpers -----------------------------------------------------------

def find_or_create_admin(db: Session) -> Account:
    acc = (
        db.query(Account)
        .filter(Account.account_type == "PARENT", Account.is_active == True)  # noqa: E712
        .order_by(Account.id.asc())
        .first()
    )
    if acc is None:
        raise SystemExit("No active PARENT account found — create one first.")
    return acc


def upsert_skill(
    db: Session,
    *,
    name: str,
    description: str,
    model_type: str,
    content: str,
    creator_id: int,
    config_json: Optional[dict],
) -> Skill:
    """Idempotent: same-name + not-deleted skill is reused (and updated)."""
    existing = (
        db.query(Skill)
        .filter(Skill.name == name, Skill.deleted_at.is_(None))
        .first()
    )
    encrypted = encryption_service.encrypt(content)
    cfg_str = json.dumps(config_json, ensure_ascii=False) if config_json else None
    if existing:
        existing.description = description
        existing.model_type = model_type
        existing.encrypted_content = encrypted
        existing.config_json = cfg_str
        existing.is_active = True
        db.flush()
        return existing
    sk = Skill(
        name=name,
        description=description,
        encrypted_content=encrypted,
        model_type=model_type,
        config_json=cfg_str,
        is_active=True,
        created_by=creator_id,
    )
    db.add(sk)
    db.flush()
    return sk


def delete_workflow_by_name(db: Session, name: str) -> None:
    """Hard-delete an existing test workflow + cascade rows so this seed
    is fully idempotent."""
    rows = (
        db.query(Workflow)
        .filter(Workflow.name == name)
        .all()
    )
    for wf in rows:
        # WorkflowSkill / WorkflowGroup are cascade='all, delete-orphan'
        # so deleting the workflow removes them.
        db.delete(wf)
    db.flush()


def build_workflow(
    db: Session,
    *,
    name: str,
    description: str,
    creator_id: int,
    parent_runtime: str,  # key in RUNTIMES
    child_skill: Skill,
    child_runtime: str,   # key in RUNTIMES
) -> Workflow:
    """Create one workflow with one group containing one child step.

    parent_runtime drives Workflow.config_json (top of inheritance chain).
    child_runtime drives WorkflowSkill.config_json (step level). With
    these set we exercise the full chain on every execution.
    """
    parent_content = (
        f"あなたはテスト用ワークフロー [{name}] のリーダーです。\n"
        "子ステップの結果 (all_step_results) を確認し、"
        f"親ランタイム = {_label(parent_runtime)}, 子ランタイム = {_label(child_runtime)} "
        "の組み合わせが正しく動いたかを日本語で1段落で報告してください。"
    )
    parent_cfg = execution_config_for(parent_runtime)
    step_cfg = execution_config_for(child_runtime)

    # Parent model_type is mandatory on Workflow even when the parent
    # actually runs through CLI. For the CLI case we still set a model
    # so the row is valid; the execution path will pick the CLI adapter
    # because parent_cfg.execution.execution_kind == "external_cli".
    wf = Workflow(
        name=name,
        description=description,
        is_active=True,
        created_by=creator_id,
        encrypted_parent_content=encryption_service.encrypt(parent_content),
        parent_model_type=API_MODEL,
        parent_enable_deep_think=True,
        parent_skill_mode="required",
        supervisor_mode="disabled",
        config_json=json.dumps(parent_cfg, ensure_ascii=False),
    )
    db.add(wf)
    db.flush()

    grp = WorkflowGroup(
        workflow_id=wf.id,
        group_order=1,
        group_name="グループ 1",
        execution_type="serial",
        skip_on_condition_fail=True,
        dynamic_mode="static",
        config_json=None,  # group level inherits from workflow
    )
    db.add(grp)
    db.flush()

    ws = WorkflowSkill(
        workflow_id=wf.id,
        skill_id=child_skill.id,
        skill_order=1,
        skill_name="子ステップ",
        group_id=grp.id,
        order_in_group=1,
        on_error="stop",
        max_retries=0,
        retry_delay_seconds=5,
        quality_gate_type="disabled",
        max_reflection_loops=0,
        config_json=json.dumps(step_cfg, ensure_ascii=False),
    )
    db.add(ws)
    db.flush()
    return wf


# ----- main --------------------------------------------------------------

def _upsert_child_skill(db: Session, runtime_key: str, creator_id: int) -> Skill:
    rt = RUNTIMES[runtime_key]
    if rt["kind"] == "api":
        content = (
            "あなたはAPI経由で動くテスト用エージェントです。"
            "ユーザー入力を受け取り、200文字以内の日本語で応答してください。"
        )
        description = "Test child skill — runs via HTTP provider (API)"
        model_type = API_MODEL
    else:
        content = (
            f"あなたは {rt['label']} 経由で動くテスト用エージェントです。"
            "ユーザー入力を受け取り、200文字以内の日本語で応答してください。"
        )
        description = f"Test child skill — runs via {rt['label']}"
        model_type = rt["cli_model_type"]
    return upsert_skill(
        db,
        name=skill_name(runtime_key),
        description=description,
        model_type=model_type,
        content=content,
        creator_id=creator_id,
        config_json=execution_config_for(runtime_key),
    )


def main() -> int:
    import argparse
    import os

    parser = argparse.ArgumentParser(
        description="Seed parent/child runtime test workflows. "
                    "Use --pair to seed a specific (parent,child) combo, "
                    "or --preset to seed a common set in one go.",
    )
    parser.add_argument(
        "--parent",
        choices=sorted(RUNTIMES.keys()),
        help="Parent runtime (api/claude/codex).",
    )
    parser.add_argument(
        "--child",
        choices=sorted(RUNTIMES.keys()),
        help="Child runtime (api/claude/codex).",
    )
    parser.add_argument(
        "--preset",
        choices=["claude", "codex", "all"],
        help=(
            "Shortcut: seed {parent=API,child=CLI} + {parent=CLI,child=API} "
            "for the chosen runtime. 'all' does both claude and codex."
        ),
    )
    args = parser.parse_args()

    # Resolve the list of (parent, child) pairs to seed.
    pairs: list[tuple[str, str]] = []
    if args.preset:
        runtimes = ["claude", "codex"] if args.preset == "all" else [args.preset]
        for rt_key in runtimes:
            pairs.append(("api", rt_key))
            pairs.append((rt_key, "api"))
    elif args.parent and args.child:
        pairs.append((args.parent, args.child))
    else:
        parser.error("specify either --preset, or both --parent and --child")

    os.makedirs(CLI_CWD_HINT, exist_ok=True)
    print(f"ensured cwd_hint dir exists: {CLI_CWD_HINT}")

    db = SessionLocal()
    try:
        admin = find_or_create_admin(db)
        print(f"using parent account id={admin.id} username={admin.username}")

        # Upsert the skills we need for all referenced runtimes.
        needed_runtimes = {rt for pair in pairs for rt in pair}
        skills_by_runtime: dict[str, Skill] = {}
        for rt_key in sorted(needed_runtimes):
            sk = _upsert_child_skill(db, rt_key, admin.id)
            skills_by_runtime[rt_key] = sk
            print(f"  skill {rt_key:<6} id={sk.id} name={sk.name!r}")

        created = []
        for parent_rt, child_rt in pairs:
            name = wf_name(parent_rt, child_rt)
            delete_workflow_by_name(db, name)
            wf = build_workflow(
                db,
                name=name,
                description=f"親={_label(parent_rt)}, 子={_label(child_rt)} のテストワークフロー",
                creator_id=admin.id,
                parent_runtime=parent_rt,
                child_skill=skills_by_runtime[child_rt],
                child_runtime=child_rt,
            )
            created.append(wf)

        db.commit()
        for wf in created:
            print(f"created wf id={wf.id} name={wf.name!r}")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
