"""
Criteria filtering and engagement ranking.

apply_criteria(articles, prompt, ...) → matching articles
rank_articles(articles, prompt, max_posts, ...) → top N articles
"""

import json
from typing import Dict, List

from openai import OpenAI

from src.logger import get_logger

log = get_logger(__name__)


def apply_criteria(
    articles: List[Dict],
    criteria_prompt: str,
    client: OpenAI,
    model: str,
    max_tokens: int,
) -> List[Dict]:
    """Return only the articles that pass the editorial criteria prompt."""
    if not articles:
        return []

    numbered = "\n".join(
        f"{i}. {a['headline']}" for i, a in enumerate(articles)
    )
    full_prompt = f"{criteria_prompt}\n\nHeadlines:\n{numbered}"

    kwargs = {}
    if max_tokens:
        kwargs["max_completion_tokens"] = max_tokens
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": full_prompt}],
            **kwargs,
        )
        msg = resp.choices[0].message
        raw = (msg.content or "").strip()
        if not raw and hasattr(msg, "reasoning_content"):
            raw = (msg.reasoning_content or "").strip()
        indices: List[int] = json.loads(raw)
    except Exception as exc:
        log.error("Criteria filter AI call failed: %s — keeping all articles", exc)
        return articles

    passed = [articles[i] for i in indices if i < len(articles)]
    log.info(
        "Criteria filter: %d → %d articles passed", len(articles), len(passed)
    )
    return passed


def rank_articles(
    articles: List[Dict],
    ranking_prompt_template: str,
    max_posts: int,
    client: OpenAI,
    model: str,
    max_tokens: int,
) -> List[Dict]:
    """Return up to max_posts articles sorted by engagement potential."""
    if not articles:
        return []

    if len(articles) <= max_posts:
        log.info("Ranking: fewer articles than max_posts — using all %d", len(articles))
        return articles

    numbered = "\n".join(
        f"{i}. {a['headline']}" for i, a in enumerate(articles)
    )
    prompt = (
        ranking_prompt_template.replace("{max_posts}", str(max_posts))
        + f"\n\nHeadlines:\n{numbered}"
    )

    kwargs = {}
    if max_tokens:
        kwargs["max_completion_tokens"] = max_tokens
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            **kwargs,
        )
        msg = resp.choices[0].message
        raw = (msg.content or "").strip()
        if not raw and hasattr(msg, "reasoning_content"):
            raw = (msg.reasoning_content or "").strip()
        indices: List[int] = json.loads(raw)
    except Exception as exc:
        log.error("Ranking AI call failed: %s — using first %d articles", exc, max_posts)
        return articles[:max_posts]

    ranked = [articles[i] for i in indices if i < len(articles)][:max_posts]
    log.info("Ranking: selected %d from %d articles", len(ranked), len(articles))
    return ranked
