from __future__ import annotations

import logging

from app.models import PaperCandidate

logger = logging.getLogger(__name__)


def merge_and_dedupe(all_candidates: list[PaperCandidate]) -> list[PaperCandidate]:
    """Merge candidates from all providers, deduplicate, and enrich."""
    seen: dict[str, PaperCandidate] = {}

    for paper in all_candidates:
        key = paper.dedup_key
        if key in seen:
            existing = seen[key]
            # Merge hf_likes (take the max)
            existing.hf_likes = max(existing.hf_likes, paper.hf_likes)
            # Merge matched keywords
            for kw in paper.matched_keywords:
                if kw not in existing.matched_keywords:
                    existing.matched_keywords.append(kw)
            # Fill in missing fields from the new entry
            if not existing.abstract and paper.abstract:
                existing.abstract = paper.abstract
            if not existing.authors and paper.authors:
                existing.authors = paper.authors
            if not existing.published and paper.published:
                existing.published = paper.published
            if not existing.arxiv_id and paper.arxiv_id:
                existing.arxiv_id = paper.arxiv_id
        else:
            seen[key] = paper

    merged = list(seen.values())
    logger.info(
        "Merged %d candidates into %d unique papers",
        len(all_candidates),
        len(merged),
    )
    return merged
