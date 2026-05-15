# AI Journalist Agent

Scrapes news sources, filters and ranks articles with an LLM, writes Facebook-ready editorials, and drip-posts them to a Facebook Page — one article per hour, automatically.

---

## Features

### Automated news pipeline
- Scrapes multiple news sources using configurable CSS selectors
- Bypasses Cloudflare-protected sites via `cloudscraper`
- Handles Next.js RSC (React Server Components) pages whose body text is embedded in flight data scripts — no Playwright needed

### AI-powered editorial judgment (OpenAI)
- **Deduplication** — groups headlines covering the same real-world event across sources; keeps the most detailed version, discards the rest
- **Criteria filtering** — evaluates each article against your editorial criteria prompt; rejects off-topic or low-quality pieces
- **Engagement ranking** — scores passing articles by audience engagement potential; fills the queue in ranked order
- **Editorial writing** — rewrites each article as a Facebook post in your configured tone and style

### Queue-based drip publishing
- Each cron run does exactly one thing:
  - **Publish mode** — queue has approved articles → write editorial for the top one, post to Facebook, done
  - **Intake mode** — queue is empty → scrape, dedup, filter, rank, approve all passing articles, publish the best one immediately
- Approved articles older than 36 hours are automatically expired so stale news never goes out
- Cron runs every hour from **08:00 to 00:00 (midnight)**

### Facebook Graph API integration
- Posts to a Facebook Page with or without a featured image
- Refreshes long-lived page tokens via `refresh_token.py`

### Developer tools
- `--dry-run` — runs the full pipeline and prints the LLM editorial output without posting anything
- `--no-image` — overrides `include_image` for a single run
- `--reset-db` — clears all scraped articles from the database (keeps tokens)
- Structured logs written to `logs/cron.log`

---

## Installation

### 1. Clone and configure

```bash
git clone <repo-url>
cd ai-journalist-agent
cp .env.example .env
```

Fill in `.env`:

```
OPENAI_API_KEY=sk-...
FB_APP_ID=...
FB_APP_SECRET=...
FB_PAGE_ID=...
FB_USER_TOKEN=...       # short-lived user token from Meta developer console
```

### 2. Add your news sources

Edit `config/sources.yaml`. Each source needs a listing page URL and CSS selectors for article links, headline, body, and (optionally) image:

```yaml
sources:
  - name: "My Source"
    listing_url: "https://example.com/news"
    selectors:
      article_links: "a.article-link"
      headline: "h1.title"
      body: "div.article-body p"
      image: "meta[property='og:image']"   # null to skip
    request_delay: 2
```

For sections buried inside a longer page, add `section_heading: "Section Title"` to scope link scraping to that section only.

For Next.js RSC pages, prefix the body selector with `rsc:`:

```yaml
body: "rsc:p.body-text"
```

### 3. Get a Facebook Page token

```bash
./venv/bin/python refresh_token.py
```

Paste your short-lived user token when prompted. The script exchanges it for a long-lived page token and saves it to `data/fb_token.json`.

### 4. Test without posting

```bash
./venv/bin/python main.py --dry-run
```

Runs the full scrape → dedup → filter → rank → write pipeline and prints the editorial to the terminal. Nothing is posted to Facebook.

### 5. Deploy

```bash
./deploy.sh
```

This single command:
- Creates the Python virtual environment (if missing)
- Installs / upgrades all dependencies from `requirements.txt`
- Creates `data/` and `logs/` directories
- Registers the hourly cron job (08:00–00:00) — idempotent, safe to re-run after `git pull`

---

## Tuning the pipeline

All behaviour is controlled by three YAML files:

| File | What it controls |
|---|---|
| `config/settings.yaml` | OpenAI model, scraping limits, article age limit, image toggle |
| `config/sources.yaml` | News sources and their CSS selectors |
| `config/prompts.yaml` | Editorial criteria, ranking instructions, writing style |

---

## Manual commands

```bash
# Full pipeline, no Facebook post
python main.py --dry-run

# Post text only, no image
python main.py --no-image

# Clear article database and run fresh
python main.py --reset-db

# Refresh the Facebook page token
python refresh_token.py
```
# ai-journalist
