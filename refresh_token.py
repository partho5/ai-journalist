"""
Standalone FB token refresher – meant to be run by a monthly cron job.

Usage: python refresh_token.py
Cron:  0 0 1 * *  /path/to/venv/bin/python /path/to/refresh_token.py >> /path/to/logs/token_refresh.log 2>&1
"""

from dotenv import load_dotenv

load_dotenv()

from src import database as db
from src.logger import get_logger
from src.token_manager import refresh_tokens

log = get_logger("refresh_token")

if __name__ == "__main__":
    db.init_db()
    try:
        refresh_tokens()
        log.info("Token refresh completed successfully.")
    except Exception as exc:
        log.error("Token refresh FAILED: %s", exc)
        raise SystemExit(1) from exc
