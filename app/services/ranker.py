from __future__ import annotations

import logging
import math
from datetime import datetime, timezone

from app.models import PaperCandidate

logger = logging.getLogger(__name__)


def score_paper(
    paper: PaperCandidate,
    all_keywords: list[str],
    w_likes: float = 0.6,
    w_recency: float = 0.3,
    w_keyword: float = 0.1,
) -> float:
    """
    score = w_likes * log(1 + hf_likes)
          + w_recency * recency_bonus
          + w_keyword * keyword_match_strength
    """
    likes_component = math.log(1 + paper.hf_likes)
    recency_component = _recency_bonus(paper.published)
    keyword_component = _keyword_match_strength(paper, all_keywords)

    return (
        w_likes * likes_component
        + w_recency * recency_component
        + w_keyword * keyword_component
    )


def rank_papers(
    papers: list[PaperCandidate],
    keywords: list[str],
    top_k: int = 5,
    weights: dict | None = None,
) -> list[PaperCandidate]:
    w = weights or {}
    for p in papers:
        p.score = score_paper(
            p,
            keywords,
            w_likes=w.get("hf_likes", 0.6),
            w_recency=w.get("recency", 0.3),
            w_keyword=w.get("keyword_match", 0.1),
        )
    ranked = sorted(papers, key=lambda p: p.score, reverse=True)
    logger.info(
        "Ranked %d papers; top score=%.3f, bottom score=%.3f",
        len(ranked),
        ranked[0].score if ranked else 0,
        ranked[-1].score if ranked else 0,
    )
    return ranked[:top_k]


def _recency_bonus(published: datetime | None) -> float:
    """1.0 for today, decaying to 0.0 over 7 days."""
    if not published:
        return 0.0
    now = datetime.now(timezone.utc)
    age_days = (now - published).total_seconds() / 86400
    if age_days < 0:
        age_days = 0
    return max(0.0, 1.0 - age_days / 7.0)


def _keyword_match_strength(paper: PaperCandidate, all_keywords: list[str]) -> float:
    """Fraction of keywords matched (0.0 – 1.0)."""
    if not all_keywords:
        return 0.0
    return len(paper.matched_keywords) / len(all_keywords)
