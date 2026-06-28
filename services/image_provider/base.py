"""
Base Image Provider Interface (Abstract Base Class).
All image providers must implement this interface.
"""

from abc import ABC, abstractmethod
from typing import Optional
from core.models import ImageResult


class BaseImageProvider(ABC):
    """
    Abstract base class for all image providers.
    Each provider implements search() which accepts an optional
    set of already-used URLs to exclude from results.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier name."""
        ...

    @abstractmethod
    async def search(
        self,
        keywords: list[str],
        orientation: str = "landscape",
        exclude_urls: Optional[set[str]] = None,
    ) -> Optional[ImageResult]:
        """
        Search for a fresh image matching the keywords.

        Args:
            keywords: List of search terms (English preferred).
            orientation: 'landscape', 'portrait', or 'square'.
            exclude_urls: Set of image URLs already used — skip these.

        Returns:
            ImageResult if a fresh image is found, None otherwise.
        """
        ...

    def _pick_best_keyword(self, keywords: list[str]) -> str:
        """Pick the most descriptive keyword for search."""
        if not keywords:
            return "home appliance electronics"
        return max(keywords, key=len)

    def _build_query_list(self, keywords: list[str]) -> list[str]:
        """
        Build an ordered list of queries to try.
        Tries longer/more specific keywords first, then shorter fallbacks.
        This gives more variety when specific queries run out of fresh results.

        Example:
          Input:  ["modern air conditioner unit", "air conditioner", "AC"]
          Output: ["modern air conditioner unit", "air conditioner", "AC",
                   "home appliance electronics"]  ← generic fallback last
        """
        if not keywords:
            return ["home appliance electronics"]

        # Sort by length descending (more specific first), deduplicate
        seen: set[str] = set()
        ordered: list[str] = []
        for kw in sorted(keywords, key=len, reverse=True):
            kw = kw.strip()
            if kw and kw.lower() not in seen:
                seen.add(kw.lower())
                ordered.append(kw)

        # Always add a generic fallback so we have something to try
        ordered.append("home appliance electronics")
        return ordered
