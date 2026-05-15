"""
Facebook Graph API publisher.

post_article(article, editorial_text, settings) → fb_post_id or None
"""

from typing import Dict, Optional

import requests

from src.logger import get_logger

log = get_logger(__name__)


def _graph_url(version: str, path: str) -> str:
    return f"https://graph.facebook.com/{version}/{path}"


def _download_image(image_url: str) -> Optional[tuple]:
    """Download image bytes. Returns (bytes, content_type) or None."""
    try:
        resp = requests.get(image_url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
        return resp.content, content_type
    except Exception as exc:
        log.warning("Could not download image %s: %s", image_url, exc)
        return None


def _post_with_image(
    image_url: str,
    message: str,
    page_id: str,
    page_token: str,
    api_version: str,
) -> Optional[str]:
    """Download image then upload as binary to /photos with caption. Returns post ID or None."""
    downloaded = _download_image(image_url)
    if not downloaded:
        return None
    img_bytes, content_type = downloaded

    try:
        resp = requests.post(
            _graph_url(api_version, f"{page_id}/photos"),
            data={
                "message": message,
                "access_token": page_token,
            },
            files={"source": ("image", img_bytes, content_type)},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json().get("post_id") or resp.json().get("id")
    except Exception as exc:
        log.warning("Photo post failed (%s): %s — falling back to text-only", image_url, exc)
        return None


def post_article(
    article: Dict,
    editorial_text: str,
    page_id: str,
    page_token: str,
    api_version: str,
    include_image: bool,
) -> Optional[str]:
    """
    Post the editorial to a Facebook page.

    Returns the FB post ID on success, None on failure.
    """
    image_url = article.get("image_url") if include_image else None

    if image_url:
        post_id = _post_with_image(image_url, editorial_text, page_id, page_token, api_version)
        if post_id:
            log.info(
                "Published to Facebook (with image): post_id=%s | headline=%s",
                post_id,
                article["headline"][:70],
            )
            return post_id
        log.info("Retrying as text-only post after image failure")

    try:
        resp = requests.post(
            _graph_url(api_version, f"{page_id}/feed"),
            data={
                "message": editorial_text,
                "access_token": page_token,
            },
            timeout=30,
        )
        resp.raise_for_status()
        post_id = resp.json().get("id")
        log.info(
            "Published to Facebook (text-only): post_id=%s | headline=%s",
            post_id,
            article["headline"][:70],
        )
        return post_id
    except requests.RequestException as exc:
        body = exc.response.text[:300] if exc.response is not None else ""
        log.error(
            "Facebook post failed for '%s': %s | response: %s",
            article["headline"][:70],
            exc,
            body,
        )
        return None
