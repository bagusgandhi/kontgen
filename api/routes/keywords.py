"""Keywords management and research API routes."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel
from typing import Optional
import structlog

from services.database import get_db, KeywordRecord
from core.models import TrendingKeyword

logger = structlog.get_logger(__name__)
router = APIRouter()


class ResearchRequest(BaseModel):
    limit: int = 20


class ScoreRequest(BaseModel):
    keyword: str


@router.post("/research", summary="Research trending keywords")
async def research_keywords(
    request: ResearchRequest,
    db: AsyncSession = Depends(get_db),
):
    """Research trending keywords from all configured sources."""
    from services.trend_research.researcher import TrendResearcher
    researcher = TrendResearcher()
    keywords = await researcher.research(limit=request.limit)
    return {
        "count": len(keywords),
        "keywords": [{"keyword": k.keyword, "source": k.source} for k in keywords],
    }


@router.post("/score", summary="Score a keyword")
async def score_keyword(
    request: ScoreRequest,
    db: AsyncSession = Depends(get_db),
):
    """Score a specific keyword using GPT-4o Mini."""
    from services.keyword_scoring.scorer import KeywordScorer
    scorer = KeywordScorer()
    kw = TrendingKeyword(keyword=request.keyword, source="manual")
    score = await scorer.score(kw)
    return score


@router.get("/", summary="List scored keywords")
async def list_keywords(
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List all researched and scored keywords."""
    stmt = (
        select(KeywordRecord)
        .order_by(desc(KeywordRecord.total_score))
        .limit(limit)
    )
    result = await db.execute(stmt)
    records = result.scalars().all()
    return {
        "count": len(records),
        "keywords": [
            {
                "keyword": r.keyword,
                "total_score": r.total_score,
                "source": r.source,
                "used": r.used,
                "created_at": r.created_at,
            }
            for r in records
        ],
    }
