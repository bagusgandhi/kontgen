"""
OpenAI client factory.
Creates AsyncOpenAI with optional custom base_url from settings.
Supports any OpenAI-compatible API (OpenRouter, LM Studio, Ollama, Azure, etc.)
"""

from typing import Optional
from openai import AsyncOpenAI
import structlog

from core.config import settings

logger = structlog.get_logger(__name__)


def create_openai_client(
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> AsyncOpenAI:
    """
    Create an AsyncOpenAI client.

    Priority for base_url:
      1. Explicit argument (for tests / override)
      2. OPENAI_BASE_URL env variable
      3. OpenAI default (https://api.openai.com/v1)

    Priority for api_key:
      1. Explicit argument
      2. OPENAI_API_KEY env variable
    """
    resolved_key = api_key or settings.OPENAI_API_KEY
    resolved_url = base_url or settings.OPENAI_BASE_URL or None  # None → SDK default

    if resolved_url:
        logger.info("OpenAI client using custom base URL", base_url=resolved_url)

    return AsyncOpenAI(
        api_key=resolved_key,
        base_url=resolved_url,  # None uses the official endpoint
    )
