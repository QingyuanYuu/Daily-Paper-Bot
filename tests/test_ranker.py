import math
from datetime import datetime, timedelta, timezone

from app.models import PaperCandidate
from app.services.ranker import rank_papers, score_paper


def _make_paper(**kwargs) -> PaperCandidate:
    defaults = {
        "title": "Test Paper",
        "url": "https://arxiv.org/abs/2401.00001",
        "source": "arxiv",
    }
    defaults.update(kwargs)
    return PaperCandidate(**defaults)


KEYWORDS = ["humanoid", "world model", "diffusion", "dexterous manipulation"]


class TestScorePaper:
    def test_zero_likes_zero_recency(self):
        p = _make_paper(hf_likes=0, published=None, matched_keywords=[])
        s = score_paper(p, KEYWORDS)
        assert s == 0.0

    def test_likes_contribute(self):
        p = _make_paper(hf_likes=100, published=None, matched_keywords=[])
        s = score_paper(p, KEYWORDS)
        expected_likes = 0.6 * math.log(1 + 100)
        assert abs(s - expected_likes) < 1e-6

    def test_recent_paper_scores_higher(self):
        now = datetime.now(timezone.utc)
        recent = _make_paper(
            hf_likes=10,
            published=now - timedelta(hours=6),
            matched_keywords=["humanoid"],
        )
        old = _make_paper(
            hf_likes=10,
            published=now - timedelta(days=6),
            matched_keywords=["humanoid"],
        )
        assert score_paper(recent, KEYWORDS) > score_paper(old, KEYWORDS)

    def test_more_keywords_scores_higher(self):
        p1 = _make_paper(hf_likes=0, published=None, matched_keywords=["humanoid"])
        p2 = _make_paper(
            hf_likes=0,
            published=None,
            matched_keywords=["humanoid", "diffusion", "world model"],
        )
        assert score_paper(p2, KEYWORDS) > score_paper(p1, KEYWORDS)

    def test_keyword_strength_fraction(self):
        p = _make_paper(
            hf_likes=0,
            published=None,
            matched_keywords=["humanoid", "diffusion"],
        )
        s = score_paper(p, KEYWORDS)
        # Only keyword component: 0.1 * (2/4) = 0.05
        assert abs(s - 0.05) < 1e-6


class TestRankPapers:
    def test_top_k_selection(self):
        papers = [
            _make_paper(title=f"Paper {i}", arxiv_id=f"2401.{i:05d}", hf_likes=i * 10)
            for i in range(10)
        ]
        result = rank_papers(papers, KEYWORDS, top_k=5)
        assert len(result) == 5
        # Highest likes should be first
        assert result[0].hf_likes == 90

    def test_top_k_larger_than_pool(self):
        papers = [_make_paper(title="Only One", hf_likes=5)]
        result = rank_papers(papers, KEYWORDS, top_k=5)
        assert len(result) == 1

    def test_scores_are_set(self):
        papers = [_make_paper(hf_likes=50)]
        result = rank_papers(papers, KEYWORDS, top_k=1)
        assert result[0].score > 0

    def test_custom_weights(self):
        now = datetime.now(timezone.utc)
        p_likes = _make_paper(title="Liked", hf_likes=200, published=now - timedelta(days=5))
        p_recent = _make_paper(title="Recent", hf_likes=1, published=now - timedelta(hours=1))

        # With default weights (likes-heavy), liked paper wins
        result_default = rank_papers([p_likes, p_recent], KEYWORDS, top_k=1)
        assert result_default[0].title == "Liked"

        # With recency-heavy weights, recent paper wins
        result_recency = rank_papers(
            [p_likes, p_recent],
            KEYWORDS,
            top_k=1,
            weights={"hf_likes": 0.1, "recency": 0.8, "keyword_match": 0.1},
        )
        assert result_recency[0].title == "Recent"
