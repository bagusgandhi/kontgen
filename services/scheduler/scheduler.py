"""
Pipeline Scheduler
Standalone scheduler for running pipeline without n8n.
Uses APScheduler with cron expression from environment variable.
Can be used as fallback or for testing.
"""

import asyncio
from datetime import datetime
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from core.config import settings
from core.models import PipelineRequest

logger = structlog.get_logger(__name__)


class PipelineScheduler:
    """
    Standalone scheduler for the AutoBlog pipeline.
    Use when n8n is not available or for local testing.
    """

    def __init__(self):
        self._scheduler = AsyncIOScheduler(timezone=settings.TIMEZONE)
        self._tz = pytz.timezone(settings.TIMEZONE)

    def start(self) -> None:
        """Start the scheduler with configured cron expression."""
        # Parse cron expression: "0 6 * * *" = every day at 6 AM WIB
        cron_parts = settings.SCHEDULER_CRON.split()
        if len(cron_parts) != 5:
            logger.error(
                "Invalid cron expression", cron=settings.SCHEDULER_CRON
            )
            return

        minute, hour, day, month, day_of_week = cron_parts

        self._scheduler.add_job(
            self._run_pipeline,
            CronTrigger(
                minute=minute,
                hour=hour,
                day=day,
                month=month,
                day_of_week=day_of_week,
                timezone=self._tz,
            ),
            id="daily_blog_generation",
            name="Daily Blog Generation",
            replace_existing=True,
        )

        self._scheduler.start()
        logger.info(
            "Scheduler started",
            cron=settings.SCHEDULER_CRON,
            timezone=settings.TIMEZONE,
        )

    def stop(self) -> None:
        """Gracefully stop the scheduler."""
        self._scheduler.shutdown()
        logger.info("Scheduler stopped")

    async def _run_pipeline(self) -> None:
        """Execute the pipeline (called by scheduler)."""
        logger.info("Scheduled pipeline run starting", time=datetime.now(self._tz))

        try:
            # Import here to avoid circular imports
            from services.database import AsyncSessionLocal
            from services.pipeline import PipelineOrchestrator

            async with AsyncSessionLocal() as db:
                orchestrator = PipelineOrchestrator(db_session=db)
                request = PipelineRequest()  # Auto-research keyword
                result = await orchestrator.run(request)

                logger.info(
                    "Scheduled pipeline completed",
                    success=result.success,
                    keyword=result.keyword,
                    time=result.processing_time_seconds,
                )

        except Exception as e:
            logger.error("Scheduled pipeline error", error=str(e), exc_info=True)

    def run_now(self) -> None:
        """Trigger immediate pipeline run (for testing)."""
        asyncio.create_task(self._run_pipeline())
