"""
Cross-source deduplication.

Sends all new headlines to OpenAI and asks it to group stories about
the same real-world event. Returns only one representative article per
topic group (the one with the longest body text = most detail).
"""

import json
from typing import Dict, List, Optional

from openai import OpenAI

from src.logger import get_logger

log = get_logger(__name__)


def _build_prompt(headlines: List[str], existing: Optional[List[str]] = None) -> str:
    numbered = "\n".join(f"{i}. {h}" for i, h in enumerate(headlines))
    existing_section = ""
    if existing:
        existing_lines = "\n".join(f"- {h}" for h in existing)
        existing_section = (
            "ALREADY COVERED topics — discard any new article about the same event:\n"
            f"{existing_lines}\n\n"
        )
    return (
        "Group the following news headlines by topic.\n"
        "Two headlines belong in the same group ONLY if they report the SAME specific event "
        "(same incident, same decision, same statement). "
        "Sharing a location, person, or keyword is NOT enough — "
        "the core subject and event must be identical. "
        "When in doubt, keep them as separate groups.\n\n"
        f"{existing_section}"
        f"New headlines (0-indexed):\n{numbered}\n\n"
        "Return ONLY valid JSON — no prose:\n"
        '{"groups": [[0, 2], [1], [3, 4]]}\n'
        "Each inner array is a group of zero-based indices of the NEW headlines above. "
        "Omit any index ONLY IF its specific event is already covered by an already-covered headline — "
        "shared keywords or location alone do not count as a duplicate."
    )


def deduplicate(
    articles: List[Dict],
    client: OpenAI,
    model: str,
    existing_headlines: Optional[List[str]] = None,
) -> List[Dict]:
    """
    Returns one representative article per topic group.
    Duplicates (within batch or against existing_headlines) are discarded.
    """
    if not articles:
        return []

    if len(articles) == 1 and not existing_headlines:
        return articles

    headlines = [a["headline"] for a in articles]
    prompt = _build_prompt(headlines, existing_headlines)

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
        )
        msg = resp.choices[0].message
        raw = (msg.content or "").strip()
        if not raw and hasattr(msg, "reasoning_content"):
            raw = (msg.reasoning_content or "").strip()
        data = json.loads(raw)
        groups: List[List[int]] = data["groups"]
    except Exception as exc:
        log.error("Deduplication AI call failed: %s — treating all as unique", exc)
        return articles

    unique: List[Dict] = []

    for group in groups:
        if not group:
            continue
        representative = max(
            (articles[i] for i in group if i < len(articles)),
            key=lambda a: len(a.get("body_text") or ""),
        )
        unique.append(representative)

    log.info(
        "Deduplication: %d articles → %d unique (%d discarded)",
        len(articles),
        len(unique),
        len(articles) - len(unique),
    )
    return unique
