from __future__ import annotations

import logging
import os
import re
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

    def write_digest(
        self,
        papers: list[PaperCandidate],
        digest_date: date,
        digest_markdown: str,
    ) -> str:
        """Upsert today's digest page and paper note pages. Returns digest page id."""
        digest_page_id = self._upsert_digest_page(digest_date)

        # Create/update paper note pages first so we have their IDs
        note_map: dict[str, str] = {}  # dedup_key -> note_page_id
        for paper in papers:
            note_id = self._upsert_paper_note(paper)
            note_map[paper.dedup_key] = note_id

        # Build digest body: convert markdown to blocks, then inject note links
        body_blocks = self._build_digest_body(digest_markdown, papers, note_map)
        self._replace_page_body(digest_page_id, body_blocks)

        logger.info("Wrote digest for %s with %d papers", digest_date, len(papers))
        return digest_page_id

    # ── Digest page (child of a parent page) ──────────────────

    def _upsert_digest_page(self, digest_date: date) -> str:
        title = f"Daily Digest – {digest_date.isoformat()}"

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
            "Title": {"title": [{"text": {"content": paper.title[:100]}}]},
            "URL": {"url": paper.url},
            "Key": {"rich_text": [{"text": {"content": key}}]},
        }
        if paper.arxiv_id:
            properties["ArXiv ID"] = {
                "rich_text": [{"text": {"content": paper.arxiv_id}}]
            }
        if paper.matched_keywords:
            properties["Tags"] = {
                "multi_select": [{"name": kw} for kw in paper.matched_keywords]
            }
        if paper.published:
            properties["Date Created"] = {
                "date": {"start": paper.published.strftime("%Y-%m-%d")}
            }

        note_blocks = self._build_note_body(paper)

        if existing_id:
            logger.info("Updating existing paper note for '%s'", paper.title[:50])
            self.client.pages.update(page_id=existing_id, properties=properties)
            self._replace_page_body(existing_id, note_blocks)
            return existing_id

        page = self.client.pages.create(
            parent={"database_id": self.notes_db},
            properties=properties,
            children=note_blocks,
        )
        logger.info("Created paper note for '%s' (Key=%s)", paper.title[:50], key)
        return page["id"]

    def _find_paper_note_by_key(self, key: str) -> str | None:
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

    def get_existing_keys(self) -> set[str]:
        """Return all Key values already in the Notes DB (for cross-day dedup)."""
        keys: set[str] = set()
        start_cursor = None
        while True:
            body: dict = {"page_size": 100}
            if start_cursor:
                body["start_cursor"] = start_cursor
            resp = self._query_database(self.notes_db, **body)
            for page in resp["results"]:
                rt = page.get("properties", {}).get("Key", {}).get("rich_text", [])
                if rt:
                    keys.add(rt[0]["text"]["content"])
            if not resp.get("has_more"):
                break
            start_cursor = resp.get("next_cursor")
        return keys

    def _query_database(self, database_id: str, **kwargs) -> dict:
        body = {k: v for k, v in kwargs.items()}
        return self.client.request(
            path=f"databases/{database_id}/query",
            method="POST",
            body=body,
        )

    # ── Body builders ───────────────────────────────────────────

    def _build_digest_body(
        self,
        digest_markdown: str,
        papers: list[PaperCandidate],
        note_map: dict[str, str],
    ) -> list[dict]:
        """Convert digest markdown to Notion blocks, injecting note links after each paper section."""
        blocks = _markdown_to_blocks(digest_markdown)

        # Insert "📄 Detailed Note" links after each paper's section.
        # The digest prompt outputs "### {i}. {title}" for each paper.
        # We find these headings and insert the mention link right after the last block
        # before the next paper heading (or end).
        paper_heading_indices = []
        for idx, block in enumerate(blocks):
            btype = block.get("type", "")
            if btype == "heading_3":
                text = _extract_block_text(block)
                # Match "1. Title", "2. Title", etc.
                if re.match(r"^\d+\.\s+", text):
                    paper_heading_indices.append(idx)

        # Build a map from paper index (1-based) to note_page_id
        paper_note_ids = []
        for p in papers:
            paper_note_ids.append(note_map.get(p.dedup_key, ""))

        # Insert mention blocks in reverse order so indices stay valid
        for section_idx in range(len(paper_heading_indices) - 1, -1, -1):
            if section_idx >= len(paper_note_ids):
                continue
            note_id = paper_note_ids[section_idx]
            if not note_id:
                continue

            # Find insertion point: just before the next paper heading, or end of blocks
            if section_idx + 1 < len(paper_heading_indices):
                insert_at = paper_heading_indices[section_idx + 1]
            else:
                insert_at = len(blocks)

            # Insert divider + mention link
            mention_block = _paragraph_with_mention("📄 Detailed Note", note_id)
            divider_block = _divider()
            blocks.insert(insert_at, divider_block)
            blocks.insert(insert_at, mention_block)

        return blocks

    def _build_note_body(self, paper: PaperCandidate) -> list[dict]:
        """Convert paper note markdown to Notion blocks."""
        if paper.note_markdown:
            return _markdown_to_blocks(paper.note_markdown)

        # Fallback: just show abstract if no note markdown
        return [
            _heading2(paper.title),
            _paragraph(f"Authors: {', '.join(paper.authors)}"),
            _divider(),
            _heading3("Abstract"),
            _paragraph(paper.abstract or "No abstract available."),
        ]

    # ── Helpers ──────────────────────────────────────────────────

    def _replace_page_body(self, page_id: str, blocks: list[dict]) -> None:
        # Paginate to collect ALL existing block IDs before deleting
        block_ids: list[str] = []
        cursor = None
        while True:
            kwargs: dict = {"block_id": page_id, "page_size": 100}
            if cursor:
                kwargs["start_cursor"] = cursor
            resp = self.client.blocks.children.list(**kwargs)
            block_ids.extend(b["id"] for b in resp["results"])
            if not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")

        for bid in block_ids:
            try:
                self.client.blocks.delete(block_id=bid)
            except Exception:
                pass

        # Append new blocks (Notion limit: 100 per request)
        for i in range(0, len(blocks), 100):
            self.client.blocks.children.append(
                block_id=page_id, children=blocks[i : i + 100]
            )


# ── Markdown → Notion blocks converter ─────────────────────────

def _markdown_to_blocks(md_text: str) -> list[dict]:
    """Convert markdown text to a list of Notion API block objects.

    Handles: # h1, ## h2, ### / #### h3, - bullets, --- dividers,
    **bold** inline, `code` inline, and plain paragraphs.
    """
    blocks: list[dict] = []
    lines = md_text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip empty lines
        if not stripped:
            i += 1
            continue

        # Divider: --- or *** or ___
        if re.match(r"^[-*_]{3,}\s*$", stripped):
            blocks.append(_divider())
            i += 1
            continue

        # Headings
        heading_match = re.match(r"^(#{1,4})\s+(.+)$", stripped)
        if heading_match:
            level = len(heading_match.group(1))
            text = heading_match.group(2).strip()
            if level == 1:
                blocks.append(_heading1(text))
            elif level == 2:
                blocks.append(_heading2(text))
            else:  # 3 or 4 → heading_3
                blocks.append(_heading3(text))
            i += 1
            continue

        # Bulleted list item: - text or * text
        bullet_match = re.match(r"^[-*]\s+(.+)$", stripped)
        if bullet_match:
            text = bullet_match.group(1)
            blocks.append(_bulleted_list_item(text))
            i += 1
            continue

        # Default: paragraph (accumulate consecutive non-special lines)
        para_lines = [stripped]
        i += 1
        while i < len(lines):
            next_stripped = lines[i].strip()
            if not next_stripped:
                break
            if re.match(r"^(#{1,4})\s+", next_stripped):
                break
            if re.match(r"^[-*_]{3,}\s*$", next_stripped):
                break
            if re.match(r"^[-*]\s+", next_stripped):
                break
            para_lines.append(next_stripped)
            i += 1

        blocks.append(_paragraph_rich("\n".join(para_lines)))

    return blocks


# ── Block helpers ────────────────────────────────────────────────

def _rich_text(content: str) -> list[dict]:
    """Plain rich_text, chunked to 2000 chars per element."""
    chunks = [content[i : i + 2000] for i in range(0, max(len(content), 1), 2000)]
    return [{"type": "text", "text": {"content": c}} for c in chunks]


def _rich_text_with_formatting(text: str) -> list[dict]:
    """Parse inline **bold** and `code` into Notion rich_text annotations."""
    parts: list[dict] = []
    # Split by **bold** and `code` patterns
    pattern = r"(\*\*[^*]+\*\*|`[^`]+`)"
    segments = re.split(pattern, text)
    for seg in segments:
        if not seg:
            continue
        if seg.startswith("**") and seg.endswith("**"):
            inner = seg[2:-2]
            for chunk in _chunked(inner, 2000):
                parts.append({
                    "type": "text",
                    "text": {"content": chunk},
                    "annotations": {"bold": True},
                })
        elif seg.startswith("`") and seg.endswith("`"):
            inner = seg[1:-1]
            for chunk in _chunked(inner, 2000):
                parts.append({
                    "type": "text",
                    "text": {"content": chunk},
                    "annotations": {"code": True},
                })
        else:
            for chunk in _chunked(seg, 2000):
                parts.append({"type": "text", "text": {"content": chunk}})
    return parts if parts else [{"type": "text", "text": {"content": " "}}]


def _chunked(s: str, size: int) -> list[str]:
    return [s[i : i + size] for i in range(0, max(len(s), 1), size)]


def _heading1(text: str) -> dict:
    return {"object": "block", "type": "heading_1", "heading_1": {"rich_text": _rich_text(text)}}


def _heading2(text: str) -> dict:
    return {"object": "block", "type": "heading_2", "heading_2": {"rich_text": _rich_text(text)}}


def _heading3(text: str) -> dict:
    return {"object": "block", "type": "heading_3", "heading_3": {"rich_text": _rich_text(text)}}


def _paragraph(text: str) -> dict:
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": _rich_text(text)}}


def _paragraph_rich(text: str) -> dict:
    """Paragraph with inline bold/code formatting."""
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": _rich_text_with_formatting(text)}}


def _bulleted_list_item(text: str) -> dict:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": _rich_text_with_formatting(text)},
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


def _extract_block_text(block: dict) -> str:
    """Extract plain text from a block's rich_text array."""
    btype = block.get("type", "")
    rt = block.get(btype, {}).get("rich_text", [])
    return "".join(item.get("text", {}).get("content", "") for item in rt)
