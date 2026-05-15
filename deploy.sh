#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Project dir: $DIR"

# --- system fonts --------------------------------------------------------
if ! fc-list | grep -qi "NotoSansBengali"; then
    echo "==> Installing Noto Bengali fonts (required for photo card)..."
    sudo apt-get install -y fonts-noto-core
else
    echo "==> Noto Bengali fonts already installed."
fi

# --- venv ----------------------------------------------------------------
if [ ! -f "$DIR/venv/bin/python3" ]; then
    echo "==> Creating virtual environment..."
    python3 -m venv "$DIR/venv"
fi

echo "==> Installing / upgrading dependencies..."
"$DIR/venv/bin/pip" install --quiet --upgrade pip
"$DIR/venv/bin/pip" install --quiet --upgrade -r "$DIR/requirements.txt"

# --- runtime dirs --------------------------------------------------------
mkdir -p "$DIR/data" "$DIR/logs"

# --- run.sh --------------------------------------------------------------
chmod +x "$DIR/run.sh"

# --- cron (idempotent) ---------------------------------------------------
CRON_JOB="0 0,8-23 * * * $DIR/run.sh"

# Strip any previous entry for this project, then append the fresh one.
(crontab -l 2>/dev/null | grep -vF "$DIR/run.sh"; echo "$CRON_JOB") | crontab -

echo ""
echo "==> Done. Cron installed:"
echo "    $CRON_JOB"
echo ""
echo "Runs every hour from 08:00 to 00:00 (midnight)."
