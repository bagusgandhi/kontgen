"""
Tests for Keyword Scorer Service.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from core.models import TrendingKeyword
from services.keyword_scoring.scorer import KeywordScorer


def make_mock_openai(response_content: str):
    """Create mock OpenAI client."""
    client = AsyncMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = response_content
    client.chat.completions.create = AsyncMock(return_value=response)
    return client


class TestKeywordScorer:
    @pytest.mark.asyncio
    async def test_score_returns_keyword_score(self):
        mock_response = json.dumps({
            "search_volume_score": 7.5,
            "search_intent_score": 8.0,
            "evergreen_score": 9.0,
            "commercial_value_score": 7.0,
            "competition_score": 6.0,
            "relevance_score": 9.5,
            "reasoning": "High intent keyword for electronics niche",
        })
        scorer = KeywordScorer(openai_client=make_mock_openai(mock_response))
        kw = TrendingKeyword(keyword="cara merawat AC", source="google_suggest")
        result = await scorer.score(kw)

        assert result.keyword == "cara merawat AC"
        assert 0 <= result.total_score <= 10
        assert result.relevance_score == 9.5
        assert result.reasoning != ""

    @pytest.mark.asyncio
    async def test_score_uses_fallback_on_invalid_json(self):
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=Exception("API error")
        )
        scorer = KeywordScorer(openai_client=mock_client)
        kw = TrendingKeyword(keyword="kulkas 2 pintu inverter", source="reddit")
        result = await scorer.score(kw)

        # Fallback should still return a valid score
        assert result.keyword == "kulkas 2 pintu inverter"
        assert result.total_score >= 0
        assert "fallback" in result.reasoning.lower()

    @pytest.mark.asyncio
    async def test_score_batch_sorts_by_total_score(self):
        responses = [
            json.dumps({
                "search_volume_score": float(i),
                "search_intent_score": float(i),
                "evergreen_score": float(i),
                "commercial_value_score": float(i),
                "competition_score": float(i),
                "relevance_score": float(i),
                "reasoning": f"test {i}",
            })
            for i in range(1, 4)
        ]

        call_count = 0
        async def mock_create(*args, **kwargs):
            nonlocal call_count
            response = MagicMock()
            response.choices = [MagicMock()]
            response.choices[0].message.content = responses[call_count % len(responses)]
            call_count += 1
            return response

        mock_client = AsyncMock()
        mock_client.chat.completions.create = mock_create

        scorer = KeywordScorer(openai_client=mock_client)
        keywords = [
            TrendingKeyword(keyword=f"keyword {i}", source="test")
            for i in range(3)
        ]
        results = await scorer.score_batch(keywords)

        # Should be sorted descending
        scores = [r.total_score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_fallback_score_electronics_keyword_gets_high_relevance(self):
        scorer = KeywordScorer.__new__(KeywordScorer)
        kw = TrendingKeyword(keyword="cara servis kulkas tidak dingin", source="test")
        result = scorer._fallback_score(kw)
        assert result.relevance_score >= 7.0

    def test_fallback_score_non_electronics_gets_low_relevance(self):
        scorer = KeywordScorer.__new__(KeywordScorer)
        kw = TrendingKeyword(keyword="resep masakan ayam goreng", source="test")
        result = scorer._fallback_score(kw)
        assert result.relevance_score < 7.0
