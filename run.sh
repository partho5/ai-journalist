#!/usr/bin/env bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"
exec "$DIR/venv/bin/python3" "$DIR/main.py" >> "$DIR/logs/cron.log" 2>&1
