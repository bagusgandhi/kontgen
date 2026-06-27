"""
WordPress REST API Client
Handles media upload, post creation, and duplicate checking.
Uses WordPress Application Passwords for authentication.
"""

import base64
import mimetypes
import os
from pathlib import Path
from typing import Optional
import structlog
import httpx

from core.config import settings
from core.exceptions import WordPressError, DuplicateArticleError
from core.models import ArticleContent, WordPressMedia, WordPressPost

logger = structlog.get_logger(__name__)


class WordPressClient:
    """
    WordPress REST API v2 client.
    
    Authentication: Basic Auth with Application Password
    (Settings → Users → Application Passwords in WP Admin)
    """

    def __init__(
        self,
        wp_url: str = settings.WORDPRESS_URL,
        username: str = settings.WORDPRESS_USERNAME,
        app_password: str = settings.WORDPRESS_APP_PASSWORD,
    ):
        self._base_url = wp_url.rstrip("/")
        self._api_base = f"{self._base_url}/wp-json/wp/v2"
        self._auth_header = self._build_auth_header(username, app_password)

    def _build_auth_header(self, username: str, password: str) -> str:
        """Build Basic Auth header from WordPress Application Password."""
        credentials = f"{username}:{password}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return f"Basic {encoded}"

    def _get_headers(self, content_type: str = "application/json") -> dict:
        return {
            "Authorization": self._auth_header,
            "Content-Type": content_type,
            "Accept": "application/json",
        }

    async def check_duplicate(self, slug: str) -> bool:
        """
        Check if article with given slug already exists in WordPress.
        Returns True if duplicate exists.
        """
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(
                    f"{self._api_base}/posts",
                    params={"slug": slug, "status": "any"},
                    headers=self._get_headers(),
                )
                response.raise_for_status()
                posts = response.json()
                exists = len(posts) > 0
                if exists:
                    logger.info("Duplicate article found in WordPress", slug=slug)
                return exists

        except httpx.HTTPStatusError as e:
            logger.error("WP duplicate check failed", slug=slug, status=e.response.status_code)
            raise WordPressError(f"Failed to check duplicate: {e}") from e
        except Exception as e:
            logger.error("WP duplicate check error", error=str(e))
            raise WordPressError(f"Failed to check duplicate: {e}") from e

    async def upload_media(
        self,
        image_path: str,
        title: str,
        alt_text: str = "",
        caption: str = "",
    ) -> WordPressMedia:
        """
        Upload image to WordPress Media Library.
        Returns media ID and URL.
        """
        path = Path(image_path)
        if not path.exists():
            raise WordPressError(f"Image file not found: {image_path}")

        content_type = mimetypes.guess_type(str(path))[0] or "image/webp"
        filename = path.name

        logger.info("Uploading media to WordPress", filename=filename)

        try:
            with open(image_path, "rb") as f:
                file_data = f.read()

            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    f"{self._api_base}/media",
                    headers={
                        "Authorization": self._auth_header,
                        "Content-Disposition": f'attachment; filename="{filename}"',
                        "Content-Type": content_type,
                    },
                    content=file_data,
                    params={
                        "title": title,
                        "alt_text": alt_text,
                        "caption": caption,
                    },
                )
                response.raise_for_status()
                media_data = response.json()

            # Update alt text via PATCH (more reliable)
            if alt_text:
                await self._update_media_meta(
                    client, media_data["id"], alt_text, title, caption
                )

            result = WordPressMedia(
                media_id=media_data["id"],
                url=media_data["source_url"],
                title=title,
            )
            logger.info(
                "Media uploaded", media_id=result.media_id, url=result.url[:80]
            )
            return result

        except httpx.HTTPStatusError as e:
            logger.error(
                "WP media upload failed",
                status=e.response.status_code,
                error=e.response.text[:200],
            )
            raise WordPressError(f"Media upload failed: {e}") from e
        except Exception as e:
            logger.error("WP media upload error", error=str(e))
            raise WordPressError(f"Media upload failed: {e}") from e

    async def _update_media_meta(
        self,
        client: httpx.AsyncClient,
        media_id: int,
        alt_text: str,
        title: str,
        caption: str,
    ) -> None:
        """Update media metadata after upload."""
        try:
            await client.post(
                f"{self._api_base}/media/{media_id}",
                json={"alt_text": alt_text, "title": title, "caption": caption},
                headers=self._get_headers(),
            )
        except Exception as e:
            logger.warning("Failed to update media meta", error=str(e))

    async def create_post(
        self,
        article: ArticleContent,
        media_id: Optional[int] = None,
        category_ids: Optional[list[int]] = None,
        tag_ids: Optional[list[int]] = None,
        status: str = settings.WORDPRESS_DEFAULT_STATUS,
    ) -> WordPressPost:
        """
        Create WordPress post with full SEO metadata.
        Includes Yoast SEO / RankMath meta fields.
        """
        # Build full content: article body + FAQ schema
        full_content = self._build_full_content(article)

        post_data = {
            "title": article.seo_title,
            "slug": article.slug,
            "content": full_content,
            "excerpt": article.excerpt,
            "status": status,
            "meta": {
                # Yoast SEO
                "_yoast_wpseo_title": article.seo_title,
                "_yoast_wpseo_metadesc": article.meta_description,
                "_yoast_wpseo_focuskw": article.focus_keyword,
                # RankMath
                "rank_math_title": article.seo_title,
                "rank_math_description": article.meta_description,
                "rank_math_focus_keyword": article.focus_keyword,
            },
        }

        if media_id:
            post_data["featured_media"] = media_id

        if category_ids:
            post_data["categories"] = category_ids
        else:
            post_data["categories"] = [settings.WORDPRESS_DEFAULT_CATEGORY_ID]

        if tag_ids:
            post_data["tags"] = tag_ids

        logger.info("Creating WordPress post", title=article.seo_title, status=status)

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    f"{self._api_base}/posts",
                    json=post_data,
                    headers=self._get_headers(),
                )
                response.raise_for_status()
                post_data_response = response.json()

            post = WordPressPost(
                wp_post_id=post_data_response["id"],
                title=post_data_response["title"]["rendered"],
                slug=post_data_response["slug"],
                url=post_data_response["link"],
                status=post_data_response["status"],
                featured_media_id=media_id,
            )

            logger.info(
                "WordPress post created",
                post_id=post.wp_post_id,
                url=post.url,
                status=post.status,
            )
            return post

        except httpx.HTTPStatusError as e:
            logger.error(
                "WP post creation failed",
                status=e.response.status_code,
                error=e.response.text[:500],
            )
            raise WordPressError(f"Post creation failed: {e}") from e
        except Exception as e:
            logger.error("WP post creation error", error=str(e))
            raise WordPressError(f"Post creation failed: {e}") from e

    async def get_or_create_category(self, name: str) -> int:
        """Get category ID by name, or create it if not exists."""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                # Search existing
                response = await client.get(
                    f"{self._api_base}/categories",
                    params={"search": name, "per_page": 5},
                    headers=self._get_headers(),
                )
                categories = response.json()
                for cat in categories:
                    if cat["name"].lower() == name.lower():
                        return cat["id"]

                # Create new
                response = await client.post(
                    f"{self._api_base}/categories",
                    json={"name": name},
                    headers=self._get_headers(),
                )
                response.raise_for_status()
                return response.json()["id"]

        except Exception as e:
            logger.warning("Failed to get/create category", name=name, error=str(e))
            return settings.WORDPRESS_DEFAULT_CATEGORY_ID

    async def get_or_create_tags(self, tag_names: list[str]) -> list[int]:
        """Get or create multiple tags, return their IDs."""
        tag_ids = []
        for name in tag_names[:10]:  # Limit to 10 tags
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    # Search existing
                    response = await client.get(
                        f"{self._api_base}/tags",
                        params={"search": name, "per_page": 5},
                        headers=self._get_headers(),
                    )
                    tags = response.json()
                    found = False
                    for tag in tags:
                        if tag["name"].lower() == name.lower():
                            tag_ids.append(tag["id"])
                            found = True
                            break

                    if not found:
                        response = await client.post(
                            f"{self._api_base}/tags",
                            json={"name": name},
                            headers=self._get_headers(),
                        )
                        if response.status_code in (200, 201):
                            tag_ids.append(response.json()["id"])

            except Exception as e:
                logger.warning("Failed to process tag", name=name, error=str(e))

        return tag_ids

    def _build_full_content(self, article: ArticleContent) -> str:
        """
        Build complete WordPress post content:
        - H1 heading
        - Article body HTML
        - FAQ section
        - CTA section
        - JSON-LD FAQ schema (in script tag)
        """
        parts = []

        # H1 is set in WordPress title, but add to content for schema markup
        parts.append(f'<h1 class="article-main-title">{article.h1}</h1>\n')

        # Main article body
        parts.append(article.body_html)

        # FAQ Section
        if article.faq:
            parts.append('\n<section class="faq-section" itemscope itemtype="https://schema.org/FAQPage">')
            parts.append('<h2>Pertanyaan yang Sering Ditanyakan (FAQ)</h2>')
            for faq_item in article.faq:
                parts.append(
                    f'''<div class="faq-item" itemscope itemprop="mainEntity" itemtype="https://schema.org/Question">
  <h3 itemprop="name">{faq_item.question}</h3>
  <div itemscope itemprop="acceptedAnswer" itemtype="https://schema.org/Answer">
    <div itemprop="text">{faq_item.answer}</div>
  </div>
</div>'''
                )
            parts.append("</section>\n")

        # CTA
        if article.cta:
            parts.append(
                f'\n<div class="article-cta">\n  <p>{article.cta}</p>\n</div>\n'
            )

        # JSON-LD FAQ Schema
        if article.faq_schema_json and article.faq_schema_json != "{}":
            parts.append(
                f'\n<script type="application/ld+json">\n{article.faq_schema_json}\n</script>\n'
            )

        # Internal link suggestions (as HTML comment for editor reference)
        if article.internal_link_suggestions:
            suggestions = "\n".join(
                f"  - {s}" for s in article.internal_link_suggestions
            )
            parts.append(
                f"\n<!-- Internal Link Suggestions:\n{suggestions}\n-->\n"
            )

        return "\n".join(parts)
