"""Coordinator adapter management API.

Read-only listing + health refresh + cached models lookup.
Used by the desktop app's adapter settings panel.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Account, CoordinatorAdapter
from app.services.coordinator_extensions import (
    list_adapters,
    refresh_local_adapter_health,
)

router = APIRouter(prefix="/api/adapters", tags=["adapters"])


def _adapter_to_dict(adapter: CoordinatorAdapter) -> dict[str, Any]:
    config: Any = None
    if adapter.config:
        try:
            config = json.loads(adapter.config)
        except json.JSONDecodeError:
            config = None
    return {
        "adapter_id": adapter.adapter_id,
        "name": adapter.name,
        "adapter_type": adapter.adapter_type,
        "provider_mode": adapter.provider_mode,
        "transport": adapter.transport,
        "runtime": adapter.runtime,
        "impl": adapter.impl,
        "is_enabled": adapter.is_enabled,
        "health_status": adapter.health_status,
        "last_health_check": (
            adapter.last_health_check.isoformat() + "Z"
            if adapter.last_health_check
            else None
        ),
        "config": config,
    }


@router.get("")
async def list_all_adapters(
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user),
):
    adapters = list_adapters(db, only_enabled=False)
    return {"adapters": [_adapter_to_dict(a) for a in adapters]}


@router.post("/{adapter_id}/health/refresh")
async def refresh_adapter_health(
    adapter_id: str,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user),
):
    adapter = refresh_local_adapter_health(db, adapter_id)
    if adapter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"adapter not found: {adapter_id}",
        )
    return _adapter_to_dict(adapter)


@router.get("/{adapter_id}/models")
async def get_cached_models(
    adapter_id: str,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user),
):
    """Return cached model list from the last health refresh.

    Does NOT re-probe — call POST /health/refresh first if you need fresh
    data.
    """
    adapter = (
        db.query(CoordinatorAdapter)
        .filter(CoordinatorAdapter.adapter_id == adapter_id)
        .first()
    )
    if adapter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"adapter not found: {adapter_id}",
        )
    config: Optional[dict[str, Any]] = None
    if adapter.config:
        try:
            config = json.loads(adapter.config)
        except json.JSONDecodeError:
            config = None
    detail = (config or {}).get("last_health_detail") or {}
    return {
        "adapter_id": adapter.adapter_id,
        "models": detail.get("models") or [],
        "checked_at": detail.get("checked_at"),
        "status": detail.get("status") or adapter.health_status,
    }
