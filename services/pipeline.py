"""
Pipeline Orchestrator Service
Coordinates all services in the correct sequence.
This is the main business logic layer called by n8n via REST API.

Pipeline Flow:
1. Research trending keywords
2. Score keywords
3. Check WordPress for duplicates
4. Generate article outline
5. Generate full article
6. Validate SEO
7. Find & process thumbnail image
8. Upload image to WordPress
9. Create WordPress draft post
10. Send Telegram notification
"""

import asyncio
import time
import uuid
from datetime import datetime
from typing import Optional

import structlog
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.exceptions import (
    ContentGenerationError,
    DuplicateArticleError,
    KeywordResearchError,
    WordPressError,
)
from core.models import (
    ArticleContent,
    KeywordScore,
    PipelineRequest,
    PipelineResult,
    PipelineStatus,
    TrendingKeyword,
)
from core.openai_client import create_openai_client
from services.content_generator.generator import ContentGenerator
from services.database import ArticleRecord, KeywordRecord, PipelineRunRecord
from services.image_provider.factory import ImageProviderFactory
from services.keyword_scoring.scorer import KeywordScorer
from services.seo_validator.validator import SEOValidator
from services.trend_research.researcher import TrendResearcher
from services.utils.image_processor import ImageProcessor
from services.utils.notifier import TelegramNotifier
from services.wordpress.client import WordPressClient

logger = structlog.get_logger(__name__)


class PipelineOrchestrator:
    """
    Main orchestrator for the AutoBlog generation pipeline.
    
    Dependencies are injected for testability and extensibility.
    All services can be swapped via Dependency Injection.
    """

    def __init__(
        self,
        db_session: AsyncSession,
        openai_client: Optional[AsyncOpenAI] = None,
    ):
        self._db = db_session
        self._openai = openai_client or create_openai_client()

        # Initialize all services
        self._trend_researcher = TrendResearcher(openai_client=self._openai)
        self._keyword_scorer = KeywordScorer(self._openai)
        self._content_generator = ContentGenerator(self._openai)
        self._seo_validator = SEOValidator()
        self._image_factory = ImageProviderFactory(db_session=self._db)  # pass DB for dedup
        self._image_processor = ImageProcessor()
        self._wp_client = WordPressClient()
        self._notifier = TelegramNotifier()

    async def run(self, request: PipelineRequest, run_id: Optional[str] = None) -> PipelineResult:
        """
        Execute the complete blog generation pipeline.
        Handles errors gracefully and always sends notification.

        Args:
            request: Pipeline request parameters.
            run_id: If provided, reuse existing PipelineRunRecord (created by /run-async).
                    If None, create a new record (used by /run synchronous endpoint).
        """
        run_id = run_id or str(uuid.uuid4())
        start_time = time.time()
        result = PipelineResult(
            success=False,
            keyword=request.keyword or "",
            timestamp=datetime.utcnow(),
        )

        # Reuse existing record (async mode) or create new one (sync mode)
        from sqlalchemy import select as sa_select
        stmt = sa_select(PipelineRunRecord).where(PipelineRunRecord.run_id == run_id)
        existing = await self._db.execute(stmt)
        run_record = existing.scalar_one_or_none()

        if run_record is None:
            run_record = PipelineRunRecord(
                run_id=run_id,
                keyword=request.keyword or "",
                status="running",
                progress_step="started",
            )
            self._db.add(run_record)
            await self._db.commit()
        else:
            run_record.progress_step = "started"
            await self._db.commit()

        try:
            logger.info(
                "Pipeline started",
                run_id=run_id,
                keyword=request.keyword,
                force=request.force,
            )

            # ─── Step 1: Keyword Selection ─────────────────────────────────
            await self._update_progress(run_record, "keyword_research")
            keyword = await self._select_keyword(request)
            result.keyword = keyword

            logger.info("Keyword selected", keyword=keyword)

            # ─── Step 2: Duplicate Check ───────────────────────────────────
            if not request.force:
                await self._update_progress(run_record, "duplicate_check")
                if await self._is_duplicate(keyword):
                    raise DuplicateArticleError(
                        f"Article for '{keyword}' already published"
                    )

            # ─── Step 3: Generate Outline ──────────────────────────────────
            await self._update_progress(run_record, "generate_outline")
            outline = await self._content_generator.generate_outline(keyword)

            # ─── Step 4: Generate Full Article ────────────────────────────
            await self._update_progress(run_record, "generate_article")
            article = await self._content_generator.generate_article(keyword, outline)
            result.article_title = article.seo_title
            result.word_count = article.word_count
            run_record.article_title = article.seo_title

            # ─── Step 5: SEO Validation ────────────────────────────────────
            await self._update_progress(run_record, "seo_validation")
            seo_result = self._seo_validator.validate(article)
            result.seo_score = seo_result.keyword_density * 5  # Rough score

            if not seo_result.is_valid:
                logger.warning(
                    "SEO validation issues found",
                    issues=seo_result.issues,
                    proceeding=True,
                )
                # Log issues but don't block publishing

            # ─── Step 6: Find Thumbnail ────────────────────────────────────
            await self._update_progress(run_record, "find_image")
            image_result = await self._image_factory.find_image(
                article.image_search_keywords
            )

            # ─── Step 7: Process Image ─────────────────────────────────────
            await self._update_progress(run_record, "process_image")
            processed_image = await self._image_processor.process(
                image_result, article.seo_title
            )
            result.thumbnail_source = processed_image.source

            # ─── Step 8: Upload Media to WordPress ────────────────────────
            await self._update_progress(run_record, "upload_media")
            wp_media = await self._wp_client.upload_media(
                image_path=processed_image.local_path,
                title=article.seo_title,
                alt_text=image_result.alt_text if image_result else article.focus_keyword,
                caption=(
                    f"Photo by {image_result.photographer}" if image_result else ""
                ),
            )

            # Cleanup temp file
            self._image_processor.cleanup(processed_image.local_path)

            # ─── Step 9: Determine Categories & Tags ──────────────────────
            await self._update_progress(run_record, "assign_taxonomy")
            category_id = await self._wp_client.get_or_create_category(
                self._determine_category(keyword)
            )
            tag_ids = await self._wp_client.get_or_create_tags(
                self._extract_tags(keyword, article)
            )

            # ─── Step 10: Create WordPress Draft ─────────────────────────
            await self._update_progress(run_record, "create_draft")
            wp_post = await self._wp_client.create_post(
                article=article,
                media_id=wp_media.media_id,
                category_ids=[category_id],
                tag_ids=tag_ids,
                status="draft",
            )

            result.wp_post_id = wp_post.wp_post_id
            result.wp_draft_url = f"{settings.WORDPRESS_URL}/?p={wp_post.wp_post_id}"
            run_record.wp_post_id = wp_post.wp_post_id

            # ─── Step 11: Save to local database ──────────────────────────
            await self._save_article_record(
                article, wp_post, processed_image.source,
                thumbnail_url=image_result.url if image_result else "",
            )

            # ─── Success ───────────────────────────────────────────────────
            result.success = True
            result.processing_time_seconds = round(time.time() - start_time, 2)
            run_record.status = "completed"
            run_record.completed_at = datetime.utcnow()
            run_record.processing_time_seconds = result.processing_time_seconds

            logger.info(
                "Pipeline completed successfully",
                run_id=run_id,
                keyword=keyword,
                post_id=wp_post.wp_post_id,
                time=result.processing_time_seconds,
            )

        except DuplicateArticleError as e:
            result.error_message = str(e)
            result.success = False
            run_record.status = "skipped"
            run_record.error_message = str(e)
            logger.info("Pipeline skipped - duplicate article", keyword=result.keyword)

        except Exception as e:
            result.error_message = str(e)
            result.success = False
            result.processing_time_seconds = round(time.time() - start_time, 2)
            run_record.status = "failed"
            run_record.error_message = str(e)[:500]
            run_record.completed_at = datetime.utcnow()
            run_record.processing_time_seconds = result.processing_time_seconds
            logger.error(
                "Pipeline failed",
                run_id=run_id,
                error=str(e),
                keyword=result.keyword,
                exc_info=True,
            )

        finally:
            # Always save run record and send notification
            await self._db.commit()
            if result.error_message != str(DuplicateArticleError):
                await self._notifier.send_result(result)

        return result

    async def _select_keyword(self, request: PipelineRequest) -> str:
        """Select keyword: use provided one or research trending."""
        if request.keyword:
            return request.keyword

        # Load existing keywords dari DB agar GPT tidak suggest duplikat
        from sqlalchemy import select as sa_select2
        stmt = sa_select2(ArticleRecord.keyword)
        result = await self._db.execute(stmt)
        existing_keywords = list(result.scalars().all())

        # Auto-research dengan mode dari request
        mode = request.mode if request.mode in ("balanced", "golden") else "balanced"
        trending = await self._trend_researcher.research(
            limit=20,
            mode=mode,
            existing_keywords=existing_keywords,
        )

        if not trending:
            raise KeywordResearchError("No trending keywords found")

        # Score them
        scored = await self._keyword_scorer.score_batch(trending)

        if not scored:
            return trending[0].keyword

        # Find highest scored keyword not already published
        for kw_score in scored:
            if not await self._is_duplicate_keyword(kw_score.keyword):
                await self._save_keyword_record(kw_score)
                return kw_score.keyword

        return scored[0].keyword

    async def _is_duplicate(self, keyword: str) -> bool:
        """Check both local DB and WordPress for duplicates."""
        # Check local database
        from sqlalchemy import select
        stmt = select(ArticleRecord).where(ArticleRecord.keyword == keyword)
        result = await self._db.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            return True

        # Check WordPress via slug
        from slugify import slugify
        slug = slugify(keyword)
        return await self._wp_client.check_duplicate(slug)

    async def _is_duplicate_keyword(self, keyword: str) -> bool:
        """Quick check - only local DB."""
        from sqlalchemy import select
        stmt = select(ArticleRecord).where(ArticleRecord.keyword == keyword)
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none() is not None

    def _determine_category(self, keyword: str) -> str:
        """Map keyword to WordPress category."""
        keyword_lower = keyword.lower()
        category_map = {
            "ac": "AC & Pendingin Ruangan",
            "kulkas": "Kulkas & Freezer",
            "freezer": "Kulkas & Freezer",
            "mesin cuci": "Mesin Cuci",
            "water heater": "Water Heater",
            "dispenser": "Dispenser & Air Minum",
            "showcase": "Showcase & Display",
            "hemat listrik": "Tips Hemat Listrik",
            "kode error": "Kode Error & Troubleshooting",
            "troubleshooting": "Kode Error & Troubleshooting",
            "cara merawat": "Tips Perawatan",
            "perbandingan": "Review & Perbandingan",
        }
        for key, category in category_map.items():
            if key in keyword_lower:
                return category
        return "Elektronik Rumah Tangga"

    def _extract_tags(self, keyword: str, article: ArticleContent) -> list[str]:
        """Extract relevant tags from keyword and article content."""
        tags = [keyword]
        # Add focus keyword words as individual tags
        for word in article.focus_keyword.split():
            if len(word) > 3:
                tags.append(word)
        # Add niche tags
        tags.extend(["elektronik", "rumah tangga", "tips hemat"])
        return list(set(tags))[:8]

    async def _save_article_record(
        self,
        article: ArticleContent,
        wp_post,
        thumbnail_source: str,
        thumbnail_url: str = "",
    ) -> None:
        """Save article record to local database."""
        record = ArticleRecord(
            keyword=article.focus_keyword,
            slug=article.slug,
            title=article.seo_title,
            wp_post_id=wp_post.wp_post_id,
            wp_url=wp_post.url,
            status="draft",
            word_count=article.word_count,
            thumbnail_source=thumbnail_source,
            thumbnail_url=thumbnail_url,
        )
        self._db.add(record)

    async def _save_keyword_record(self, score: KeywordScore) -> None:
        """Save keyword score to database for analytics."""
        record = KeywordRecord(
            keyword=score.keyword,
            total_score=score.total_score,
            search_volume_score=score.search_volume_score,
            search_intent_score=score.search_intent_score,
            evergreen_score=score.evergreen_score,
            commercial_value_score=score.commercial_value_score,
            competition_score=score.competition_score,
            relevance_score=score.relevance_score,
            source=score.source,
        )
        self._db.add(record)

    async def _update_progress(self, record: PipelineRunRecord, step: str) -> None:
        """Update pipeline run progress step."""
        record.progress_step = step
        await self._db.commit()
        logger.debug("Pipeline step", step=step)
