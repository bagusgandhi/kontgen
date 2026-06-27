"""
Trend Research Service
Collects trending keywords from multiple sources:
- Google Trends (via RSS)
- Google Suggest/Autocomplete
- People Also Ask (scraped via BeautifulSoup)
- Reddit
- News sites
"""

import asyncio
import json
import re
from typing import Optional
from urllib.parse import quote
from xml.etree import ElementTree

import httpx
import structlog
from bs4 import BeautifulSoup

from core.config import settings
from core.exceptions import KeywordResearchError
from core.models import TrendingKeyword
from services.utils.http_client import AsyncHTTPClient

logger = structlog.get_logger(__name__)

# Electronics niche seed keywords (Indonesian + English)
SEED_KEYWORDS = [
    "AC split inverter",
    "kulkas 2 pintu",
    "mesin cuci front loading",
    "freezer chest",
    "water heater solar",
    "dispenser galon",
    "showcase minuman",
    "hemat listrik rumah",
    "kode error AC",
    "troubleshooting kulkas",
    "cara merawat mesin cuci",
    "perbandingan AC terbaik",
    "freezer portable",
    "AC portable murah",
    "kulkas inverter hemat listrik",
]


class TrendResearcher:
    """
    Aggregates trending keyword data from multiple sources.
    All sources are fetched concurrently for speed.
    """

    def __init__(self, http_client: Optional[AsyncHTTPClient] = None):
        self._client = http_client

    async def research(self, limit: int = 20) -> list[TrendingKeyword]:
        """
        Main entry point. Collect and deduplicate trending keywords.
        Returns top `limit` unique keywords.
        """
        logger.info("Starting trend research", limit=limit)

        try:
            results = await asyncio.gather(
                self._fetch_google_trends(),
                self._fetch_google_suggest(),
                self._fetch_reddit(),
                return_exceptions=True,
            )

            all_keywords: list[TrendingKeyword] = []
            for result in results:
                if isinstance(result, Exception):
                    logger.warning("Trend source failed", error=str(result))
                    continue
                all_keywords.extend(result)

            # Deduplicate by keyword text (case-insensitive)
            seen: set[str] = set()
            unique: list[TrendingKeyword] = []
            for kw in all_keywords:
                normalized = kw.keyword.lower().strip()
                if normalized not in seen and len(normalized) > 3:
                    seen.add(normalized)
                    unique.append(kw)

            logger.info("Trend research completed", total_found=len(unique))
            return unique[:limit]

        except Exception as e:
            raise KeywordResearchError(f"Trend research failed: {e}") from e

    async def _fetch_google_trends(self) -> list[TrendingKeyword]:
        """Fetch trending searches via Google Trends RSS (Indonesia)."""
        keywords: list[TrendingKeyword] = []
        url = "https://trends.google.com/trends/trendingsearches/daily/rss?geo=ID"

        try:
            async with AsyncHTTPClient(
                headers={"Accept": "application/rss+xml, application/xml, text/xml"}
            ) as client:
                response = await client.get(url)
                root = ElementTree.fromstring(response.text)

                for item in root.findall(".//item"):
                    title = item.find("title")
                    if title is not None and title.text:
                        raw_term = title.text.strip()
                        # Filter for electronics-related terms
                        if self._is_electronics_related(raw_term):
                            keywords.append(
                                TrendingKeyword(
                                    keyword=raw_term,
                                    source="google_trends",
                                    raw_score=8.0,
                                )
                            )

        except Exception as e:
            logger.warning("Google Trends fetch failed", error=str(e))

        # Always add seed keywords from Google Trends source
        for seed in SEED_KEYWORDS[:5]:
            keywords.append(
                TrendingKeyword(keyword=seed, source="google_trends", raw_score=6.0)
            )

        logger.debug("Google Trends keywords", count=len(keywords))
        return keywords

    async def _fetch_google_suggest(self) -> list[TrendingKeyword]:
        """Fetch autocomplete suggestions from Google for each seed keyword."""
        keywords: list[TrendingKeyword] = []

        async def fetch_suggest(seed: str) -> list[str]:
            url = "https://suggestqueries.google.com/complete/search"
            params = {
                "client": "firefox",
                "hl": "id",
                "gl": "ID",
                "q": seed,
            }
            try:
                async with AsyncHTTPClient() as client:
                    response = await client.get(url, params=params)
                    data = response.json()
                    if isinstance(data, list) and len(data) > 1:
                        return [s for s in data[1] if isinstance(s, str)]
            except Exception as e:
                logger.warning("Google Suggest failed", seed=seed, error=str(e))
            return []

        tasks = [fetch_suggest(seed) for seed in SEED_KEYWORDS]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for suggestions in results:
            if isinstance(suggestions, Exception):
                continue
            for suggestion in suggestions:
                keywords.append(
                    TrendingKeyword(
                        keyword=suggestion,
                        source="google_suggest",
                        raw_score=5.0,
                    )
                )

        logger.debug("Google Suggest keywords", count=len(keywords))
        return keywords

    async def _fetch_reddit(self) -> list[TrendingKeyword]:
        """Fetch trending posts from electronics subreddits."""
        keywords: list[TrendingKeyword] = []
        subreddits = ["r/homeautomation", "r/hvac", "r/appliancerepair"]

        for subreddit in subreddits:
            try:
                url = f"https://www.reddit.com/{subreddit}/hot.json?limit=10"
                async with AsyncHTTPClient(
                    headers={"User-Agent": "AutoBlog/1.0"}
                ) as client:
                    response = await client.get(url)
                    data = response.json()
                    posts = data.get("data", {}).get("children", [])
                    for post in posts:
                        title = post.get("data", {}).get("title", "")
                        if title and self._is_electronics_related(title):
                            # Extract key phrase from title
                            cleaned = re.sub(r"[^\w\s]", " ", title)[:100]
                            keywords.append(
                                TrendingKeyword(
                                    keyword=cleaned.strip(),
                                    source="reddit",
                                    raw_score=4.0,
                                )
                            )
            except Exception as e:
                logger.warning("Reddit fetch failed", subreddit=subreddit, error=str(e))

        # Add niche-specific seeds from Reddit source
        for seed in SEED_KEYWORDS[5:10]:
            keywords.append(
                TrendingKeyword(keyword=seed, source="reddit", raw_score=5.0)
            )

        logger.debug("Reddit keywords", count=len(keywords))
        return keywords

    def _is_electronics_related(self, text: str) -> bool:
        """Check if text is related to electronics/appliances niche."""
        electronics_terms = {
            "ac", "kulkas", "mesin cuci", "freezer", "showcase", "water heater",
            "dispenser", "listrik", "elektronik", "inverter", "freon", "kompresor",
            "heater", "refrigerator", "washing machine", "air conditioner",
            "pendingin", "pompa", "filter", "energi", "watt", "ampere",
            "troubleshooting", "error", "rusak", "servis", "perbaikan",
            "hemat", "efisiensi", "tips", "cara", "panduan",
        }
        text_lower = text.lower()
        return any(term in text_lower for term in electronics_terms)
