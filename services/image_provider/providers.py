"""
Concrete Image Provider Implementations.
Each provider searches their respective API for free-to-use images.

Priority order (configured via IMAGE_PROVIDER env):
1. Unsplash
2. Pexels
3. Pixabay
4. Wikimedia Commons
"""

import urllib.parse
from typing import Optional
import structlog

from core.config import settings
from core.models import ImageResult
from services.utils.http_client import AsyncHTTPClient
from .base import BaseImageProvider

logger = structlog.get_logger(__name__)


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
        self, keywords: list[str], orientation: str = "landscape"
    ) -> Optional[ImageResult]:
        if not settings.UNSPLASH_ACCESS_KEY:
            logger.warning("Unsplash API key not configured")
            return None

        query = self._pick_best_keyword(keywords)
        logger.debug("Searching Unsplash", query=query)

        try:
            async with AsyncHTTPClient(
                base_url=self.BASE_URL,
                headers={"Authorization": f"Client-ID {settings.UNSPLASH_ACCESS_KEY}"},
            ) as client:
                response = await client.get(
                    "/search/photos",
                    params={
                        "query": query,
                        "orientation": orientation,
                        "per_page": 5,
                        "order_by": "relevant",
                        "content_filter": "high",
                    },
                )
                data = response.json()
                results = data.get("results", [])

                if not results:
                    # Try with first keyword
                    if len(keywords) > 1:
                        return await self._retry_search(keywords[0])
                    return None

                photo = results[0]
                return ImageResult(
                    url=photo["urls"]["regular"],  # 1080px wide
                    photographer=photo["user"]["name"],
                    photographer_url=photo["user"]["links"]["html"],
                    source="unsplash",
                    license="Unsplash License (Free for commercial use)",
                    alt_text=photo.get("alt_description") or query,
                )

        except Exception as e:
            logger.error("Unsplash search failed", query=query, error=str(e))
            return None

    async def _retry_search(self, query: str) -> Optional[ImageResult]:
        """Retry with simplified query."""
        try:
            async with AsyncHTTPClient(
                base_url=self.BASE_URL,
                headers={"Authorization": f"Client-ID {settings.UNSPLASH_ACCESS_KEY}"},
            ) as client:
                response = await client.get(
                    "/search/photos",
                    params={"query": query, "per_page": 3},
                )
                results = response.json().get("results", [])
                if results:
                    photo = results[0]
                    return ImageResult(
                        url=photo["urls"]["regular"],
                        photographer=photo["user"]["name"],
                        photographer_url=photo["user"]["links"]["html"],
                        source="unsplash",
                        license="Unsplash License",
                        alt_text=query,
                    )
        except Exception:
            pass
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
        self, keywords: list[str], orientation: str = "landscape"
    ) -> Optional[ImageResult]:
        if not settings.PEXELS_API_KEY:
            logger.warning("Pexels API key not configured")
            return None

        query = self._pick_best_keyword(keywords)
        logger.debug("Searching Pexels", query=query)

        try:
            async with AsyncHTTPClient(
                base_url=self.BASE_URL,
                headers={"Authorization": settings.PEXELS_API_KEY},
            ) as client:
                response = await client.get(
                    "/search",
                    params={
                        "query": query,
                        "orientation": orientation,
                        "per_page": 5,
                        "size": "large",
                    },
                )
                data = response.json()
                photos = data.get("photos", [])

                if not photos:
                    return None

                photo = photos[0]
                return ImageResult(
                    url=photo["src"]["large2x"],  # 940x627
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
        self, keywords: list[str], orientation: str = "landscape"
    ) -> Optional[ImageResult]:
        if not settings.PIXABAY_API_KEY:
            logger.warning("Pixabay API key not configured")
            return None

        query = self._pick_best_keyword(keywords)
        logger.debug("Searching Pixabay", query=query)

        try:
            async with AsyncHTTPClient(base_url=self.BASE_URL) as client:
                response = await client.get(
                    "/",
                    params={
                        "key": settings.PIXABAY_API_KEY,
                        "q": query,
                        "orientation": orientation,
                        "image_type": "photo",
                        "safesearch": "true",
                        "per_page": 5,
                        "min_width": 1200,
                        "min_height": 630,
                    },
                )
                data = response.json()
                hits = data.get("hits", [])

                if not hits:
                    return None

                photo = hits[0]
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
        self, keywords: list[str], orientation: str = "landscape"
    ) -> Optional[ImageResult]:
        query = self._pick_best_keyword(keywords)
        logger.debug("Searching Wikimedia Commons", query=query)

        try:
            async with AsyncHTTPClient() as client:
                # Search for images
                response = await client.get(
                    self.BASE_URL,
                    params={
                        "action": "query",
                        "format": "json",
                        "list": "search",
                        "srnamespace": "6",  # File namespace
                        "srsearch": f"{query} filetype:jpeg",
                        "srlimit": 5,
                        "srprop": "snippet",
                    },
                )
                data = response.json()
                results = data.get("query", {}).get("search", [])

                if not results:
                    return None

                # Get image info for first result
                title = results[0]["title"]
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
                info_data = info_response.json()
                pages = info_data.get("query", {}).get("pages", {})

                for page in pages.values():
                    imageinfo = page.get("imageinfo", [{}])[0]
                    url = imageinfo.get("thumburl") or imageinfo.get("url", "")
                    if url:
                        meta = imageinfo.get("extmetadata", {})
                        artist = meta.get("Artist", {}).get("value", "")
                        license_name = meta.get("LicenseShortName", {}).get(
                            "value", "CC License"
                        )
                        return ImageResult(
                            url=url,
                            photographer=artist,
                            photographer_url="https://commons.wikimedia.org",
                            source="wikimedia",
                            license=license_name,
                            alt_text=query,
                        )

        except Exception as e:
            logger.error("Wikimedia search failed", query=query, error=str(e))
        return None
