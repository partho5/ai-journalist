#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Project dir: $DIR"

# Track what was actually done
ACTIONS=()

# --- system fonts --------------------------------------------------------
if ! fc-list | grep -qi "NotoSansBengali"; then
    echo "==> Installing Noto Bengali fonts..."
    sudo apt-get install -y fonts-noto-core
    ACTIONS+=("Installed system font: fonts-noto-core (NotoSansBengali)")
else
    ACTIONS+=("System font: fonts-noto-core already present (skipped)")
fi

# --- venv ----------------------------------------------------------------
if [ ! -f "$DIR/venv/bin/python3" ]; then
    echo "==> Creating virtual environment..."
    python3 -m venv "$DIR/venv"
    ACTIONS+=("Created Python virtual environment: $DIR/venv")
else
    ACTIONS+=("Virtual environment: already exists (skipped)")
fi

echo "==> Installing / upgrading dependencies..."
PIP_OUT=$("$DIR/venv/bin/pip" install --upgrade pip 2>&1)
PIP_PKGS=$("$DIR/venv/bin/pip" install --upgrade -r "$DIR/requirements.txt" 2>&1)

# Count newly installed/upgraded packages (lines containing "Successfully installed")
INSTALLED=$(echo "$PIP_PKGS" | grep -c "^Successfully installed" || true)
if [ "$INSTALLED" -gt 0 ]; then
    PKG_NAMES=$(echo "$PIP_PKGS" | grep "^Successfully installed" | sed 's/Successfully installed //')
    ACTIONS+=("Installed/upgraded pip packages: $PKG_NAMES")
else
    ACTIONS+=("Pip packages: all up to date (skipped)")
fi

# --- runtime dirs --------------------------------------------------------
DIRS_CREATED=()
for d in "$DIR/data" "$DIR/logs"; do
    [ ! -d "$d" ] && DIRS_CREATED+=("$d")
    mkdir -p "$d"
done
if [ ${#DIRS_CREATED[@]} -gt 0 ]; then
    ACTIONS+=("Created directories: ${DIRS_CREATED[*]}")
else
    ACTIONS+=("Runtime directories: already exist (skipped)")
fi

# --- run.sh --------------------------------------------------------------
chmod +x "$DIR/run.sh"

# --- cron (idempotent) ---------------------------------------------------
CRON_JOB="0 0,8-23 * * * $DIR/run.sh"
PREV_CRON=$(crontab -l 2>/dev/null | grep -F "$DIR/run.sh" || true)

(crontab -l 2>/dev/null | grep -vF "$DIR/run.sh"; echo "$CRON_JOB") | crontab -

if [ -z "$PREV_CRON" ]; then
    ACTIONS+=("Cron job: newly registered  →  $CRON_JOB")
elif [ "$PREV_CRON" = "$CRON_JOB" ]; then
    ACTIONS+=("Cron job: unchanged  →  $CRON_JOB")
else
    ACTIONS+=("Cron job: updated")
    ACTIONS+=("  old: $PREV_CRON")
    ACTIONS+=("  new: $CRON_JOB")
fi

# --- summary -------------------------------------------------------------
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                  DEPLOY SUMMARY                              ║"
echo "╠══════════════════════════════════════════════════════════════╣"
for action in "${ACTIONS[@]}"; do
    printf "║  %-62s║\n" "$action"
done
echo "╠══════════════════════════════════════════════════════════════╣"
printf "║  %-62s║\n" "Schedule: every hour 08:00–00:00 (midnight), daily"
printf "║  %-62s║\n" "Log file: $DIR/logs/journalist.log"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
