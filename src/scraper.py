"""
Web scraper – one public function per logical step.

scrape_source(source)   → list of new article dicts (not yet in DB)
fetch_article(url, sel) → {headline, body_text, image_url}
"""

import json
import re
import time
from typing import Dict, List, Optional
from urllib.parse import urljoin

import cloudscraper
from bs4 import BeautifulSoup

from src.logger import get_logger

log = get_logger(__name__)

# Single shared session — reuses Cloudflare clearance cookies across requests
_scraper = cloudscraper.create_scraper()


def _get(url: str, timeout: int) -> Optional[BeautifulSoup]:
    try:
        resp = _scraper.get(url, timeout=timeout)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")
    except Exception as exc:
        log.error("GET failed for %s: %s", url, exc)
        return None


def _absolute(href: str, base_url: str) -> str:
    return urljoin(base_url, href)


def _extract_rsc_body(soup: BeautifulSoup, css_selector: str) -> str:
    """
    Extract body text from Next.js RSC flight data embedded in inline scripts.

    Concatenates all self.__next_f.push([1, "..."]) chunks, finds the first
    T<hexlen>, text block, parses it as HTML, and applies css_selector.
    """
    flight = ""
    for sc in soup.select("script:not([src])"):
        txt = sc.string or ""
        if "self.__next_f.push" not in txt:
            continue
        m = re.search(r'self\.__next_f\.push\(\[1,"(.*)"\]\)', txt, re.DOTALL)
        if m:
            try:
                flight += json.loads('"' + m.group(1) + '"')
            except Exception:
                pass

    m = re.search(r"[0-9a-f]+:T([0-9a-f]+),", flight)
    if not m:
        return ""

    start = m.end()
    length = int(m.group(1), 16)
    body_html = flight[start : start + length]
    body_soup = BeautifulSoup(body_html, "lxml")
    els = body_soup.select(css_selector)
    return " ".join(el.get_text(strip=True) for el in els)


def scrape_listing(
    listing_url: str,
    link_selector: str,
    base_url: str,
    timeout: int,
    section_heading: Optional[str] = None,
) -> List[str]:
    """
    Return absolute article URLs from the listing/index page.

    If section_heading is set, only links inside the section whose
    heading text contains that string are returned. This is useful when
    the target section has unstable CSS Module class names.
    """
    soup = _get(listing_url, timeout)
    if not soup:
        return []

    if section_heading:
        # Find the heading tag whose text matches, then walk up to the
        # nearest ancestor that contains the links.
        heading_el = soup.find(
            lambda tag: tag.name in ("h2", "h3", "h4", "h5")
            and section_heading in (tag.get_text(strip=True) or "")
        )
        if not heading_el:
            log.warning(
                "Section heading '%s' not found on %s — falling back to full page",
                section_heading, listing_url,
            )
            search_root = soup
        else:
            # the section container is typically heading → parent (header div) → parent (card div)
            search_root = heading_el.parent.parent
            log.debug("Scoped to section '%s'", section_heading)
    else:
        search_root = soup

    anchors = search_root.select(link_selector)
    if not anchors:
        log.warning("No links matched selector '%s' on %s", link_selector, listing_url)

    urls = []
    for a in anchors:
        href = a.get("href", "").strip()
        if href:
            urls.append(_absolute(href, base_url))
    return urls


def fetch_article(
    url: str,
    selectors: Dict[str, Optional[str]],
    timeout: int,
) -> Optional[Dict]:
    """
    Fetch a single article page and extract content.

    Returns dict with keys: headline, body_text, image_url
    Returns None if the page cannot be fetched or headline is missing.
    """
    soup = _get(url, timeout)
    if not soup:
        return None

    headline_el = soup.select_one(selectors["headline"])
    if not headline_el:
        log.warning("Headline not found at %s (selector: %s)", url, selectors["headline"])
        return None
    headline = headline_el.get_text(strip=True)

    body_sel = selectors["body"]
    if body_sel.startswith("rsc:"):
        body_text = _extract_rsc_body(soup, body_sel[4:])
    else:
        body_text = " ".join(el.get_text(strip=True) for el in soup.select(body_sel))

    image_url: Optional[str] = None
    img_selector = selectors.get("image")
    if img_selector:
        img_el = soup.select_one(img_selector)
        if img_el:
            if img_el.name == "meta":
                image_url = img_el.get("content")
            else:
                image_url = img_el.get("data-src") or img_el.get("src")
            if image_url:
                image_url = _absolute(image_url, url)

    return {"headline": headline, "body_text": body_text, "image_url": image_url}


def scrape_source(source: Dict, db_is_seen_fn, settings: Dict) -> List[Dict]:
    """
    Full scrape for one source config entry.

    Returns list of new article dicts ready to be saved to DB.
    Each dict: {source_name, url, headline, body_text, image_url}
    """
    name = source["name"]
    listing_url = source["listing_url"]
    selectors = source["selectors"]
    delay = source.get("request_delay", 2)
    timeout = settings["scraping"]["request_timeout"]
    max_articles = settings["scraping"]["max_articles_per_source"]

    base_url = listing_url  # used for resolving relative hrefs
    log.info("[%s] Scraping listing: %s", name, listing_url)

    section_heading = source.get("section_heading")
    urls = scrape_listing(listing_url, selectors["article_links"], base_url, timeout, section_heading)
    log.info("[%s] Found %d links on listing page", name, len(urls))

    new_articles = []
    for url in urls[:max_articles]:
        if db_is_seen_fn(url):
            log.debug("[%s] Skipping already-seen: %s", name, url)
            continue

        time.sleep(delay)
        article = fetch_article(url, selectors, timeout)
        if not article:
            continue

        article["url"] = url
        article["source_name"] = name
        new_articles.append(article)
        log.info("[%s] Fetched: %s", name, article["headline"][:80])

    log.info("[%s] %d new articles collected", name, len(new_articles))
    return new_articles
