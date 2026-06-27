"""
Shared async HTTP client with retry mechanism and timeout handling.
"""

import asyncio
from typing import Any, Optional
import httpx
import structlog
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)
import logging

from core.config import settings

logger = structlog.get_logger(__name__)


class AsyncHTTPClient:
    """
    Reusable async HTTP client with built-in retry logic.
    Use as context manager for proper connection pooling.
    """

    DEFAULT_TIMEOUT = 30.0
    DEFAULT_HEADERS = {
        "User-Agent": "AutoBlog-Generator/1.0 (compatible; automated content research)",
        "Accept": "application/json",
    }

    def __init__(
        self,
        base_url: str = "",
        headers: Optional[dict] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self._base_url = base_url
        self._headers = {**self.DEFAULT_HEADERS, **(headers or {})}
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "AsyncHTTPClient":
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=self._headers,
            timeout=self._timeout,
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *_) -> None:
        if self._client:
            await self._client.aclose()

    @retry(
        stop=stop_after_attempt(settings.RETRY_MAX_ATTEMPTS),
        wait=wait_exponential(multiplier=1, min=settings.RETRY_WAIT_SECONDS, max=10),
        retry=retry_if_exception_type((httpx.RequestError, httpx.HTTPStatusError)),
        before_sleep=before_sleep_log(logging.getLogger(__name__), logging.WARNING),
    )
    async def get(
        self,
        url: str,
        params: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> httpx.Response:
        if not self._client:
            raise RuntimeError("Client not initialized. Use as async context manager.")
        response = await self._client.get(url, params=params, headers=headers)
        response.raise_for_status()
        return response

    @retry(
        stop=stop_after_attempt(settings.RETRY_MAX_ATTEMPTS),
        wait=wait_exponential(multiplier=1, min=settings.RETRY_WAIT_SECONDS, max=10),
        retry=retry_if_exception_type((httpx.RequestError, httpx.HTTPStatusError)),
        before_sleep=before_sleep_log(logging.getLogger(__name__), logging.WARNING),
    )
    async def post(
        self,
        url: str,
        json: Optional[dict] = None,
        data: Optional[Any] = None,
        headers: Optional[dict] = None,
        files: Optional[Any] = None,
    ) -> httpx.Response:
        if not self._client:
            raise RuntimeError("Client not initialized. Use as async context manager.")
        response = await self._client.post(
            url, json=json, data=data, headers=headers, files=files
        )
        response.raise_for_status()
        return response

    async def download_bytes(self, url: str) -> bytes:
        """Download raw bytes from URL (for image download)."""
        if not self._client:
            raise RuntimeError("Client not initialized. Use as async context manager.")
        response = await self._client.get(url)
        response.raise_for_status()
        return response.content
