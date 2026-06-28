"""
Concrete Image Provider Implementations.
Each provider searches their respective API for free-to-use images.

Priority order (configured via IMAGE_PROVIDER env):
1. Unsplash
2. Pexels
3. Pixabay
4. Wikimedia Commons

Each provider accepts `exclude_urls` — a set of already-used image URLs.
Results that match any excluded URL are skipped, ensuring variety.
"""

import random
from typing import Optional
import structlog

from core.config import settings
from core.models import ImageResult
from services.utils.http_client import AsyncHTTPClient
from .base import BaseImageProvider

logger = structlog.get_logger(__name__)

# Fetch more results per request so we have candidates to filter from
RESULTS_PER_PAGE = 15


class UnsplashProvider(BaseImageProvider):
    """
    Unsplash API provider.
    Free tier: 50 requests/hour.
    License: Free for commercial use (Unsplash License).
    """

    BASE_URL = "https://api.unsplash.com"

    @property
    def name(self) -> str:
        return "unsplash"

    async def search(
        self,
        keywords: list[str],
        orientation: str = "landscape",
        exclude_urls: Optional[set[str]] = None,
    ) -> Optional[ImageResult]:
        if not settings.UNSPLASH_ACCESS_KEY:
            logger.warning("Unsplash API key not configured")
            return None

        exclude_urls = exclude_urls or set()

        # Try each keyword until we find a fresh image
        queries = self._build_query_list(keywords)
        for query in queries:
            result = await self._search_query(query, orientation, exclude_urls)
            if result:
                return result

        return None

    async def _search_query(
        self, query: str, orientation: str, exclude_urls: set[str]
    ) -> Optional[ImageResult]:
        logger.debug("Searching Unsplash", query=query, excluded=len(exclude_urls))

        try:
            async with AsyncHTTPClient(
                base_url=self.BASE_URL,
                headers={"Authorization": f"Client-ID {settings.UNSPLASH_ACCESS_KEY}"},
            ) as client:
                # Fetch page 1 and page 2 for more variety
                candidates = []
                for page in [1, 2]:
                    response = await client.get(
                        "/search/photos",
                        params={
                            "query": query,
                            "orientation": orientation,
                            "per_page": RESULTS_PER_PAGE,
                            "page": page,
                            "order_by": "relevant",
                            "content_filter": "high",
                        },
                    )
                    results = response.json().get("results", [])
                    candidates.extend(results)
                    if not results:
                        break

                # Filter out already-used URLs
                fresh = [
                    p for p in candidates
                    if p["urls"]["regular"] not in exclude_urls
                ]

                if not fresh:
                    logger.debug("All Unsplash results already used", query=query)
                    return None

                # Pick randomly from fresh candidates for variety
                photo = random.choice(fresh)
                return ImageResult(
                    url=photo["urls"]["regular"],
                    photographer=photo["user"]["name"],
                    photographer_url=photo["user"]["links"]["html"],
                    source="unsplash",
                    license="Unsplash License (Free for commercial use)",
                    alt_text=photo.get("alt_description") or query,
                )

        except Exception as e:
            logger.error("Unsplash search failed", query=query, error=str(e))
            return None


class PexelsProvider(BaseImageProvider):
    """
    Pexels API provider.
    Free tier: 200 requests/hour.
    License: Pexels License (Free for commercial use).
    """

    BASE_URL = "https://api.pexels.com/v1"

    @property
    def name(self) -> str:
        return "pexels"

    async def search(
        self,
        keywords: list[str],
        orientation: str = "landscape",
        exclude_urls: Optional[set[str]] = None,
    ) -> Optional[ImageResult]:
        if not settings.PEXELS_API_KEY:
            logger.warning("Pexels API key not configured")
            return None

        exclude_urls = exclude_urls or set()
        queries = self._build_query_list(keywords)

        for query in queries:
            result = await self._search_query(query, orientation, exclude_urls)
            if result:
                return result

        return None

    async def _search_query(
        self, query: str, orientation: str, exclude_urls: set[str]
    ) -> Optional[ImageResult]:
        logger.debug("Searching Pexels", query=query, excluded=len(exclude_urls))

        try:
            async with AsyncHTTPClient(
                base_url=self.BASE_URL,
                headers={"Authorization": settings.PEXELS_API_KEY},
            ) as client:
                candidates = []
                for page in [1, 2]:
                    response = await client.get(
                        "/search",
                        params={
                            "query": query,
                            "orientation": orientation,
                            "per_page": RESULTS_PER_PAGE,
                            "page": page,
                            "size": "large",
                        },
                    )
                    photos = response.json().get("photos", [])
                    candidates.extend(photos)
                    if not photos:
                        break

                fresh = [
                    p for p in candidates
                    if p["src"]["large2x"] not in exclude_urls
                ]

                if not fresh:
                    logger.debug("All Pexels results already used", query=query)
                    return None

                photo = random.choice(fresh)
                return ImageResult(
                    url=photo["src"]["large2x"],
                    photographer=photo["photographer"],
                    photographer_url=photo["photographer_url"],
                    source="pexels",
                    license="Pexels License (Free for commercial use)",
                    alt_text=photo.get("alt") or query,
                )

        except Exception as e:
            logger.error("Pexels search failed", query=query, error=str(e))
            return None


class PixabayProvider(BaseImageProvider):
    """
    Pixabay API provider.
    Free tier: 100 requests/minute.
    License: Pixabay License (Free for commercial use, no attribution required).
    """

    BASE_URL = "https://pixabay.com/api"

    @property
    def name(self) -> str:
        return "pixabay"

    async def search(
        self,
        keywords: list[str],
        orientation: str = "landscape",
        exclude_urls: Optional[set[str]] = None,
    ) -> Optional[ImageResult]:
        if not settings.PIXABAY_API_KEY:
            logger.warning("Pixabay API key not configured")
            return None

        exclude_urls = exclude_urls or set()
        queries = self._build_query_list(keywords)

        for query in queries:
            result = await self._search_query(query, orientation, exclude_urls)
            if result:
                return result

        return None

    async def _search_query(
        self, query: str, orientation: str, exclude_urls: set[str]
    ) -> Optional[ImageResult]:
        logger.debug("Searching Pixabay", query=query, excluded=len(exclude_urls))

        try:
            async with AsyncHTTPClient(base_url=self.BASE_URL) as client:
                candidates = []
                for page in [1, 2]:
                    response = await client.get(
                        "/",
                        params={
                            "key": settings.PIXABAY_API_KEY,
                            "q": query,
                            "orientation": orientation,
                            "image_type": "photo",
                            "safesearch": "true",
                            "per_page": RESULTS_PER_PAGE,
                            "page": page,
                            "min_width": 1200,
                            "min_height": 630,
                        },
                    )
                    hits = response.json().get("hits", [])
                    candidates.extend(hits)
                    if not hits:
                        break

                fresh = [
                    p for p in candidates
                    if p["largeImageURL"] not in exclude_urls
                ]

                if not fresh:
                    logger.debug("All Pixabay results already used", query=query)
                    return None

                photo = random.choice(fresh)
                return ImageResult(
                    url=photo["largeImageURL"],
                    photographer=photo.get("user", ""),
                    photographer_url=f"https://pixabay.com/users/{photo.get('user', '')}",
                    source="pixabay",
                    license="Pixabay License (Free, no attribution required)",
                    alt_text=query,
                )

        except Exception as e:
            logger.error("Pixabay search failed", query=query, error=str(e))
            return None


class WikimediaProvider(BaseImageProvider):
    """
    Wikimedia Commons provider.
    Free: Public domain or Creative Commons licensed images.
    """

    BASE_URL = "https://commons.wikimedia.org/w/api.php"

    @property
    def name(self) -> str:
        return "wikimedia"

    async def search(
        self,
        keywords: list[str],
        orientation: str = "landscape",
        exclude_urls: Optional[set[str]] = None,
    ) -> Optional[ImageResult]:
        exclude_urls = exclude_urls or set()
        query = self._pick_best_keyword(keywords)
        logger.debug("Searching Wikimedia Commons", query=query)

        try:
            async with AsyncHTTPClient() as client:
                response = await client.get(
                    self.BASE_URL,
                    params={
                        "action": "query",
                        "format": "json",
                        "list": "search",
                        "srnamespace": "6",
                        "srsearch": f"{query} filetype:jpeg",
                        "srlimit": RESULTS_PER_PAGE,
                        "srprop": "snippet",
                    },
                )
                results = response.json().get("query", {}).get("search", [])
                if not results:
                    return None

                # Shuffle for variety
                random.shuffle(results)

                for item in results:
                    title = item["title"]
                    info_response = await client.get(
                        self.BASE_URL,
                        params={
                            "action": "query",
                            "format": "json",
                            "titles": title,
                            "prop": "imageinfo",
                            "iiprop": "url|extmetadata",
                            "iiurlwidth": 1200,
                        },
                    )
                    pages = info_response.json().get("query", {}).get("pages", {})
                    for page in pages.values():
                        imageinfo = page.get("imageinfo", [{}])[0]
                        url = imageinfo.get("thumburl") or imageinfo.get("url", "")
                        if url and url not in exclude_urls:
                            meta = imageinfo.get("extmetadata", {})
                            return ImageResult(
                                url=url,
                                photographer=meta.get("Artist", {}).get("value", ""),
                                photographer_url="https://commons.wikimedia.org",
                                source="wikimedia",
                                license=meta.get("LicenseShortName", {}).get("value", "CC License"),
                                alt_text=query,
                            )

        except Exception as e:
            logger.error("Wikimedia search failed", query=query, error=str(e))
        return None
