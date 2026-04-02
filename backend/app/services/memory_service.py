"""
ワークフロー永続メモリサービス

workflow × agent_profile 単位の長期記憶。
blackboard_data（1実行内の共有メモリ）とは異なり、実行をまたいで蓄積される。
"""
import json
import logging
from typing import Optional
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def get_memory(db: Session, workflow_id: int, profile: str) -> Optional[str]:
    """指定 workflow + profile のメモリを取得。なければ None。"""
    from app.models import WorkflowMemory
    mem = db.query(WorkflowMemory).filter(
        WorkflowMemory.workflow_id == workflow_id,
        WorkflowMemory.profile == profile,
    ).first()
    if not mem:
        return None
    return mem.memory_data


def get_or_init_memory(db: Session, workflow_id: int, profile: str) -> str:
    """メモリを取得。初回は starter_seed から初期化。"""
    from app.models import WorkflowMemory
    mem = db.query(WorkflowMemory).filter(
        WorkflowMemory.workflow_id == workflow_id,
        WorkflowMemory.profile == profile,
    ).first()
    if mem and mem.memory_data:
        return mem.memory_data
    if mem and mem.starter_seed and not mem.memory_data:
        # 初回: seed → memory に初期化
        mem.memory_data = mem.starter_seed
        db.commit()
        logger.info(f"Memory initialized from seed: workflow={workflow_id}, profile={profile}")
        return mem.memory_data
    return ""


def update_memory(db: Session, workflow_id: int, profile: str, summary: str) -> None:
    """メモリに要約を追記。存在しなければ作成。"""
    from app.models import WorkflowMemory
    if not summary or not summary.strip():
        return
    mem = db.query(WorkflowMemory).filter(
        WorkflowMemory.workflow_id == workflow_id,
        WorkflowMemory.profile == profile,
    ).first()
    if not mem:
        mem = WorkflowMemory(
            workflow_id=workflow_id,
            profile=profile,
            memory_data="",
        )
        db.add(mem)

    # 既存メモリに追記（最大10000文字制限）
    existing = mem.memory_data or ""
    entry = f"\n---\n{summary.strip()}"
    updated = (existing + entry).strip()
    if len(updated) > 10000:
        # 古い部分を切り捨て
        lines = updated.split("\n---\n")
        while len("\n---\n".join(lines)) > 10000 and len(lines) > 1:
            lines.pop(0)
        updated = "\n---\n".join(lines)
    mem.memory_data = updated
    db.commit()
    logger.info(f"Memory updated: workflow={workflow_id}, profile={profile}, length={len(updated)}")


def build_memory_prompt_section(memory_text: str) -> str:
    """メモリをプロンプトに挿入するセクションを構築。"""
    if not memory_text or not memory_text.strip():
        return ""
    return f"""
# 過去の実行から学んだ記憶
以下は、このワークフローの過去の実行から蓄積された記憶です。参考にしてください。
ただし、今回の入力データと矛盾する場合は、今回の入力を優先してください。

{memory_text.strip()}
"""
