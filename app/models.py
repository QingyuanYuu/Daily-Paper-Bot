from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class PaperCandidate:
    title: str
    url: str
    source: str  # "arxiv" | "huggingface"
    arxiv_id: Optional[str] = None
    authors: list[str] = field(default_factory=list)
    abstract: str = ""
    published: Optional[datetime] = None
    hf_likes: int = 0
    matched_keywords: list[str] = field(default_factory=list)

    # populated after ranking
    score: float = 0.0
    note_markdown: str = ""

    @property
    def dedup_key(self) -> str:
        """Primary: arxiv_id. Fallback: normalized title hash."""
        if self.arxiv_id:
            return f"arxiv:{self.arxiv_id}"
        return f"title:{self._title_hash}"

    @property
    def notion_key(self) -> str:
        """Key for Notion DB dedup: arxiv_id or hash(title+first_author+year)."""
        if self.arxiv_id:
            return self.arxiv_id
        parts = [self._normalize_title(self.title)]
        if self.authors:
            parts.append(self.authors[0].lower().strip())
        if self.published:
            parts.append(str(self.published.year))
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

    @property
    def _title_hash(self) -> str:
        norm = self._normalize_title(self.title)
        return hashlib.sha256(norm.encode()).hexdigest()[:16]

    @staticmethod
    def _normalize_title(title: str) -> str:
        title = unicodedata.normalize("NFKD", title)
        title = title.lower().strip()
        title = re.sub(r"[^a-z0-9\s]", "", title)
        title = re.sub(r"\s+", " ", title)
        return title


