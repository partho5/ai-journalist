# AI Journalist Agent

Scrapes multiple news sources, deduplicates similar stories, filters by editorial criteria, writes engaging Facebook posts, and publishes them via the Graph API — all on a cron schedule.

---

## Architecture

```
main.py
│
├─ scraper.py         fetch listing pages → extract new articles (CSS selectors)
├─ deduplicator.py    group cross-source duplicates via AI → keep one per topic
├─ filter.py          apply criteria prompt → rank by engagement → select top N
├─ writer.py          rephrase each article into a Facebook post via AI
├─ publisher.py       post to Facebook (text + optional image)
└─ token_manager.py   refresh long-lived FB user token and page token
```

State is stored in `data/state.db` (SQLite). Every URL ever scraped is recorded — re-runs skip already-seen articles automatically.

---

## Setup

```bash
bash setup.sh
```

This creates the venv, installs dependencies, and scaffolds `.env`.

### Manual steps

1. **Fill in `.env`** (copy from `.env.example`):

   | Variable | What it is |
   |---|---|
   | `OPENAI_API_KEY` | Your OpenAI API key |
   | `FB_APP_ID` | Facebook App ID (from developers.facebook.com) |
   | `FB_APP_SECRET` | Facebook App Secret |
   | `FB_PAGE_ID` | Numeric ID of your Facebook page |
   | `FB_USER_TOKEN` | Long-lived user access token (see below) |

2. **Get a Facebook long-lived user token** (one-time):
   - Go to [Graph API Explorer](https://developers.facebook.com/tools/explorer/)
   - Select your app → add permissions: `pages_manage_posts`, `pages_read_engagement`
   - Click **Generate Access Token** → copy it to `FB_USER_TOKEN` in `.env`
   - Then run once to exchange and persist it:
     ```bash
     ./venv/bin/python refresh_token.py
     ```

3. **Configure news sources** in `config/sources.yaml` — paste URLs and CSS selectors.

4. **Tune prompts** in `config/prompts.yaml` — criteria, ranking style, writing language/tone.

5. **Adjust limits** in `config/settings.yaml` — max posts per run, image toggle, delays.

---

## Running

```bash
# Test the full pipeline without posting to Facebook:
./venv/bin/python main.py --dry-run

# Run for real:
./venv/bin/python main.py

# Skip images (text posts only):
./venv/bin/python main.py --no-image
```

### Trigger an immediate post (don't wait for cron)

The cron runs every hour via `deploy.sh`. To post right now without waiting:

```bash
cd /path/to/ai-journalist-agent
./venv/bin/python main.py
```

Or using the same script the cron calls:

```bash
bash run.sh
```

Both do the same thing: if there are approved articles in the queue they publish one immediately; otherwise they scrape, filter, and publish one on the spot.

---

## Cron setup

Add these lines via `crontab -e` (adjust path to your project):

```cron
# Run pipeline every 6 hours
0 */6 * * *  cd /home/user/ai-journalist-agent && ./venv/bin/python main.py >> logs/cron.log 2>&1

# Refresh FB token on the 1st of every month
0 0 1 * *    cd /home/user/ai-journalist-agent && ./venv/bin/python refresh_token.py >> logs/token_refresh.log 2>&1
```

---

## Adding a news source

In `config/sources.yaml`, add a block:

```yaml
- name: "My News Site"
  listing_url: "https://mynewssite.com/latest"
  selectors:
    article_links: "a.article-title-link"   # <a> tags on the listing page
    headline:      "h1.headline"             # headline on the article page
    body:          "div.article-body p"      # body paragraphs on the article page
    image:         "figure.featured img"     # featured image (null to disable)
  request_delay: 2
```

Use your browser DevTools → Inspector to find CSS selectors for each site.

---

## Article status lifecycle

```
pending → duplicate       (same story found in another source)
        → filtered_out    (did not pass criteria or ranking)
        → selected        (chosen for publishing)
            → published   (posted to Facebook)
            → error       (something failed — check logs/)
```

---

## Logs

- `logs/journalist.log` — full pipeline log
- `logs/cron.log` — cron output
- `logs/token_refresh.log` — FB token refresh

Set log level in `config/settings.yaml` (`DEBUG` for verbose output).
