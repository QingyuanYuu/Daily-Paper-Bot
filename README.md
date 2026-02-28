# Daily Paper Bot

Automated daily paper digest that searches **arXiv** and **Hugging Face**, ranks papers by community engagement + recency, generates structured summaries with **Claude**, and writes everything to **Notion**.

## How It Works

```
┌──────────┐   ┌──────────┐
│  arXiv   │   │ HF Daily │
│   API    │   │  Papers  │
└────┬─────┘   └────┬─────┘
     │              │
     └──────┬───────┘
            ▼
     ┌─────────────┐
     │ Merge/Dedupe│  arxiv_id → title hash fallback
     └──────┬──────┘
            ▼
     ┌─────────────┐
     │    Rank     │  score = 0.6·log(1+likes) + 0.3·recency + 0.1·keyword
     └──────┬──────┘
            ▼
     ┌─────────────┐
     │  Summarize  │  Claude (digest prompt + note prompt)
     └──────┬──────┘
            ▼
     ┌─────────────┐
     │   Notion    │  Daily Digest page + Paper Note pages
     └─────────────┘
```

1. **Fetch** — Queries arXiv API and HF daily papers API (with HTML scraping fallback) for configured keywords
2. **Merge & Dedupe** — Combines results from both sources, deduplicates by arXiv ID (fallback: normalized title hash), merges HF likes and missing metadata
3. **Rank** — Scores each paper: `score = 0.6·log(1+hf_likes) + 0.3·recency_bonus + 0.1·keyword_match_strength`, selects top-k
4. **Summarize** — Claude generates two outputs per paper: a short digest interpretation and a detailed structured note (TL;DR, method breakdown, robotics takeaways, reproduction plan, etc.)
5. **Write to Notion** — Upserts a Daily Digest page (as a child of a parent page) with all papers, and creates/updates individual Paper Note pages in a database

## Quick Start

```bash
# Clone & install
git clone https://github.com/QingyuanYuu/Daily-Paper-Bot.git
cd Daily-Paper-Bot
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your actual API keys and Notion IDs
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `NOTION_API_KEY` | Yes | Notion integration token ([create one here](https://www.notion.so/my-integrations)) |
| `DIGEST_PARENT_PAGE_ID` | Yes | Notion page ID — daily digests are created as sub-pages under this page |
| `NOTES_DB_ID` | Yes | Notion database ID — individual paper notes are stored here |
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key for Claude summarization |
| `WINDOW_DAYS` | No | Override arXiv search window (default: 7) |
| `TOP_K` | No | Override number of top papers (default: 5) |
| `KEYWORDS` | No | Override keywords, comma-separated (default: from `config.yaml`) |
| `TZ` | No | Timezone for scheduling (default: system timezone) |

### Notion Setup

1. Create a [Notion integration](https://www.notion.so/my-integrations) and copy the token as `NOTION_API_KEY`
2. Create a **Digest Parent Page** — daily digests will be created as its child pages. Share this page with your integration, then copy the page ID as `DIGEST_PARENT_PAGE_ID`
3. Create a **Paper Notes Database** with these properties, share it with your integration, and copy the database ID as `NOTES_DB_ID`:

| Property | Type | Purpose |
|---|---|---|
| `Name` | Title | Paper title |
| `URL` | URL | Link to paper |
| `Key` | Rich text | Dedup key (arXiv ID or title hash) |
| `ArXiv ID` | Rich text | arXiv identifier |

> **Tip**: To find a page/database ID, open it in Notion, click "Share" → "Copy link". The ID is the 32-character hex string in the URL (before the `?v=` parameter for databases).

## Usage

```bash
# Run for today
python -m app.daily_digest

# Run for a specific date with custom top_k
python -m app.daily_digest --date 2026-02-27 --top_k 5

# Dry run — prints results to console, skips Notion write
python -m app.daily_digest --dry-run
```

## Configuration

Edit `config.yaml` to customize keywords, search parameters, and ranking weights:

```yaml
keywords:
  - humanoid
  - world model
  - diffusion
  - dexterous manipulation

providers:
  arxiv:
    window_days: 7              # How far back to search
    max_results_per_keyword: 50 # Max results per keyword query

ranking:
  top_k: 5                     # Number of papers in the digest
  weights:
    hf_likes: 0.6              # Community engagement weight
    recency: 0.3               # Newer papers score higher
    keyword_match: 0.1          # More keyword matches score higher
```

All `config.yaml` values can be overridden via environment variables (`WINDOW_DAYS`, `TOP_K`, `KEYWORDS`).

## GitHub Actions

The included workflow (`.github/workflows/daily_digest.yml`) runs automatically every day at **09:00 AM Pacific**.

### Setup

Add these secrets in **Settings → Secrets and variables → Actions → New repository secret**:

- `NOTION_API_KEY`
- `DIGEST_PARENT_PAGE_ID`
- `NOTES_DB_ID`
- `ANTHROPIC_API_KEY`

### Manual Trigger

You can also run it manually from the **Actions** tab → **Daily Paper Digest** → **Run workflow**, with optional inputs:

- `date` — digest date in `YYYY-MM-DD` format (defaults to today)
- `top_k` — number of top papers (defaults to 5)

## Tests

```bash
python -m pytest tests/ -v
```

Currently covers merger (dedup logic, field merging) and ranker (scoring formula, top-k selection, custom weights).

## Project Structure

```
app/
  __main__.py            # python -m app entrypoint
  daily_digest.py        # CLI argument parsing + pipeline orchestration
  config.py              # Loads config.yaml + .env, supports env overrides
  models.py              # PaperCandidate & PaperSummary dataclasses
  providers/
    arxiv_provider.py    # arXiv API search by keyword + time window
    hf_provider.py       # HF daily papers JSON API + HTML scraper fallback
  services/
    merger.py            # Merge multi-source results & deduplicate
    ranker.py            # Score papers & select top-k
    summarizer.py        # Claude-based structured summarization
    notion_writer.py     # Notion API: upsert digest pages & paper notes
skills/
  digest_prompt.md       # System prompt for short digest interpretation
  note_prompt.md         # System prompt for detailed paper analysis
tests/
  test_merger.py         # Merge & dedup unit tests
  test_ranker.py         # Scoring & ranking unit tests
config.yaml              # Keywords, provider settings, ranking weights
.env.example             # Template for required environment variables
.github/workflows/
  daily_digest.yml       # Scheduled GitHub Actions workflow
```

## Tech Stack

- **Python 3.11+**
- **Anthropic Claude** (`claude-sonnet-4-20250514`) — paper summarization
- **Notion API** (`notion-client`) — knowledge base output
- **arXiv API** (`arxiv` package) — academic paper search
- **Hugging Face** (`requests` + `beautifulsoup4`) — community trending papers
- **GitHub Actions** — daily scheduled automation

## License

MIT
