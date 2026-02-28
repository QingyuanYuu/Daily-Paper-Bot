from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from app.models import PaperCandidate

logger = logging.getLogger(__name__)

HF_PAPERS_URL = "https://huggingface.co/papers"
HF_API_URL = "https://huggingface.co/api/daily_papers"


class HuggingFaceProvider:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "DailyPaperBot/1.0"})

    def fetch(self, keywords: list[str]) -> list[PaperCandidate]:
        candidates: list[PaperCandidate] = []

        # Try the JSON API first (more reliable)
        candidates.extend(self._fetch_api(keywords))

        # Fallback / supplement with HTML scraping
        if not candidates:
            candidates.extend(self._fetch_html(keywords))

        return candidates

    def _fetch_api(self, keywords: list[str]) -> list[PaperCandidate]:
        results: list[PaperCandidate] = []
        try:
            resp = self.session.get(HF_API_URL, timeout=30)
            resp.raise_for_status()
            papers = resp.json()
        except Exception:
            logger.warning("HF API fetch failed, will try HTML scrape", exc_info=True)
            return results

        for item in papers:
            paper = item.get("paper", {})
            title = paper.get("title", "")
            abstract = paper.get("summary", "")
            text = f"{title} {abstract}".lower()
            matched = [kw for kw in keywords if kw.lower() in text]
            if not matched:
                continue

            arxiv_id = paper.get("id")  # HF API often uses arxiv id as paper id
            pub_str = paper.get("publishedAt") or item.get("publishedAt")
            published = None
            if pub_str:
                try:
                    published = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                except ValueError:
                    pass

            url = f"https://huggingface.co/papers/{arxiv_id}" if arxiv_id else ""
            results.append(
                PaperCandidate(
                    title=title,
                    url=url,
                    source="huggingface",
                    arxiv_id=arxiv_id,
                    authors=[a.get("name", "") for a in paper.get("authors", []) if isinstance(a, dict)],
                    abstract=abstract,
                    published=published,
                    hf_likes=item.get("numLikes", 0),
                    matched_keywords=matched,
                )
            )

        logger.info("HF API: found %d matching papers", len(results))
        return results

    def _fetch_html(self, keywords: list[str]) -> list[PaperCandidate]:
        results: list[PaperCandidate] = []
        try:
            resp = self.session.get(HF_PAPERS_URL, timeout=30)
            resp.raise_for_status()
        except Exception:
            logger.warning("HF HTML fetch failed", exc_info=True)
            return results

        soup = BeautifulSoup(resp.text, "html.parser")
        for article in soup.select("article"):
            title_el = article.select_one("h3 a")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            href = title_el.get("href", "")
            url = f"https://huggingface.co{href}" if href.startswith("/") else href

            # Extract likes
            likes = 0
            like_el = article.select_one("[class*='like']")
            if like_el:
                m = re.search(r"(\d+)", like_el.get_text())
                if m:
                    likes = int(m.group(1))

            # Extract arxiv_id from URL
            arxiv_id = None
            m = re.search(r"(\d{4}\.\d{4,5})", href)
            if m:
                arxiv_id = m.group(1)

            text = title.lower()
            matched = [kw for kw in keywords if kw.lower() in text]
            if not matched:
                continue

            results.append(
                PaperCandidate(
                    title=title,
                    url=url,
                    source="huggingface",
                    arxiv_id=arxiv_id,
                    hf_likes=likes,
                    matched_keywords=matched,
                )
            )

        logger.info("HF HTML: found %d matching papers", len(results))
        return results
