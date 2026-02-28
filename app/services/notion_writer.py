from __future__ import annotations

import logging
import os
from datetime import date

from notion_client import Client

from app.models import PaperCandidate

logger = logging.getLogger(__name__)


class NotionWriter:
    def __init__(self):
        self.client = Client(auth=os.environ["NOTION_API_KEY"], notion_version="2022-06-28")
        self.digest_parent_page = os.environ["DIGEST_PARENT_PAGE_ID"]
        self.notes_db = os.environ["NOTES_DB_ID"]

    # ── Public API ──────────────────────────────────────────────

    def write_digest(self, papers: list[PaperCandidate], digest_date: date) -> str:
        """Upsert today's digest page and create paper note pages. Returns digest page id."""
        digest_page_id = self._upsert_digest_page(digest_date)
        note_page_ids: list[tuple[PaperCandidate, str]] = []

        for paper in papers:
            note_id = self._upsert_paper_note(paper)
            note_page_ids.append((paper, note_id))

        body_blocks = self._build_digest_body(papers, note_page_ids)
        self._replace_page_body(digest_page_id, body_blocks)

        logger.info("Wrote digest for %s with %d papers", digest_date, len(papers))
        return digest_page_id

    # ── Digest page (child of a parent page) ──────────────────

    def _upsert_digest_page(self, digest_date: date) -> str:
        title = f"Daily Digest – {digest_date.isoformat()}"

        # Search existing children of the parent page for today's digest
        existing_id = self._find_child_page_by_title(self.digest_parent_page, title)
        if existing_id:
            logger.info("Found existing digest page: %s", existing_id)
            return existing_id

        page = self.client.pages.create(
            parent={"page_id": self.digest_parent_page},
            properties={
                "title": {"title": [{"text": {"content": title}}]},
            },
        )
        logger.info("Created digest page: %s", page["id"])
        return page["id"]

    def _find_child_page_by_title(self, parent_page_id: str, title: str) -> str | None:
        """Search children of a page for a child_page with matching title."""
        try:
            resp = self.client.blocks.children.list(block_id=parent_page_id, page_size=100)
            for block in resp["results"]:
                if block["type"] == "child_page" and block["child_page"]["title"] == title:
                    return block["id"]
        except Exception:
            logger.warning("Failed to list children of parent page", exc_info=True)
        return None

    # ── Paper note pages (in Notes DB) ─────────────────────────

    def _upsert_paper_note(self, paper: PaperCandidate) -> str:
        key = paper.notion_key
        existing_id = self._find_paper_note_by_key(key)

        properties: dict = {
            "Name": {"title": [{"text": {"content": paper.title[:100]}}]},
            "URL": {"url": paper.url},
            "Key": {"rich_text": [{"text": {"content": key}}]},
        }
        if paper.arxiv_id:
            properties["ArXiv ID"] = {
                "rich_text": [{"text": {"content": paper.arxiv_id}}]
            }

        if existing_id:
            logger.info("Updating existing paper note for '%s'", paper.title[:50])
            self.client.pages.update(page_id=existing_id, properties=properties)
            self._replace_page_body(existing_id, self._build_note_body(paper))
            return existing_id

        # Create new page
        page = self.client.pages.create(
            parent={"database_id": self.notes_db},
            properties=properties,
            children=self._build_note_body(paper),
        )
        logger.info("Created paper note for '%s' (Key=%s)", paper.title[:50], key)
        return page["id"]

    def _find_paper_note_by_key(self, key: str) -> str | None:
        """Find existing paper note by Key property."""
        try:
            resp = self._query_database(
                self.notes_db,
                filter={"property": "Key", "rich_text": {"equals": key}},
                page_size=1,
            )
            if resp["results"]:
                return resp["results"][0]["id"]
        except Exception:
            logger.warning("Query by Key failed", exc_info=True)
        return None

    def _query_database(self, database_id: str, **kwargs) -> dict:
        """Query a database (compatible with notion-client v3)."""
        body = {k: v for k, v in kwargs.items()}
        return self.client.request(
            path=f"databases/{database_id}/query",
            method="POST",
            body=body,
        )

    # ── Body builders ───────────────────────────────────────────

    def _build_digest_body(
        self,
        papers: list[PaperCandidate],
        note_page_ids: list[tuple[PaperCandidate, str]],
    ) -> list[dict]:
        blocks: list[dict] = []
        note_map = {p.dedup_key: nid for p, nid in note_page_ids}

        for i, paper in enumerate(papers, 1):
            tags = ", ".join(paper.matched_keywords)
            meta = f"(arXiv:{paper.arxiv_id or 'N/A'} | ❤️ {paper.hf_likes} | tags: {tags})"

            # a) Heading with link + meta
            blocks.append(_heading2(f"{i}. {paper.title}"))
            blocks.append(_link_text(paper.title, paper.url))
            blocks.append(_paragraph(meta))

            # b) Abstract
            blocks.append(_heading3("Abstract:"))
            blocks.append(_paragraph(paper.abstract or "No abstract available."))

            # c) Interpretation (skipped when summary is None)
            if paper.summary:
                blocks.append(_heading3("Interpretation:"))
                blocks.append(_paragraph(paper.summary.tldr))
                if paper.summary.core_idea:
                    blocks.append(_paragraph(paper.summary.core_idea))
                if paper.summary.method_breakdown:
                    blocks.append(_paragraph(paper.summary.method_breakdown))

            # d) Key points (skipped when summary is None)
            if paper.summary and paper.summary.key_takeaways:
                blocks.append(_heading3("Key points:"))
                for point in paper.summary.key_takeaways:
                    blocks.append(_bulleted_list_item(point))

            # e) Link to detailed note
            note_id = note_map.get(paper.dedup_key, "")
            if note_id:
                blocks.append(
                    _paragraph_with_mention("📄 Detailed Note", note_id)
                )

            # Divider between papers
            blocks.append(_divider())

        return blocks

    def _build_note_body(self, paper: PaperCandidate) -> list[dict]:
        blocks: list[dict] = []
        blocks.append(_heading2(paper.title))
        blocks.append(_link_text(paper.title, paper.url))
        if paper.arxiv_id:
            blocks.append(_paragraph(f"arXiv ID: {paper.arxiv_id}"))
        blocks.append(_paragraph(f"Authors: {', '.join(paper.authors)}"))
        blocks.append(_paragraph(f"❤️ HF Likes: {paper.hf_likes}"))
        blocks.append(_divider())

        # Abstract
        blocks.append(_heading3("Abstract"))
        blocks.append(_paragraph(paper.abstract or "No abstract available."))

        # Summary sections (skipped when summary is None)
        if paper.summary:
            s = paper.summary
            for label, content in [
                ("TL;DR", s.tldr),
                ("Core Idea", s.core_idea),
                ("Method Breakdown", s.method_breakdown),
                ("Limitations", s.limitations),
                ("Robotics Takeaways", s.robotics_takeaways),
                ("Reproduction Plan", s.reproduction_plan),
                ("Keywords & Prerequisites", s.keywords_prerequisites),
            ]:
                if content:
                    blocks.append(_heading3(label))
                    blocks.append(_paragraph(content))

            if s.key_takeaways:
                blocks.append(_heading3("Key Takeaways"))
                for point in s.key_takeaways:
                    blocks.append(_bulleted_list_item(point))

        return blocks

    # ── Helpers ──────────────────────────────────────────────────

    def _replace_page_body(self, page_id: str, blocks: list[dict]) -> None:
        # Delete existing children
        existing = self.client.blocks.children.list(block_id=page_id)
        for block in existing["results"]:
            try:
                self.client.blocks.delete(block_id=block["id"])
            except Exception:
                pass
        # Append new blocks (Notion limit: 100 per request)
        for i in range(0, len(blocks), 100):
            self.client.blocks.children.append(
                block_id=page_id, children=blocks[i : i + 100]
            )


# ── Block helpers ────────────────────────────────────────────────

def _rich_text(content: str) -> list[dict]:
    # Notion blocks have a 2000-char limit per rich_text element
    chunks = [content[i : i + 2000] for i in range(0, max(len(content), 1), 2000)]
    return [{"type": "text", "text": {"content": c}} for c in chunks]


def _heading2(text: str) -> dict:
    return {"object": "block", "type": "heading_2", "heading_2": {"rich_text": _rich_text(text)}}


def _heading3(text: str) -> dict:
    return {"object": "block", "type": "heading_3", "heading_3": {"rich_text": _rich_text(text)}}


def _paragraph(text: str) -> dict:
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": _rich_text(text)}}


def _link_text(text: str, url: str) -> dict:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": text, "link": {"url": url}}}]
        },
    }


def _bulleted_list_item(text: str) -> dict:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": _rich_text(text)},
    }


def _divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def _paragraph_with_mention(text: str, page_id: str) -> dict:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [
                {"type": "text", "text": {"content": text + " "}},
                {"type": "mention", "mention": {"type": "page", "page": {"id": page_id}}},
            ]
        },
    }
