"""
Editorial writer – turns a raw article into a Facebook-ready post.
"""

from typing import Dict, Optional

from openai import OpenAI

from src.logger import get_logger

log = get_logger(__name__)


def write_editorial(
    article: Dict,
    writing_prompt: str,
    client: OpenAI,
    model: str,
    max_tokens: int,
    temperature: Optional[float] = None,
) -> Optional[str]:
    """
    Generate a Facebook post from a raw article.

    Returns the post text, or None if the AI call fails.
    """
    body_snippet = (article.get("body_text") or "")[:3000]  # stay within context
    user_content = (
        f"{writing_prompt}\n\n"
        f"Headline: {article['headline']}\n\n"
        f"Article body:\n{body_snippet}"
    )

    kwargs = {}
    if max_tokens:
        kwargs["max_completion_tokens"] = max_tokens
    if temperature is not None:
        kwargs["temperature"] = temperature
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": user_content}],
            **kwargs,
        )
        msg = resp.choices[0].message
        # gpt-5-nano (reasoning model) may return content=None with output in
        # reasoning_content; fall back gracefully
        text = (msg.content or "").strip()
        if not text and hasattr(msg, "reasoning_content"):
            text = (msg.reasoning_content or "").strip()
        if not text:
            log.error(
                "Writing AI returned empty content for '%s' — finish_reason=%s "
                "msg_fields=%s",
                article["headline"][:70],
                resp.choices[0].finish_reason,
                [k for k, v in vars(msg).items() if v],
            )
            return None
        text = text.replace("—", ",")
        log.info("Editorial written for: %s", article["headline"][:70])
        return text
    except Exception as exc:
        log.error(
            "Writing AI call failed for '%s': %s",
            article["headline"][:70],
            exc,
        )
        return None
