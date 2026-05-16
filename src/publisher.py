"""
Facebook Graph API publisher.

post_article(article, editorial_text, settings) → fb_post_id or None

Image posting uses a two-step approach to prevent double-posts:
  1. Upload photo as unpublished asset  → get photo_id   (no post visible yet)
  2. Create feed post referencing photo → get post_id    (post becomes visible)

If step 1 fails: nothing was posted, safe to surface error.
If step 2 fails: orphan unpublished photo left behind (invisible, harmless), no post visible.
"""

import json
from typing import Dict, Optional

import requests

from src.logger import get_logger
from src.photo_card import PhotoCardGenerator

log = get_logger(__name__)
_card_gen = PhotoCardGenerator()


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


def _prepare_image_bytes(image_url: str, headline: str) -> Optional[tuple]:
    """Build image bytes locally (no FB call). Returns (bytes, content_type) or None."""
    try:
        img_bytes = _card_gen.generate_bytes(image_url, headline)
        return img_bytes, "image/png"
    except Exception as exc:
        log.warning("Photo card generation failed (%s) — trying raw image download", exc)
        return _download_image(image_url)


def _upload_photo_unpublished(
    img_bytes: bytes,
    content_type: str,
    page_id: str,
    page_token: str,
    api_version: str,
) -> str:
    """
    Upload photo as an unpublished asset. No post is created yet.
    Returns photo_id on success. Raises on any failure.
    """
    resp = requests.post(
        _graph_url(api_version, f"{page_id}/photos"),
        data={
            "published": "false",
            "access_token": page_token,
        },
        files={"source": ("image", img_bytes, content_type)},
        timeout=60,
    )
    resp.raise_for_status()
    photo_id = resp.json().get("id")
    if not photo_id:
        raise ValueError(f"FB photo upload returned no id: {resp.text[:200]}")
    return photo_id


def _post_feed_with_photo(
    photo_id: str,
    message: str,
    page_id: str,
    page_token: str,
    api_version: str,
) -> str:
    """
    Create a feed post with the pre-uploaded photo attached.
    Returns post_id on success. Raises on any failure.
    """
    resp = requests.post(
        _graph_url(api_version, f"{page_id}/feed"),
        data={
            "message": message,
            "attached_media": json.dumps([{"media_fbid": photo_id}]),
            "access_token": page_token,
        },
        timeout=30,
    )
    resp.raise_for_status()
    post_id = resp.json().get("id")
    if not post_id:
        raise ValueError(f"FB feed post returned no id: {resp.text[:200]}")
    return post_id


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
        card_headline = article.get("card_headline") or article.get("headline", "")
        prepared = _prepare_image_bytes(image_url, card_headline)

        if prepared:
            img_bytes, content_type = prepared

            # Step 1: upload unpublished photo — no post visible yet
            try:
                photo_id = _upload_photo_unpublished(
                    img_bytes, content_type, page_id, page_token, api_version
                )
            except Exception as exc:
                log.warning(
                    "Photo upload failed for '%s': %s — not falling back to avoid double-post",
                    article["headline"][:70], exc,
                )
                return None

            # Step 2: create feed post referencing the photo
            try:
                post_id = _post_feed_with_photo(
                    photo_id, editorial_text, page_id, page_token, api_version
                )
                log.info(
                    "Published to Facebook (with image): post_id=%s | headline=%s",
                    post_id, article["headline"][:70],
                )
                return post_id
            except Exception as exc:
                # Unpublished photo orphaned — invisible to followers, harmless
                log.warning(
                    "Feed post failed after photo upload (photo_id=%s) for '%s': %s",
                    photo_id, article["headline"][:70], exc,
                )
                return None

        # Image bytes couldn't be prepared locally — no FB call was made, safe to fall back
        log.info("Image bytes unavailable — falling back to text-only post")

    # Text-only path: only reached when no image_url, or image bytes prep failed locally
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
            post_id, article["headline"][:70],
        )
        return post_id
    except requests.RequestException as exc:
        body = exc.response.text[:300] if exc.response is not None else ""
        log.error(
            "Facebook post failed for '%s': %s | response: %s",
            article["headline"][:70], exc, body,
        )
        return None
