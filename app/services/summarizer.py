from __future__ import annotations

import logging
import os
from pathlib import Path

import anthropic

from app.models import PaperCandidate, PaperSummary

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

    @staticmethod
    def _build_user_message(paper: PaperCandidate) -> str:
        return (
            f"Title: {paper.title}\n"
            f"Authors: {', '.join(paper.authors)}\n"
            f"Abstract: {paper.abstract}\n"
            f"Keywords matched: {', '.join(paper.matched_keywords)}\n"
        )

    def summarize_for_digest(self, paper: PaperCandidate) -> str:
        """Short interpretation for the daily digest page. Returns raw markdown text."""
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=800,
                system=self.digest_prompt,
                messages=[{"role": "user", "content": self._build_user_message(paper)}],
                temperature=0.3,
            )
            return response.content[0].text
        except Exception:
            logger.error("Digest summary failed for '%s'", paper.title, exc_info=True)
            return ""

    def summarize_for_note(self, paper: PaperCandidate) -> PaperSummary:
        """Full analysis for the paper note page."""
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2500,
                system=self.note_prompt,
                messages=[{"role": "user", "content": self._build_user_message(paper)}],
                temperature=0.3,
            )
            text = response.content[0].text
        except Exception:
            logger.error("Note summary failed for '%s'", paper.title, exc_info=True)
            return PaperSummary(tldr="Summary generation failed.")

        return self._parse_response(text)

    @staticmethod
    def _parse_response(text: str) -> PaperSummary:
        summary = PaperSummary()
        sections = {
            "**TL;DR**": "tldr",
            "**Core Idea**": "core_idea",
            "**Method Breakdown**": "method_breakdown",
            "**Key Takeaways**": "key_takeaways",
            "**Limitations**": "limitations",
            "**Robotics Takeaways**": "robotics_takeaways",
            "**Reproduction Plan**": "reproduction_plan",
            "**Keywords & Prerequisites**": "keywords_prerequisites",
        }

        current_field = None
        buffer: list[str] = []

        for line in text.split("\n"):
            matched_section = False
            for header, field_name in sections.items():
                if line.strip().startswith(header):
                    if current_field:
                        _set_field(summary, current_field, buffer)
                    current_field = field_name
                    buffer = []
                    rest = line.strip()[len(header):].strip()
                    if rest:
                        buffer.append(rest)
                    matched_section = True
                    break
            if not matched_section and current_field:
                buffer.append(line)

        if current_field:
            _set_field(summary, current_field, buffer)

        return summary


def _set_field(summary: PaperSummary, field_name: str, lines: list[str]) -> None:
    text = "\n".join(lines).strip()
    if field_name == "key_takeaways":
        bullets = [l.lstrip("- ").strip() for l in text.split("\n") if l.strip().startswith("-")]
        summary.key_takeaways = bullets
    else:
        setattr(summary, field_name, text)
