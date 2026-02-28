# Daily Paper Bot

Automated daily paper digest that fetches papers from **arXiv** and **Hugging Face**, ranks them by community engagement + recency + keyword relevance, generates structured summaries with **Claude**, and writes everything to **Notion** as a long-term knowledge base.

> The default configuration targets **robotics / embodied AI** research (humanoid, world model, diffusion, dexterous manipulation), but you can adapt it to any research area by changing the keywords.

## Pipeline Overview

```
┌──────────────┐     ┌──────────────┐
│   arXiv API  │     │  HF Daily    │
│  (keyword    │     │  Papers API  │
│   search,    │     │  + HTML      │
│   last 7d)   │     │  scraper)    │
└──────┬───────┘     └──────┬───────┘
       │                    │
       └────────┬───────────┘
                ▼
       ┌────────────────┐
       │  Merge & Dedupe │  Dedup by arXiv ID (fallback: title hash)
       │                │  Merge HF likes, fill missing metadata
       └────────┬───────┘
                ▼
       ┌────────────────┐
       │     Rank       │  score = 0.6·log(1+likes)
       │                │       + 0.3·recency_bonus
       │                │       + 0.1·keyword_match
       └────────┬───────┘
                ▼
       ┌────────────────┐
       │   Summarize    │  Claude generates two summaries:
       │   (Claude API) │  · Digest (quick overview + key insights)
       │                │  · Note (method breakdown + repro plan)
       └────────┬───────┘
                ▼
       ┌────────────────┐
       │  Notion Writer │  · Upsert Daily Digest page
       │                │  · Upsert Paper Note pages
       │                │  · Cross-link Digest ↔ Notes
       └────────────────┘
```

## How Each Stage Works

### 1. Fetch

**arXiv**: For each keyword, constructs an `all:"keyword"` query against the arXiv API, searching the last N days (default: 7) sorted by submission date. Up to 50 results per keyword. A paper matching multiple keywords (e.g., both "humanoid" and "world model") will be fetched multiple times and merged in the next stage with all matched keyword tags preserved.

**Hugging Face**: Calls the HF Daily Papers JSON API to retrieve all trending papers (including like counts), then filters by substring-matching keywords against title + abstract (case-insensitive). Automatically falls back to HTML scraping if the API is unavailable.

### 2. Merge & Dedupe

Combines papers from both sources into a single list:
- **Dedup key**: arXiv ID (e.g., `2401.12345`) takes priority; falls back to a normalized title hash when no arXiv ID is available
- **Merge strategy**: Takes the max HF likes; unions matched keywords; fills in missing abstract, authors, and published date from the other source

### 3. Rank

Each paper receives a composite score:

```
score = 0.6 × log(1 + hf_likes)      # Community engagement (log-scaled to prevent outlier dominance)
      + 0.3 × recency_bonus           # Recency (1.0 for today, linear decay to 0.0 at 7 days)
      + 0.1 × keyword_match_strength  # Keyword coverage (matched keywords / total keywords)
```

Papers are sorted by score in descending order, and the top `top_k` are selected (default: 5, overridable via `TOP_K` in `.env`).

**Multi-keyword matching**: A single paper can match multiple keywords. For example, a paper about humanoid + diffusion gets `keyword_match_strength = 2/4 = 0.5`, scoring higher than one matching only a single keyword (0.25). In practice, HF likes dominate the ranking; keyword match serves as a tiebreaker.

### 4. Summarize

For each selected paper, Claude generates two structured summaries:

| Type | Prompt File | Used In | Content |
|------|-------------|---------|---------|
| **Digest** | `skills/digest_prompt.md` | Daily Digest page | Daily commentary, key takeaways, per-paper problem/method/innovation/limitations/repro suggestions |
| **Note** | `skills/note_prompt.md` | Paper Note page | One-line conclusion, detailed method breakdown (pipeline / architecture / training / inference / key design choices), innovations, limitations, reproduction plan (~1000 words) |

Both prompt files are fully customizable.

### 5. Write to Notion

- **Daily Digest page**: Created as a child page under a designated parent page (title format: `Daily Digest – 2026-02-28`), containing an overview of all selected papers with summaries and links to detailed notes
- **Paper Note pages**: Created in a designated database, one per paper, with the full structured analysis
- **Idempotent writes**: Uses a Key field (arXiv ID or title hash) for deduplication — re-running won't create duplicates, it updates existing pages

---

## Getting Started

### Prerequisites

- Python 3.11+
- A [Notion](https://www.notion.so) account
- An [Anthropic](https://console.anthropic.com) API key

### Step 1: Clone & Install

```bash
git clone https://github.com/QingyuanYuu/Daily-Paper-Bot.git
cd Daily-Paper-Bot
pip install -r requirements.txt
```

### Step 2: Set Up Notion

1. **Create a Notion Integration**
   - Go to [My Integrations](https://www.notion.so/my-integrations) and click "New integration"
   - Give it a name (e.g., "Paper Bot"), select your workspace, and click "Submit"
   - Copy the **Internal Integration Token** (starts with `ntn_` or `secret_`)

2. **Create the Digest Parent Page**
   - Create a new page in Notion to serve as the parent for all daily digests (e.g., "Daily Digests")
   - Click `···` in the top right → "Connections" → add the integration you just created
   - Get the page ID: click "Share" → "Copy link" — the 32-character hex string at the end of the URL is the ID
     ```
     https://www.notion.so/Your-Page-Title-{32-char-ID-here}
     ```

3. **Create the Paper Notes Database**
   - Create a new **Full Page Database**
   - Add the following properties:

     | Property | Type | Description |
     |----------|------|-------------|
     | `Name` | Title | Paper title (built-in) |
     | `URL` | URL | Link to paper |
     | `Key` | Rich text | Dedup key (auto-filled by the bot) |
     | `ArXiv ID` | Rich text | arXiv identifier |

   - Connect the integration to this database as well
   - Get the database ID: open the database, "Share" → "Copy link" — the 32-char hex string before `?v=` is the ID
     ```
     https://www.notion.so/{32-char-DB-ID-here}?v=...
     ```

### Step 3: Configure Environment Variables

```bash
cp .env.example .env
```

Edit `.env` with your actual values:

```env
# Required
NOTION_API_KEY=ntn_your_integration_token
DIGEST_PARENT_PAGE_ID=your_digest_parent_page_id
NOTES_DB_ID=your_paper_notes_database_id
ANTHROPIC_API_KEY=sk-ant-your_anthropic_key

# Optional — override config.yaml defaults
# TOP_K=3                  # Number of top papers per day (default: 5)
# WINDOW_DAYS=7             # arXiv search window in days (default: 7)
# KEYWORDS=humanoid,world model,diffusion   # Custom keywords (comma-separated)
# TZ=America/Los_Angeles    # Timezone
```

### Step 4: Run

```bash
# Full run (fetch → rank → summarize → write to Notion)
python -m app.daily_digest

# Dry run (prints results to console, skips Notion)
python -m app.daily_digest --dry-run

# Specify date and number of papers
python -m app.daily_digest --date 2026-02-27 --top_k 5
```

---

## Customizing Keywords

Keywords determine which papers you receive. Two ways to change them:

**Option A**: Edit `.env` (recommended — env vars take highest priority)
```env
KEYWORDS=reinforcement learning,transformer,LLM agent
```

**Option B**: Edit `config.yaml`
```yaml
keywords:
  - reinforcement learning
  - transformer
  - LLM agent
```

**How keywords work**:
- arXiv uses exact phrase search (`all:"keyword"`), so `world model` matches that exact phrase
- HF uses case-insensitive substring matching against title + abstract
- A paper can match multiple keywords — more matches = higher score

---

## Tuning Ranking Weights

Edit the `ranking.weights` section in `config.yaml`:

```yaml
ranking:
  top_k: 5
  weights:
    hf_likes: 0.6       # Community engagement weight
    recency: 0.3         # Recency weight
    keyword_match: 0.1   # Keyword coverage weight
```

For example, to prioritize the latest papers over popular ones:
```yaml
  weights:
    hf_likes: 0.3
    recency: 0.6
    keyword_match: 0.1
```

---

## Customizing Summary Prompts

Two prompt files control Claude's output format and content:

- `skills/digest_prompt.md` — Digest page style (daily commentary, quick takeaways, per-paper overview)
- `skills/note_prompt.md` — Note page depth (method breakdown, reproduction plan, ~1000 words)

Edit these Markdown files directly. The default prompts produce mixed Chinese-English output tailored for robotics/embodied AI. To adapt for a different research area, update the "target reader" description and domain-specific sections in the prompts.

---

## GitHub Actions

The project includes a GitHub Actions workflow that runs automatically every day.

### Setup

1. Push the project to GitHub
2. Go to **Settings → Secrets and variables → Actions → New repository secret**
3. Add these 4 secrets:

   | Secret Name | Value |
   |-------------|-------|
   | `NOTION_API_KEY` | Your Notion integration token |
   | `DIGEST_PARENT_PAGE_ID` | Digest parent page ID |
   | `NOTES_DB_ID` | Paper Notes database ID |
   | `ANTHROPIC_API_KEY` | Anthropic API key |

### Automatic Schedule

The workflow runs daily at **09:00 AM Pacific** (UTC 17:00).

### Manual Trigger

Go to the **Actions** tab → select **Daily Paper Digest** → click **Run workflow**, with optional inputs:

- `date` — Digest date in `YYYY-MM-DD` format (defaults to today)
- `top_k` — Number of top papers (defaults to 5)

---

## Tests

```bash
python -m pytest tests/ -v
```

Current coverage:
- `test_merger.py` — Dedup logic (by arXiv ID / title hash), field merging (likes / keywords / abstract / published), edge cases
- `test_ranker.py` — Scoring formula correctness, top-k selection, custom weights, edge cases

---

## Project Structure

```
app/
  __main__.py              # python -m app entrypoint
  daily_digest.py          # CLI parsing + 5-stage pipeline orchestration
  config.py                # Loads config.yaml + .env with env var overrides
  models.py                # PaperCandidate & PaperSummary dataclasses
  providers/
    arxiv_provider.py      # arXiv API keyword + time window search
    hf_provider.py         # HF Daily Papers JSON API + HTML scraper fallback
  services/
    merger.py              # Multi-source merge & deduplication
    ranker.py              # Scoring formula & top-k selection
    summarizer.py          # Claude API calls + structured response parsing
    notion_writer.py       # Notion API: upsert pages + block construction
skills/
  digest_prompt.md         # System prompt for digest summaries
  note_prompt.md           # System prompt for detailed paper analysis
tests/
  test_merger.py           # Merge & dedup unit tests
  test_ranker.py           # Scoring & ranking unit tests
config.yaml                # Keywords, provider settings, ranking weights
.env.example               # Environment variable template
.github/workflows/
  daily_digest.yml         # Scheduled GitHub Actions workflow
```

## Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Language | Python 3.11+ | — |
| LLM | Anthropic Claude (`claude-sonnet-4-20250514`) | Paper summarization |
| Knowledge Base | Notion API (`notion-client`) | Structured output & long-term storage |
| Academic Search | arXiv API (`arxiv` package) | Full-field keyword search |
| Community Signal | Hugging Face (`requests` + `beautifulsoup4`) | Trending papers + like counts |
| Automation | GitHub Actions | Daily scheduled runs |
| Configuration | YAML + dotenv | Flexible multi-layer config |

## License

MIT
