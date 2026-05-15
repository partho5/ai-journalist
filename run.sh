#!/usr/bin/env bash
# Resolve the project directory from this script's location — no hardcoded paths.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/venv/bin/python3" "$DIR/main.py" >> "$DIR/logs/cron.log" 2>&1
