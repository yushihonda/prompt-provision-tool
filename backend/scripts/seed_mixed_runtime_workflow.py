#!/usr/bin/env python3
"""混合ランタイムワークフローのサンプルを開発 DB に投入する。

パイプライン構造（調査 -> 並列実装 -> 検証）:

  グループ 1（直列）: research_step  -> HTTP provider
  グループ 2（並列）: claude_impl    -> Claude Code CLI（allow_write）
                      codex_impl     -> OpenAI Codex CLI（allow_write）
  グループ 3（直列）: verify_step    -> HTTP provider で両方の出力を比較

使い方:
    cd backend
    python scripts/seed_mixed_runtime_workflow.py [--account-id 1] [--dry-run]

このスクリプトは冪等: 再実行すると同名の古いワークフローを削除し、
現在のスキル ID で再作成する。

実行後、desktop アプリにログインしてワークフローに移動し、トリガーする。
各ステップは resolve_execution_kind を通じて宣言されたランタイムに
ルーティングされ、完全な来歴がアーティファクトメタデータに記録される。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# backend/ から実行した際に `app.*` をインポート可能にする。
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

WORKFLOW_NAME = "Mixed Runtime Demo (research -> parallel impl -> verify)"


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
    """execution_config をインラインで含む config_json blob を構築する。"""
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
    # アカウントにスキルが付与されていることを確認する。
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
        # デフォルトアダプタの存在を保証（claude-code-local, codex-local 等）
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

        # グループ構成: 調査 -> 並列（claude|codex） -> 検証
        groups = [
            {
                "group_order": 1,
                "group_name": "research",
                "execution_type": "serial",
                "steps": [
                    {
                        "name": "demo-research-step",
                        "model_type": "gpt-4o-mini",
                        "prompt": (
                            "You are a research agent. Given the user's topic, list 3 short "
                            "bullet points summarizing the most important facts. Be concise."
                        ),
                        "config": execution_config_for(
                            execution_kind="provider",
                            approval_policy="read_only",
                        ),
                        "agent_profile": "explore",
                    },
                ],
            },
            {
                "group_order": 2,
                "group_name": "parallel-implementations",
                "execution_type": "parallel",
                "steps": [
                    {
                        "name": "demo-claude-impl",
                        "model_type": "claude_code",
                        "prompt": (
                            "You are a coding agent invoked via Claude Code CLI. Based on the "
                            "research notes, implement a minimal working example for the topic "
                            "by writing files into the working directory. End with a short "
                            "summary of what you created."
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
                        "agent_profile": "implement",
                    },
                    {
                        "name": "demo-codex-impl",
                        "model_type": "codex",
                        "prompt": (
                            "You are a coding agent invoked via OpenAI Codex CLI. Based on the "
                            "research notes, implement a minimal working example for the topic "
                            "by writing files into the working directory. End with a short "
                            "summary of what you created."
                        ),
                        "config": execution_config_for(
                            execution_kind="external_cli",
                            preferred_adapter="codex-local",
                            cli_runtime_hint="codex",
                            workspace_policy="temp_dir",
                            approval_policy="allow_write",
                            allow_writes=True,
                            allow_shell=False,
                            required_capabilities=["file_read", "file_write", "workspace_aware"],
                            cwd_hint=cwd_hint,
                        ),
                        "agent_profile": "implement",
                    },
                ],
            },
            {
                "group_order": 3,
                "group_name": "verify",
                "execution_type": "serial",
                "steps": [
                    {
                        "name": "demo-verify-step",
                        "model_type": "gpt-4o-mini",
                        "prompt": (
                            "You are a verification judge. Two implementations were produced "
                            "in parallel (Claude Code and Codex). Compare their outputs, pick "
                            "the stronger one, and explain why. Output ACCEPTED/REJECTED on "
                            "the first line, then a short rationale."
                        ),
                        "config": execution_config_for(
                            execution_kind="auto",  # judge is hard-routed to remote regardless
                            approval_policy="read_only",
                        ),
                        "agent_profile": "verification",
                    },
                ],
            },
        ]

        if args.dry_run:
            print("--- DRY RUN ---")
            for g in groups:
                print(f"  group {g['group_order']} [{g['execution_type']}] {g['group_name']}")
                for s in g["steps"]:
                    print(f"    - {s['name']} model={s['model_type']}")
            return

        # 全スキルを upsert し、紐付け用に (skill, spec, group_index) を記録する。
        skill_entries = []  # list of (skill_row, step_spec, group_dict)
        for g in groups:
            for s in g["steps"]:
                sk = upsert_skill(
                    db,
                    name=s["name"],
                    prompt=s["prompt"],
                    model_type=s["model_type"],
                    account_id=account_id,
                )
                skill_entries.append((sk, s, g))
                print(f"  upserted skill id={sk.id} name={sk.name}")

        # 既存のデモワークフローがあれば削除する。
        prior = db.query(Workflow).filter(
            Workflow.name == WORKFLOW_NAME,
            Workflow.deleted_at.is_(None) if hasattr(Workflow, "deleted_at") else True,
        ).first()
        if prior:
            db.query(WorkflowSkill).filter(WorkflowSkill.workflow_id == prior.id).delete()
            db.query(WorkflowGroup).filter(WorkflowGroup.workflow_id == prior.id).delete()
            db.delete(prior)
            db.commit()
            print(f"  removed prior workflow id={prior.id}")

        # ワークフローを作成する。
        wf = Workflow(
            name=WORKFLOW_NAME,
            description=(
                "Research -> parallel implementation (Claude Code CLI + Codex CLI) -> verify. "
                "Demonstrates mixed runtime execution in a single workflow."
            ),
            is_active=True,
            created_by=account_id,
        )
        db.add(wf)
        db.commit()
        db.refresh(wf)
        print(f"created workflow id={wf.id} name={wf.name}")

        # グループを作成する。
        group_id_by_order = {}
        for g in groups:
            grp = WorkflowGroup(
                workflow_id=wf.id,
                group_order=g["group_order"],
                group_name=g["group_name"],
                execution_type=g["execution_type"],
            )
            db.add(grp)
            db.commit()
            db.refresh(grp)
            group_id_by_order[g["group_order"]] = grp.id
            print(f"  created group id={grp.id} order={g['group_order']} type={g['execution_type']}")

        # スキルを execution_config + グループ紐付けで添付する。
        skill_order_counter = 0
        order_in_group_counter: dict[int, int] = {}
        for sk, spec, g in skill_entries:
            skill_order_counter += 1
            gid = group_id_by_order[g["group_order"]]
            order_in_group_counter[gid] = order_in_group_counter.get(gid, 0) + 1
            ws = WorkflowSkill(
                workflow_id=wf.id,
                skill_id=sk.id,
                skill_order=skill_order_counter,
                skill_name=spec["name"],
                config_json=json.dumps(spec["config"], ensure_ascii=False),
                agent_profile=spec.get("agent_profile"),
                group_id=gid,
                order_in_group=order_in_group_counter[gid],
            )
            db.add(ws)
        db.commit()
        print(f"attached {len(skill_entries)} steps across {len(groups)} groups")

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
