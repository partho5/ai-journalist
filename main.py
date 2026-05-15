"""
AI Journalist Agent – main pipeline entry point.

Run:  python main.py
      python main.py --dry-run     (full pipeline, no FB post)
      python main.py --no-image    (override include_image setting)
      python main.py --reset-db    (clear all scraped articles before running)

Queue-based publish loop
------------------------
Each hourly cron run does ONE of two things:

PUBLISH MODE  — if approved articles exist in the queue, pick the newest,
                write an editorial, post to Facebook, mark published.

INTAKE MODE   — if queue is empty, scrape fresh articles, run dedup/filter/rank,
                mark all passing articles 'approved', then immediately publish 1.
"""

import argparse
import os
import sys

import yaml
from dotenv import load_dotenv
from openai import OpenAI

from src import database as db
from src.deduplicator import deduplicate
from src.filter import apply_criteria, rank_articles
from src.logger import get_logger
from src.publisher import post_article
from src.scraper import scrape_source
from src.token_manager import get_page_token
from src.writer import write_editorial

load_dotenv()

log = get_logger(__name__)


def load_yaml(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        log.error("OPENAI_API_KEY is not set in .env")
        sys.exit(1)
    return OpenAI(api_key=api_key)


def _print_dry_run_result(article: dict, editorial: str, index: int, total: int) -> None:
    sep = "=" * 70
    thin = "-" * 70
    lines = [
        f"\n{sep}",
        f"  DRY RUN — Article {index}/{total}",
        thin,
        f"  Headline : {article['headline']}",
        f"  Source   : {article.get('source_name', 'unknown')}",
        f"  URL      : {article['url']}",
    ]
    if article.get("image_url"):
        lines.append(f"  Image    : {article['image_url']}")
    lines += [thin, "  LLM OUTPUT (Facebook Editorial)", thin, editorial, sep]
    print("\n".join(lines), flush=True)


def _write_and_publish(
    article: dict,
    prompts: dict,
    client: OpenAI,
    ai_cfg: dict,
    fb_cfg: dict,
    page_id: str,
    page_token: str,
    include_image: bool,
    dry_run: bool,
) -> bool:
    """Write editorial + post to FB (or dry-print). Returns True on success."""
    editorial = write_editorial(
        article,
        prompts["writing"],
        client,
        ai_cfg.get("writing_model", ai_cfg["model"]),
        ai_cfg.get("max_tokens_write"),
        ai_cfg.get("temperature_write"),
    )
    if not editorial:
        db.mark_error(article["url"], "Editorial writing failed")
        return False

    if dry_run:
        _print_dry_run_result(article, editorial, 1, 1)
        return True

    post_id = post_article(
        article,
        editorial,
        page_id,
        page_token,
        fb_cfg["graph_api_version"],
        include_image,
    )
    if post_id:
        db.mark_published(article["url"], post_id)
        return True
    else:
        db.mark_error(article["url"], "Facebook post failed")
        return False


def run(dry_run: bool = False, force_no_image: bool = False) -> None:
    log.info("=" * 60)
    log.info("AI Journalist Agent starting")
    log.info("=" * 60)

    settings = load_yaml("config/settings.yaml")
    prompts = load_yaml("config/prompts.yaml")
    sources_cfg = load_yaml("config/sources.yaml")

    max_age = settings["posting"].get("max_article_age_hours", 36)
    include_image = settings["posting"]["include_image"] and not force_no_image
    ai_cfg = settings["openai"]
    fb_cfg = settings["facebook"]

    db.init_db()
    trimmed = db.trim_old_articles(max_rows=100, keep=80)
    if trimmed:
        log.info("Trimmed %d old article(s) from DB (kept newest 80)", trimmed)
    client = build_openai_client()

    # Resolve FB credentials upfront so we fail fast before any expensive work
    page_id = page_token = ""
    if not dry_run:
        page_id = os.getenv("FB_PAGE_ID", "").strip()
        if not page_id:
            log.error("FB_PAGE_ID is not set in .env")
            sys.exit(1)
        try:
            page_token = get_page_token()
        except Exception as exc:
            log.error("Cannot obtain FB page token: %s", exc)
            sys.exit(1)

    # ── Step 0: expire stale approved articles ────────────────────
    expired = db.expire_old_articles(max_age)
    if expired:
        log.info("Expired %d approved article(s) older than %d hours", expired, max_age)

    # ── Step 1: check queue ───────────────────────────────────────
    approved_count = db.count_by_status("approved")
    log.info("Approved articles in queue: %d", approved_count)

    if approved_count >= 1:
        # ── PUBLISH MODE ──────────────────────────────────────────
        log.info("PUBLISH MODE — draining 1 from queue")
        article = db.get_approved_articles()[0]
        log.info("Publishing: %s", article["headline"][:80])
        _write_and_publish(
            article, prompts, client, ai_cfg, fb_cfg,
            page_id, page_token, include_image, dry_run,
        )

    else:
        # ── INTAKE MODE ───────────────────────────────────────────
        log.info("INTAKE MODE — queue empty, scraping fresh articles")
        all_new = []
        for source in sources_cfg.get("sources", []):
            try:
                articles = scrape_source(source, db.is_url_seen, settings)
                all_new.extend(articles)
            except Exception as exc:
                log.error("Source '%s' scrape failed: %s", source.get("name"), exc)

        log.info("Total new articles collected: %d", len(all_new))

        if not all_new:
            log.info("Nothing new to process. Exiting.")
            return

        # Deduplicate — compare within batch AND against last 15 saved headlines
        existing_headlines = db.get_recent_headlines(15)
        unique = deduplicate(all_new, client, ai_cfg["model"], existing_headlines)

        for a in unique:
            try:
                db.save_article(
                    a["source_name"], a["url"], a["headline"],
                    a.get("body_text", ""), a.get("image_url"),
                )
            except Exception as exc:
                log.warning("Could not save article %s: %s", a["url"], exc)

        # Filter
        passed = apply_criteria(
            unique, prompts["criteria"], client,
            ai_cfg["model"], ai_cfg.get("max_tokens_filter"),
        )
        for a in unique:
            if a not in passed:
                db.update_status(a["url"], "filtered_out")

        # Rank ALL passing articles (orders the queue by quality; all get approved)
        ranked = rank_articles(
            passed, prompts["ranking"], len(passed), client,
            ai_cfg["model"], ai_cfg.get("max_tokens_filter"),
        )
        for a in passed:
            if a not in ranked:
                db.update_status(a["url"], "filtered_out")

        for a in ranked:
            db.update_status(a["url"], "approved")

        log.info(
            "Intake — collected: %d | unique: %d | passed filter: %d | approved: %d",
            len(all_new), len(unique), len(passed), len(ranked),
        )

        if not ranked:
            log.info("No articles passed filter this run.")
            return

        # Publish 1 immediately (newest approved)
        article = db.get_approved_articles()[0]
        log.info("Publishing immediately: %s", article["headline"][:80])
        success = _write_and_publish(
            article, prompts, client, ai_cfg, fb_cfg,
            page_id, page_token, include_image, dry_run,
        )
        if success and not dry_run:
            remaining = db.count_by_status("approved")
            log.info(
                "%d article(s) remain in queue — will publish 1/hour", remaining
            )

    log.info("=" * 60)
    log.info("Run complete")
    log.info("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Journalist Agent")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Full pipeline without posting to Facebook",
    )
    parser.add_argument(
        "--no-image",
        action="store_true",
        help="Post text only, skip image upload",
    )
    parser.add_argument(
        "--reset-db",
        action="store_true",
        help="Clear all scraped articles from the DB before running (tokens kept)",
    )
    args = parser.parse_args()

    if args.reset_db:
        db.init_db()
        db.reset_db()
        log.info("Database reset — all articles cleared.")

    run(dry_run=args.dry_run, force_no_image=args.no_image)
