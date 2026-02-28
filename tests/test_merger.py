from datetime import datetime, timezone

from app.models import PaperCandidate
from app.services.merger import merge_and_dedupe


def _make_paper(**kwargs) -> PaperCandidate:
    defaults = {
        "title": "Test Paper",
        "url": "https://arxiv.org/abs/2401.00001",
        "source": "arxiv",
    }
    defaults.update(kwargs)
    return PaperCandidate(**defaults)


class TestMergeAndDedupe:
    def test_dedup_by_arxiv_id(self):
        p1 = _make_paper(arxiv_id="2401.00001", source="arxiv", hf_likes=0)
        p2 = _make_paper(arxiv_id="2401.00001", source="huggingface", hf_likes=42)
        result = merge_and_dedupe([p1, p2])
        assert len(result) == 1
        assert result[0].hf_likes == 42

    def test_dedup_by_title_hash(self):
        p1 = _make_paper(title="Some Great Paper", url="http://a.com", source="arxiv")
        p2 = _make_paper(title="Some Great Paper", url="http://b.com", source="huggingface", hf_likes=10)
        result = merge_and_dedupe([p1, p2])
        assert len(result) == 1
        assert result[0].hf_likes == 10

    def test_title_normalization_dedup(self):
        p1 = _make_paper(title="  Some  GREAT paper! ", url="http://a.com", source="arxiv")
        p2 = _make_paper(title="some great paper", url="http://b.com", source="huggingface")
        result = merge_and_dedupe([p1, p2])
        assert len(result) == 1

    def test_no_false_dedup(self):
        p1 = _make_paper(title="Paper A", arxiv_id="2401.00001")
        p2 = _make_paper(title="Paper B", arxiv_id="2401.00002")
        result = merge_and_dedupe([p1, p2])
        assert len(result) == 2

    def test_merges_keywords(self):
        p1 = _make_paper(arxiv_id="2401.00001", matched_keywords=["humanoid"])
        p2 = _make_paper(arxiv_id="2401.00001", matched_keywords=["diffusion"])
        result = merge_and_dedupe([p1, p2])
        assert set(result[0].matched_keywords) == {"humanoid", "diffusion"}

    def test_fills_missing_abstract(self):
        p1 = _make_paper(arxiv_id="2401.00001", abstract="")
        p2 = _make_paper(arxiv_id="2401.00001", abstract="A great abstract.")
        result = merge_and_dedupe([p1, p2])
        assert result[0].abstract == "A great abstract."

    def test_fills_missing_published(self):
        dt = datetime(2024, 1, 15, tzinfo=timezone.utc)
        p1 = _make_paper(arxiv_id="2401.00001", published=None)
        p2 = _make_paper(arxiv_id="2401.00001", published=dt)
        result = merge_and_dedupe([p1, p2])
        assert result[0].published == dt

    def test_empty_input(self):
        assert merge_and_dedupe([]) == []
