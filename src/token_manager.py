"""
Facebook token lifecycle manager.

Flow
----
1. Read long-lived user token (from DB first, then .env fallback).
2. Exchange it for a fresh long-lived user token (valid 60 days).
3. Fetch the page access token from the new user token.
4. Persist both tokens in the DB.

Page access tokens derived from a long-lived user token never expire,
so step 3 only needs to run when the user token is refreshed.
"""

import os
from typing import Optional

import requests

from src import database as db
from src.logger import get_logger

log = get_logger(__name__)

_GRAPH = "https://graph.facebook.com/v19.0"

TOKEN_KEY_USER = "fb_user_token"
TOKEN_KEY_PAGE = "fb_page_token"


def _env(key: str) -> str:
    value = os.getenv(key, "").strip()
    if not value:
        raise EnvironmentError(f"Required env var '{key}' is not set.")
    return value


def get_page_token() -> str:
    """
    Return a valid page access token.
    Reads from DB; falls back to refreshing from env if missing.
    """
    token = db.get_token(TOKEN_KEY_PAGE)
    if token:
        return token
    log.info("No page token in DB — running full refresh to obtain one.")
    refresh_tokens()
    token = db.get_token(TOKEN_KEY_PAGE)
    if not token:
        raise RuntimeError(
            "Could not obtain a Facebook page token. "
            "Run 'python refresh_token.py' and check your .env credentials."
        )
    return token


def refresh_tokens() -> None:
    """
    Refresh FB user token and derive a fresh page access token.
    Call this from a monthly cron job via refresh_token.py.
    """
    app_id = _env("FB_APP_ID")
    app_secret = _env("FB_APP_SECRET")
    page_id = _env("FB_PAGE_ID")

    # prefer stored token; fall back to .env initial token
    current_user_token = db.get_token(TOKEN_KEY_USER) or _env("FB_USER_TOKEN")

    log.info("Refreshing Facebook long-lived user token…")
    new_user_token = _exchange_token(app_id, app_secret, current_user_token)
    db.save_token(TOKEN_KEY_USER, new_user_token)
    log.info("User token refreshed and saved.")

    log.info("Fetching page access token…")
    page_token = _fetch_page_token(page_id, new_user_token)
    db.save_token(TOKEN_KEY_PAGE, page_token)
    log.info("Page token saved.")


def _exchange_token(app_id: str, app_secret: str, short_token: str) -> str:
    """Exchange any user token for a new long-lived user token (60 days)."""
    resp = requests.get(
        f"{_GRAPH}/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": short_token,
        },
        timeout=20,
    )
    _raise_for_fb_error(resp, "token exchange")
    token = resp.json().get("access_token")
    if not token:
        raise RuntimeError(f"No access_token in exchange response: {resp.text}")
    return token


def _fetch_page_token(page_id: str, user_token: str) -> str:
    """Retrieve the page access token for page_id using the user token."""
    resp = requests.get(
        f"{_GRAPH}/{page_id}",
        params={"fields": "access_token", "access_token": user_token},
        timeout=20,
    )
    _raise_for_fb_error(resp, "page token fetch")
    token = resp.json().get("access_token")
    if not token:
        raise RuntimeError(
            f"No access_token in page token response: {resp.text}\n"
            "Make sure your user token has 'pages_show_list' and 'pages_read_engagement' permissions."
        )
    return token


def _raise_for_fb_error(resp: requests.Response, context: str) -> None:
    try:
        resp.raise_for_status()
    except requests.HTTPError:
        error_body = resp.text[:400]
        raise RuntimeError(f"Facebook API error during {context}: {error_body}") from None
