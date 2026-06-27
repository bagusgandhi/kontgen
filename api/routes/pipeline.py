"""
Pipeline API Routes
Exposes the blog generation pipeline via REST API.
Called by n8n as the orchestration trigger.
"""

from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional
import structlog

from core.models import PipelineRequest, PipelineResult
from services.database import get_db
from services.pipeline import PipelineOrchestrator

logger = structlog.get_logger(__name__)
router = APIRouter()


class TriggerResponse(BaseModel):
    message: str
    run_id: Optional[str] = None


@router.post("/run", response_model=PipelineResult, summary="Run pipeline synchronously")
async def run_pipeline(
    request: PipelineRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Execute the full blog generation pipeline synchronously.
    
    - If `keyword` is provided, uses that keyword directly.
    - If `keyword` is omitted, auto-researches trending keywords.
    - If `force=true`, skips duplicate check.
    
    **Called by n8n Cron workflow trigger.**
    
    Returns full pipeline result including WordPress post URL.
    """
    logger.info("Pipeline triggered via API", keyword=request.keyword, force=request.force)

    orchestrator = PipelineOrchestrator(db_session=db)
    result = await orchestrator.run(request)

    if not result.success and result.error_message:
        # Don't return 500 for business logic failures - return 200 with failure info
        # n8n will handle the result based on result.success field
        logger.warning("Pipeline completed with failure", error=result.error_message)

    return result


@router.post(
    "/run-async",
    response_model=TriggerResponse,
    summary="Trigger pipeline asynchronously",
)
async def run_pipeline_async(
    request: PipelineRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger pipeline as background task and return immediately.
    Use /status/{run_id} to check progress.
    
    Useful for long-running generations via n8n webhook response.
    """
    import uuid

    run_id = str(uuid.uuid4())

    async def _run():
        from services.database import AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            orchestrator = PipelineOrchestrator(db_session=session)
            await orchestrator.run(request)

    background_tasks.add_task(_run)
    logger.info("Pipeline queued", run_id=run_id)

    return TriggerResponse(
        message="Pipeline queued for execution",
        run_id=run_id,
    )


@router.get("/status/{run_id}", summary="Get pipeline run status")
async def get_pipeline_status(
    run_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get the current status and progress of a pipeline run."""
    from sqlalchemy import select
    from services.database import PipelineRunRecord

    stmt = select(PipelineRunRecord).where(PipelineRunRecord.run_id == run_id)
    result = await db.execute(stmt)
    record = result.scalar_one_or_none()

    if not record:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    return {
        "run_id": record.run_id,
        "status": record.status,
        "keyword": record.keyword,
        "progress_step": record.progress_step,
        "article_title": record.article_title,
        "wp_post_id": record.wp_post_id,
        "error_message": record.error_message,
        "processing_time_seconds": record.processing_time_seconds,
        "started_at": record.started_at,
        "completed_at": record.completed_at,
    }


@router.get("/history", summary="Get recent pipeline runs")
async def get_pipeline_history(
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """Get recent pipeline run history for monitoring."""
    from sqlalchemy import select, desc
    from services.database import PipelineRunRecord

    stmt = (
        select(PipelineRunRecord)
        .order_by(desc(PipelineRunRecord.started_at))
        .limit(limit)
    )
    result = await db.execute(stmt)
    records = result.scalars().all()

    return [
        {
            "run_id": r.run_id,
            "keyword": r.keyword,
            "status": r.status,
            "article_title": r.article_title,
            "wp_post_id": r.wp_post_id,
            "processing_time_seconds": r.processing_time_seconds,
            "started_at": r.started_at,
        }
        for r in records
    ]
