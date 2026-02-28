"""
CLI entrypoint: python -m app.daily_digest --date YYYY-MM-DD --top_k 5
"""
from __future__ import annotations

import argparse
import logging
from datetime import date

from app.config import load_config
from app.providers.arxiv_provider import ArxivProvider
from app.providers.hf_provider import HuggingFaceProvider
from app.services.merger import merge_and_dedupe
from app.services.ranker import rank_papers
from app.services.summarizer import Summarizer
from app.services.notion_writer import NotionWriter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Daily Paper Digest")
    parser.add_argument("--date", type=str, default=None, help="Digest date (YYYY-MM-DD)")
    parser.add_argument("--top_k", type=int, default=None, help="Number of top papers")
    parser.add_argument("--dry-run", action="store_true", help="Skip Notion write")
    args = parser.parse_args(argv)

    cfg = load_config()
    digest_date = date.fromisoformat(args.date) if args.date else date.today()
    top_k = args.top_k or cfg["ranking"]["top_k"]
    keywords = cfg["keywords"]

    # 1) Fetch from both providers
    logger.info("Fetching papers for keywords: %s", keywords)
    arxiv_cfg = cfg["providers"]["arxiv"]
    arxiv_provider = ArxivProvider(
        window_days=arxiv_cfg["window_days"],
        max_results_per_keyword=arxiv_cfg["max_results_per_keyword"],
    )
    hf_provider = HuggingFaceProvider()

    arxiv_papers = arxiv_provider.fetch(keywords)
    hf_papers = hf_provider.fetch(keywords)
    logger.info("ArXiv: %d, HuggingFace: %d", len(arxiv_papers), len(hf_papers))

    # 2) Merge & dedupe
    all_papers = merge_and_dedupe(arxiv_papers + hf_papers)

    if not all_papers:
        logger.warning("No papers found. Exiting.")
        return

    # 3) Rank & select top-k
    weights = cfg["ranking"].get("weights")
    top_papers = rank_papers(all_papers, keywords, top_k=top_k, weights=weights)
    logger.info("Top %d papers selected:", len(top_papers))
    for i, p in enumerate(top_papers, 1):
        logger.info("  %d. [%.3f] %s", i, p.score, p.title)

    # 4) Summarize with Claude API
    summarizer = Summarizer()

    # 4a) Digest: one call for all papers
    logger.info("Generating digest summary for %d papers...", len(top_papers))
    digest_markdown = summarizer.summarize_for_digest(top_papers, digest_date, keywords)

    # 4b) Note: one call per paper
    for p in top_papers:
        logger.info("Generating note for: %s", p.title[:60])
        p.note_markdown = summarizer.summarize_for_note(p)

    # 5) Write to Notion
    if args.dry_run:
        logger.info("Dry run — skipping Notion write.")
        _print_digest(digest_markdown, top_papers)
        return

    writer = NotionWriter()
    digest_id = writer.write_digest(top_papers, digest_date, digest_markdown)
    logger.info("Notion digest page: %s", digest_id)


def _print_digest(digest_markdown: str, papers: list) -> None:
    print("\n" + "=" * 60)
    print("DIGEST MARKDOWN:")
    print("=" * 60)
    print(digest_markdown[:2000] if digest_markdown else "(empty)")
    print("\n" + "=" * 60)
    for i, p in enumerate(papers, 1):
        print(f"\n{'='*60}")
        print(f"{i}. {p.title}")
        print(f"   arXiv: {p.arxiv_id} | HF likes: {p.hf_likes} | score: {p.score:.3f}")
        if p.note_markdown:
            print(f"   Note preview: {p.note_markdown[:200]}...")


if __name__ == "__main__":
    main()
