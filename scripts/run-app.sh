#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
MANAGER_PORT="${MANAGER_PORT:-3013}"

if [[ ! -x "$VENV_DIR/bin/uvicorn" ]]; then
  echo "uvicorn が見つかりません。次のコマンドを実行してください: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

exec "$VENV_DIR/bin/uvicorn" agent_sandbox.app:app --app-dir "$ROOT_DIR" --host 0.0.0.0 --port "$MANAGER_PORT" --reload
