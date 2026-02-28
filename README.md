# Daily Paper Bot

Automated daily paper digest that searches **arXiv** and **Hugging Face**, ranks papers by community engagement + recency, generates structured summaries, and writes everything to Notion.

## How It Works

1. **Fetch** — Queries arXiv API and HF daily papers for configured keywords
2. **Merge & Dedupe** — Combines results, deduplicates by arXiv ID (fallback: title hash), enriches arXiv papers with HF likes
3. **Rank** — `score = 0.6·log(1+hf_likes) + 0.3·recency_bonus + 0.1·keyword_match_strength`
4. **Summarize** — Claude-based structured analysis using digest & note prompts
5. **Write to Notion** — Upserts a Daily Digest page with all papers + creates individual Paper Notes pages

## Setup

```bash
# Clone & install
git clone https://github.com/QingyuanYuu/Daily-Paper-Bot.git
cd Daily-Paper-Bot
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your API keys
```

### Required Environment Variables

| Variable | Description |
|---|---|
| `NOTION_API_KEY` | Notion integration token |
| `DIGEST_PARENT_PAGE_ID` | Parent page ID for Daily Digest pages |
| `NOTES_DB_ID` | Database ID for Paper Notes |
| `ANTHROPIC_API_KEY` | Anthropic API key (for Claude summarizer) |

### Notion Setup

**Digest Parent Page** — A Notion page whose children will be daily digest sub-pages (one per day).

**Paper Notes DB** — Properties:
- `Name` (title)
- `URL` (url)
- `Key` (rich_text — dedup key)
- `ArXiv ID` (rich_text)

## Usage

```bash
# Run for today
python -m app.daily_digest

# Run for a specific date with custom top_k
python -m app.daily_digest --date 2026-02-27 --top_k 5

# Dry run (prints to console, skips Notion)
python -m app.daily_digest --dry-run
```

## Configuration

Edit `config.yaml` to change keywords, time windows, ranking weights, etc.

```yaml
keywords:
  - humanoid
  - world model
  - diffusion
  - dexterous manipulation

providers:
  arxiv:
    window_days: 7
    max_results_per_keyword: 50

ranking:
  top_k: 5
  weights:
    hf_likes: 0.6
    recency: 0.3
    keyword_match: 0.1
```

## GitHub Actions

The workflow runs daily at 09:00 AM Pacific. Set secrets in your repo settings:
- `NOTION_API_KEY`
- `DIGEST_PARENT_PAGE_ID`
- `NOTES_DB_ID`
- `ANTHROPIC_API_KEY`

You can also trigger manually via `workflow_dispatch` with optional `date` and `top_k` inputs.

## Tests

```bash
python -m pytest tests/ -v
```

## Project Structure

```
app/
  __main__.py          # python -m app entrypoint
  daily_digest.py      # CLI + orchestration
  config.py            # YAML + env config loader
  models.py            # PaperCandidate, PaperSummary dataclasses
  providers/
    arxiv_provider.py  # ArXiv API search
    hf_provider.py     # HuggingFace API + HTML scraper
  services/
    merger.py          # Merge & deduplicate
    ranker.py          # Scoring & ranking
    summarizer.py      # LLM-based paper analysis
    notion_writer.py   # Notion API integration
skills/
  digest_prompt.md     # Digest short-summary prompt
  note_prompt.md       # Detailed paper note prompt
tests/
  test_merger.py       # Merge/dedupe tests
  test_ranker.py       # Scoring/ranking tests
```
