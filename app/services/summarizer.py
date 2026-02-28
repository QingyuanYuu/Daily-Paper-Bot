from __future__ import annotations

import logging
import os
from datetime import date
from pathlib import Path

import anthropic

from app.models import PaperCandidate

logger = logging.getLogger(__name__)

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "skills"


class Summarizer:
    def __init__(self, model: str = "claude-sonnet-4-20250514"):
        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.model = model
        self.digest_prompt = self._load_prompt("digest_prompt.md")
        self.note_prompt = self._load_prompt("note_prompt.md")

    @staticmethod
    def _load_prompt(filename: str) -> str:
        path = SKILLS_DIR / filename
        if path.exists():
            return path.read_text()
        logger.warning("Prompt file not found: %s", path)
        return "You are a research analyst. Produce a structured paper analysis."

    # ── Digest: one call for ALL papers ──────────────────────────

    def summarize_for_digest(
        self,
        papers: list[PaperCandidate],
        digest_date: date,
        keywords: list[str],
    ) -> str:
        """Generate the full daily digest page markdown (one call for all papers)."""
        user_msg = self._build_digest_user_message(papers, digest_date, keywords)
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=8000,
                system=self.digest_prompt,
                messages=[{"role": "user", "content": user_msg}],
                temperature=0.3,
            )
            return response.content[0].text
        except Exception:
            logger.error("Digest summary failed", exc_info=True)
            return ""

    # ── Note: one call per paper ─────────────────────────────────

    def summarize_for_note(self, paper: PaperCandidate) -> str:
        """Generate detailed note page markdown for a single paper."""
        user_msg = self._build_note_user_message(paper)
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4000,
                system=self.note_prompt,
                messages=[{"role": "user", "content": user_msg}],
                temperature=0.3,
            )
            return response.content[0].text
        except Exception:
            logger.error("Note summary failed for '%s'", paper.title, exc_info=True)
            return ""

    # ── User message builders ────────────────────────────────────

    @staticmethod
    def _build_digest_user_message(
        papers: list[PaperCandidate],
        digest_date: date,
        keywords: list[str],
    ) -> str:
        lines = [
            f"date: {digest_date.isoformat()}",
            f"keywords_today: {', '.join(keywords)}",
            f"papers ({len(papers)} total):",
            "",
        ]
        for i, p in enumerate(papers, 1):
            lines.append(f"--- paper {i} ---")
            lines.append(f"title: {p.title}")
            lines.append(f"authors: {', '.join(p.authors) if p.authors else '未提供'}")
            lines.append(f"affiliations: 未提供")
            lines.append(f"source: {p.source}")
            lines.append(f"url_arxiv: {p.url if p.arxiv_id else '未提供'}")
            lines.append(f"url_pdf: {'未提供'}")
            lines.append(f"url_hf: {'未提供'}")
            lines.append(f"published_date: {p.published.strftime('%Y-%m-%d') if p.published else '未提供'}")
            lines.append(f"hf_likes: {p.hf_likes}")
            lines.append(f"matched_tags: {', '.join(p.matched_keywords)}")
            lines.append(f"abstract: {p.abstract or '未提供'}")
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _build_note_user_message(paper: PaperCandidate) -> str:
        lines = [
            f"title: {paper.title}",
            f"authors: {', '.join(paper.authors) if paper.authors else '未提供'}",
            f"affiliations: 未提供",
            f"source: {paper.source}",
            f"url_arxiv: {paper.url if paper.arxiv_id else '未提供'}",
            f"url_pdf: 未提供",
            f"url_hf: 未提供",
            f"published_date: {paper.published.strftime('%Y-%m-%d') if paper.published else '未提供'}",
            f"hf_likes: {paper.hf_likes}",
            f"matched_tags: {', '.join(paper.matched_keywords)}",
            f"abstract: {paper.abstract or '未提供'}",
        ]
        return "\n".join(lines)
