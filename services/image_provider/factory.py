"""
Image Provider Factory
Selects and chains image providers based on priority order.
Supports Factory Pattern with environment variable configuration.

Usage:
    factory = ImageProviderFactory()
    result = await factory.find_image(keywords)
"""

from typing import Optional
import structlog

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

# Provider registry - add new providers here
PROVIDER_REGISTRY: dict[str, type[BaseImageProvider]] = {
    "unsplash": UnsplashProvider,
    "pexels": PexelsProvider,
    "pixabay": PixabayProvider,
    "wikimedia": WikimediaProvider,
    # Future providers:
    # "openai": OpenAIProvider,
    # "flux": FluxProvider,
}

# Default fallback priority order
DEFAULT_PRIORITY_ORDER = ["unsplash", "pexels", "pixabay", "wikimedia"]


class ImageProviderFactory:
    """
    Factory class that manages image provider selection and fallback chain.
    
    The primary provider is set via IMAGE_PROVIDER env variable.
    If the primary provider fails, falls back through the priority chain.
    """

    def __init__(self, primary_provider: Optional[str] = None):
        self._primary = primary_provider or settings.IMAGE_PROVIDER
        self._providers = self._build_provider_chain()

    def _build_provider_chain(self) -> list[BaseImageProvider]:
        """
        Build ordered list of providers starting with primary.
        Primary provider goes first, then remaining in priority order.
        """
        chain: list[BaseImageProvider] = []

        # Primary provider first
        if self._primary in PROVIDER_REGISTRY:
            chain.append(PROVIDER_REGISTRY[self._primary]())

        # Add remaining providers as fallbacks
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
        Try each provider in order until one returns a result.
        Returns None only if all providers fail.
        """
        for provider in self._providers:
            logger.info(
                "Trying image provider", provider=provider.name, keywords=keywords
            )
            try:
                result = await provider.search(keywords)
                if result:
                    logger.info(
                        "Image found",
                        provider=provider.name,
                        url=result.url[:80],
                    )
                    return result
            except Exception as e:
                logger.warning(
                    "Provider failed, trying next",
                    provider=provider.name,
                    error=str(e),
                )
                continue

        logger.warning("All image providers failed", keywords=keywords)
        return None

    @classmethod
    def get_provider(cls, name: str) -> BaseImageProvider:
        """
        Get a specific provider by name.
        Useful for direct provider access without fallback.
        """
        if name not in PROVIDER_REGISTRY:
            raise ValueError(
                f"Unknown provider: '{name}'. "
                f"Available: {list(PROVIDER_REGISTRY.keys())}"
            )
        return PROVIDER_REGISTRY[name]()
