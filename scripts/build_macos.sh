#!/usr/bin/env bash
# Build a local macOS test app. Run this script from a Mac terminal.
set -euo pipefail

project_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project_root"

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pip install .
python -m PyInstaller hipersonalization_assistant.spec --clean --noconfirm

echo "Build complete: $project_root/dist/hipersonalization订单处理助手 v0.13 by Robin+Codex.app"
