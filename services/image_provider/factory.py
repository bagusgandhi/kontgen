"""
Image Provider Factory
Selects and chains image providers based on priority order.
Passes already-used image URLs to each provider so they skip
images that have appeared on previous articles.

Usage:
    factory = ImageProviderFactory(db_session=session)
    result = await factory.find_image(keywords)
"""

import hashlib
from typing import Optional
from datetime import datetime
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.config import settings
from core.models import ImageResult
from .base import BaseImageProvider
from .providers import (
    UnsplashProvider,
    PexelsProvider,
    PixabayProvider,
    WikimediaProvider,
)

logger = structlog.get_logger(__name__)

PROVIDER_REGISTRY: dict[str, type[BaseImageProvider]] = {
    "unsplash": UnsplashProvider,
    "pexels": PexelsProvider,
    "pixabay": PixabayProvider,
    "wikimedia": WikimediaProvider,
    # Future:
    # "openai": OpenAIProvider,
    # "flux": FluxProvider,
}

DEFAULT_PRIORITY_ORDER = ["unsplash", "pexels", "pixabay", "wikimedia"]


def _url_hash(url: str) -> str:
    """Stable short hash of a URL for dedup lookup."""
    return hashlib.sha256(url.encode()).hexdigest()[:32]


class ImageProviderFactory:
    """
    Factory that manages provider selection, fallback chain,
    and used-image deduplication.

    Pass a db_session to enable dedup tracking.
    Without a session, dedup is disabled (useful for tests).
    """

    def __init__(
        self,
        primary_provider: Optional[str] = None,
        db_session: Optional[AsyncSession] = None,
    ):
        self._primary = primary_provider or settings.IMAGE_PROVIDER
        self._db = db_session
        self._providers = self._build_provider_chain()

    def _build_provider_chain(self) -> list[BaseImageProvider]:
        chain: list[BaseImageProvider] = []
        if self._primary in PROVIDER_REGISTRY:
            chain.append(PROVIDER_REGISTRY[self._primary]())
        for name in DEFAULT_PRIORITY_ORDER:
            if name != self._primary and name in PROVIDER_REGISTRY:
                chain.append(PROVIDER_REGISTRY[name]())
        logger.info(
            "Image provider chain configured",
            primary=self._primary,
            chain=[p.name for p in chain],
        )
        return chain

    async def find_image(self, keywords: list[str]) -> Optional[ImageResult]:
        """
        Try each provider in order, skipping already-used images.

        Flow per provider:
          1. Load set of used URLs from DB
          2. Pass exclude_urls to provider.search()
          3. Provider fetches 15+ results, filters out excluded, picks randomly
          4. If provider returns None (all used), try next provider
          5. If result found, record it in used_images table
        """
        # Load all used URLs once (shared across provider attempts)
        exclude_urls = await self._load_used_urls()
        logger.info(
            "Image search starting",
            keywords=keywords,
            already_used_count=len(exclude_urls),
        )

        for provider in self._providers:
            logger.info("Trying image provider", provider=provider.name)
            try:
                result = await provider.search(
                    keywords,
                    exclude_urls=exclude_urls,
                )
                if result:
                    logger.info(
                        "Fresh image found",
                        provider=provider.name,
                        url=result.url[:80],
                    )
                    # Record usage so future runs skip this image
                    await self._record_used(result, keywords[0] if keywords else "")
                    return result
            except Exception as e:
                logger.warning(
                    "Provider failed, trying next",
                    provider=provider.name,
                    error=str(e),
                )
                continue

        logger.warning("All providers exhausted (all results already used or failed)")
        return None

    async def _load_used_urls(self) -> set[str]:
        """
        Load all previously used image URLs from DB.
        Returns empty set if no DB session available.
        """
        if not self._db:
            return set()
        try:
            from services.database import UsedImageRecord
            stmt = select(UsedImageRecord.url)
            result = await self._db.execute(stmt)
            return set(result.scalars().all())
        except Exception as e:
            logger.warning("Could not load used image URLs", error=str(e))
            return set()

    async def _record_used(self, result: ImageResult, keyword: str) -> None:
        """
        Persist image URL to used_images table.
        Silently skips if no DB session or URL already recorded.
        """
        if not self._db:
            return
        try:
            from services.database import UsedImageRecord
            h = _url_hash(result.url)
            # Check if already recorded (upsert-like)
            stmt = select(UsedImageRecord).where(UsedImageRecord.url_hash == h)
            existing = await self._db.execute(stmt)
            if existing.scalar_one_or_none() is None:
                record = UsedImageRecord(
                    url_hash=h,
                    url=result.url,
                    source=result.source,
                    keyword=keyword,
                    used_at=datetime.utcnow(),
                )
                self._db.add(record)
                await self._db.commit()
                logger.debug("Image URL recorded as used", source=result.source)
        except Exception as e:
            logger.warning("Could not record used image", error=str(e))

    @classmethod
    def get_provider(cls, name: str) -> BaseImageProvider:
        if name not in PROVIDER_REGISTRY:
            raise ValueError(
                f"Unknown provider: '{name}'. "
                f"Available: {list(PROVIDER_REGISTRY.keys())}"
            )
        return PROVIDER_REGISTRY[name]()
