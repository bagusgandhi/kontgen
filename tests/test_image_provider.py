"""
Tests for Image Provider Factory and Providers.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from core.models import ImageResult
from services.image_provider.factory import ImageProviderFactory, PROVIDER_REGISTRY
from services.image_provider.base import BaseImageProvider


class TestImageProviderFactory:
    def test_factory_creates_provider_chain(self):
        factory = ImageProviderFactory(primary_provider="unsplash")
        assert len(factory._providers) > 0
        assert factory._providers[0].name == "unsplash"

    def test_factory_puts_primary_first(self):
        factory = ImageProviderFactory(primary_provider="pexels")
        assert factory._providers[0].name == "pexels"

    def test_factory_fallback_chain_excludes_primary(self):
        factory = ImageProviderFactory(primary_provider="unsplash")
        names = [p.name for p in factory._providers]
        # Primary should appear only once
        assert names.count("unsplash") == 1

    def test_get_provider_returns_correct_instance(self):
        provider = ImageProviderFactory.get_provider("pixabay")
        assert provider.name == "pixabay"

    def test_get_provider_raises_for_unknown(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            ImageProviderFactory.get_provider("nonexistent_provider")

    @pytest.mark.asyncio
    async def test_find_image_returns_first_success(self):
        factory = ImageProviderFactory(primary_provider="unsplash")

        mock_result = ImageResult(
            url="https://example.com/image.jpg",
            source="unsplash",
        )

        # Mock all providers
        for provider in factory._providers:
            provider.search = AsyncMock(return_value=None)

        # Make first provider succeed
        factory._providers[0].search = AsyncMock(return_value=mock_result)

        result = await factory.find_image(["air conditioner"])
        assert result is not None
        assert result.source == "unsplash"

    @pytest.mark.asyncio
    async def test_find_image_falls_back_to_next_provider(self):
        factory = ImageProviderFactory(primary_provider="unsplash")

        mock_result = ImageResult(
            url="https://example.com/image.jpg",
            source="pexels",
        )

        # First provider fails
        factory._providers[0].search = AsyncMock(return_value=None)
        # Second provider succeeds
        if len(factory._providers) > 1:
            factory._providers[1].search = AsyncMock(return_value=mock_result)
            for p in factory._providers[2:]:
                p.search = AsyncMock(return_value=None)

            result = await factory.find_image(["air conditioner"])
            assert result is not None

    @pytest.mark.asyncio
    async def test_find_image_returns_none_when_all_fail(self):
        factory = ImageProviderFactory(primary_provider="unsplash")
        for provider in factory._providers:
            provider.search = AsyncMock(return_value=None)

        result = await factory.find_image(["very obscure search term xyz"])
        assert result is None


class TestBaseImageProvider:
    def test_pick_best_keyword_returns_longest(self):
        class ConcreteProvider(BaseImageProvider):
            @property
            def name(self):
                return "test"
            async def search(self, keywords, orientation="landscape"):
                return None

        provider = ConcreteProvider()
        result = provider._pick_best_keyword(["ac", "air conditioner", "modern AC split"])
        assert result == "modern AC split"

    def test_pick_best_keyword_with_empty_list(self):
        class ConcreteProvider(BaseImageProvider):
            @property
            def name(self):
                return "test"
            async def search(self, keywords, orientation="landscape"):
                return None

        provider = ConcreteProvider()
        result = provider._pick_best_keyword([])
        assert result == "home appliance electronics"
