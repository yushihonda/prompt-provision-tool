#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if command -v project-audit >/dev/null 2>&1; then
  exec project-audit "$ROOT"
fi

cd "$ROOT"

echo "[audit] 自動監査を開始します。"

if [[ ! -d node_modules ]]; then
  echo "[audit] node_modules がありません。先に: npm install" >&2
  exit 1
fi

echo "[audit] Mermaid (.mmd) を PNG に変換中..."
mkdir -p docs/diagrams
shopt -s nullglob
mmd_files=(docs/*.mmd)
if ((${#mmd_files[@]})); then
  for file in "${mmd_files[@]}"; do
    base=$(basename "$file" .mmd)
    npx --no-install mmdc -i "$file" -o "docs/diagrams/${base}.png" -t dark -b transparent
  done
  echo "[audit] 図解の生成が完了しました。"
else
  echo "[audit] docs/*.mmd が見つかりません。スキップします。"
fi
shopt -u nullglob

echo "[audit] コード規模を計測中（cloc）..."
mkdir -p docs
npx --no-install cloc . \
  --exclude-dir=node_modules,.git,dist,build,venv,.venv,__pycache__,.pytest_cache,.serena,uploads,temp,htmlcov,.tox,.nox \
  > docs/complexity_report.txt
echo "[audit] docs/complexity_report.txt に出力しました。"

echo "[audit] 完了しました。"
