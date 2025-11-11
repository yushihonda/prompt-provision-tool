#!/usr/bin/env bash
# ============================================================
# ローカル開発環境用起動スクリプト
# 本番環境（ConoHaVPS）では使用しません
# ============================================================

set -e

echo "[backend] waiting for database..."
sleep 5

# 可能ならマイグレーション（失敗しても継続）
if [ -f "/app/alembic.ini" ]; then
  echo "[backend] running alembic upgrade (best-effort)"
  alembic upgrade head || echo "[backend] alembic skipped"
fi

echo "[backend] starting uvicorn"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2


