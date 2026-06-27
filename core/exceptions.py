"""
Custom exceptions for AutoBlog Generator.
"""


class AutoBlogException(Exception):
    """Base exception for all AutoBlog errors."""
    pass


class KeywordResearchError(AutoBlogException):
    """Raised when keyword research fails."""
    pass


class ContentGenerationError(AutoBlogException):
    """Raised when content generation fails."""
    pass


class SEOValidationError(AutoBlogException):
    """Raised when SEO validation fails critically."""
    pass


class ImageProviderError(AutoBlogException):
    """Raised when all image providers fail."""
    pass


class ImageProcessingError(AutoBlogException):
    """Raised when image processing (resize/overlay) fails."""
    pass


class WordPressError(AutoBlogException):
    """Raised when WordPress API calls fail."""
    pass


class NotificationError(AutoBlogException):
    """Raised when Telegram notification fails."""
    pass


class DuplicateArticleError(AutoBlogException):
    """Raised when article already exists in WordPress."""
    pass
