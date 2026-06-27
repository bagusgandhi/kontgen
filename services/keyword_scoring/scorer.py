"""
Keyword Scoring Service
Scores each keyword across 6 dimensions using GPT-4o Mini for intelligence
and heuristic rules for fast scoring.
"""

import json
from typing import Optional
import structlog
from openai import AsyncOpenAI

from core.config import settings
from core.exceptions import KeywordResearchError
from core.models import TrendingKeyword, KeywordScore
from core.openai_client import create_openai_client

logger = structlog.get_logger(__name__)

NICHE_KEYWORDS = settings.niche_keyword_list

SCORING_PROMPT = """
You are an SEO expert specializing in Indonesian electronics/home appliances content.

Score the following keyword across 6 dimensions. Return ONLY a valid JSON object.

Keyword: "{keyword}"

Scoring dimensions (scale 0-10):
1. search_volume_score: Estimated monthly search volume in Indonesia (0=very low, 10=very high)
2. search_intent_score: Informational/commercial intent alignment (0=unclear, 10=very clear intent to buy/learn)
3. evergreen_score: Topic longevity (0=very seasonal/trending only, 10=always relevant)
4. commercial_value_score: Revenue potential for electronics blog (0=none, 10=high affiliate/ad value)
5. competition_score: Inverted competition (0=extremely competitive, 10=low competition, easy to rank)
6. relevance_score: Relevance to electronics/home appliances niche (0=off-topic, 10=exact match)

Target niches: {niches}

Return EXACTLY this JSON format:
{{
  "search_volume_score": <float>,
  "search_intent_score": <float>,
  "evergreen_score": <float>,
  "commercial_value_score": <float>,
  "competition_score": <float>,
  "relevance_score": <float>,
  "reasoning": "<brief 1-2 sentence explanation>"
}}
"""


class KeywordScorer:
    """
    Scores keywords using a combination of:
    - GPT-4o Mini for semantic understanding
    - Heuristic rules for fast pre-filtering
    """

    def __init__(self, openai_client: Optional[AsyncOpenAI] = None):
        self._client = openai_client or create_openai_client()

    async def score(self, keyword: TrendingKeyword) -> KeywordScore:
        """Score a single keyword using GPT-4o Mini."""
        logger.debug("Scoring keyword", keyword=keyword.keyword)

        try:
            prompt = SCORING_PROMPT.format(
                keyword=keyword.keyword,
                niches=", ".join(NICHE_KEYWORDS),
            )

            response = await self._client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=400,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            scores_data = json.loads(content)

            # Calculate weighted total score
            total = (
                scores_data.get("search_volume_score", 5.0)
                * settings.SCORE_WEIGHT_SEARCH_VOLUME
                + scores_data.get("search_intent_score", 5.0)
                * settings.SCORE_WEIGHT_SEARCH_INTENT
                + scores_data.get("evergreen_score", 5.0)
                * settings.SCORE_WEIGHT_EVERGREEN
                + scores_data.get("commercial_value_score", 5.0)
                * settings.SCORE_WEIGHT_COMMERCIAL
                + scores_data.get("competition_score", 5.0)
                * settings.SCORE_WEIGHT_COMPETITION
                + scores_data.get("relevance_score", 5.0)
                * settings.SCORE_WEIGHT_RELEVANCE
            )

            scored = KeywordScore(
                keyword=keyword.keyword,
                search_volume_score=scores_data.get("search_volume_score", 5.0),
                search_intent_score=scores_data.get("search_intent_score", 5.0),
                evergreen_score=scores_data.get("evergreen_score", 5.0),
                commercial_value_score=scores_data.get("commercial_value_score", 5.0),
                competition_score=scores_data.get("competition_score", 5.0),
                relevance_score=scores_data.get("relevance_score", 5.0),
                total_score=round(total, 2),
                source=keyword.source,
                reasoning=scores_data.get("reasoning", ""),
            )

            logger.debug(
                "Keyword scored",
                keyword=keyword.keyword,
                total_score=scored.total_score,
            )
            return scored

        except json.JSONDecodeError as e:
            logger.warning("Failed to parse GPT scoring response", error=str(e))
            return self._fallback_score(keyword)
        except Exception as e:
            logger.error("Keyword scoring error", keyword=keyword.keyword, error=str(e))
            return self._fallback_score(keyword)

    async def score_batch(self, keywords: list[TrendingKeyword]) -> list[KeywordScore]:
        """Score multiple keywords and return sorted by total_score descending."""
        import asyncio

        # Score in batches of 5 to avoid rate limits
        batch_size = 5
        all_scores: list[KeywordScore] = []

        for i in range(0, len(keywords), batch_size):
            batch = keywords[i : i + batch_size]
            tasks = [self.score(kw) for kw in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, Exception):
                    logger.warning("Batch scoring failed for keyword", error=str(result))
                    continue
                all_scores.append(result)

            # Small delay between batches
            if i + batch_size < len(keywords):
                await asyncio.sleep(0.5)

        return sorted(all_scores, key=lambda x: x.total_score, reverse=True)

    def _fallback_score(self, keyword: TrendingKeyword) -> KeywordScore:
        """
        Heuristic-based fallback scoring when GPT fails.
        Uses keyword characteristics to estimate scores.
        """
        text = keyword.keyword.lower()

        # Relevance heuristic
        relevance = 8.0 if any(
            term in text for term in ["ac", "kulkas", "mesin cuci", "freezer",
                                       "water heater", "dispenser", "elektronik"]
        ) else 4.0

        # Intent heuristic
        informational_signals = ["cara", "tips", "panduan", "bagaimana", "kenapa", "kode error"]
        commercial_signals = ["terbaik", "murah", "harga", "rekomendasi", "beli", "pilih"]
        intent = 7.0 if any(s in text for s in informational_signals + commercial_signals) else 5.0

        # Evergreen heuristic
        evergreen = 7.0 if any(
            term in text for term in ["cara", "tips", "kode error", "panduan", "troubleshooting"]
        ) else 5.0

        total = (
            5.0 * settings.SCORE_WEIGHT_SEARCH_VOLUME
            + intent * settings.SCORE_WEIGHT_SEARCH_INTENT
            + evergreen * settings.SCORE_WEIGHT_EVERGREEN
            + 5.0 * settings.SCORE_WEIGHT_COMMERCIAL
            + 5.0 * settings.SCORE_WEIGHT_COMPETITION
            + relevance * settings.SCORE_WEIGHT_RELEVANCE
        )

        return KeywordScore(
            keyword=keyword.keyword,
            search_volume_score=5.0,
            search_intent_score=intent,
            evergreen_score=evergreen,
            commercial_value_score=5.0,
            competition_score=5.0,
            relevance_score=relevance,
            total_score=round(total, 2),
            source=keyword.source,
            reasoning="Heuristic fallback score (GPT unavailable)",
        )
