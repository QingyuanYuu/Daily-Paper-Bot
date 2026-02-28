from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

import arxiv

from app.models import PaperCandidate

logger = logging.getLogger(__name__)


class ArxivProvider:
    def __init__(self, window_days: int = 7, max_results_per_keyword: int = 50):
        self.window_days = window_days
        self.max_results = max_results_per_keyword

    def fetch(self, keywords: list[str]) -> list[PaperCandidate]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.window_days)
        candidates: list[PaperCandidate] = []

        for kw in keywords:
            logger.info("ArXiv: searching '%s' (last %d days)", kw, self.window_days)
            query = f'all:"{kw}"'
            search = arxiv.Search(
                query=query,
                max_results=self.max_results,
                sort_by=arxiv.SortCriterion.SubmittedDate,
                sort_order=arxiv.SortOrder.Descending,
            )
            client = arxiv.Client()
            for result in client.results(search):
                pub = result.published.replace(tzinfo=timezone.utc)
                if pub < cutoff:
                    continue
                aid = self._extract_arxiv_id(result.entry_id)
                candidates.append(
                    PaperCandidate(
                        title=result.title,
                        url=result.entry_id,
                        source="arxiv",
                        arxiv_id=aid,
                        authors=[a.name for a in result.authors],
                        abstract=result.summary,
                        published=pub,
                        matched_keywords=[kw],
                    )
                )
            logger.info("ArXiv: got %d results for '%s'", len(candidates), kw)

        return candidates

    @staticmethod
    def _extract_arxiv_id(entry_id: str) -> str | None:
        m = re.search(r"(\d{4}\.\d{4,5})(v\d+)?$", entry_id)
        return m.group(1) if m else None
