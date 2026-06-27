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
    Follows Interface Segregation Principle - each provider implements
    only the search method.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier name."""
        ...

    @abstractmethod
    async def search(
        self, keywords: list[str], orientation: str = "landscape"
    ) -> Optional[ImageResult]:
        """
        Search for an image matching the keywords.
        
        Args:
            keywords: List of search terms (English preferred)
            orientation: 'landscape', 'portrait', or 'square'
            
        Returns:
            ImageResult if found, None otherwise.
        """
        ...

    def _pick_best_keyword(self, keywords: list[str]) -> str:
        """Pick the most descriptive keyword for search."""
        if not keywords:
            return "home appliance electronics"
        # Prefer longer, more descriptive keywords
        return max(keywords, key=len)
