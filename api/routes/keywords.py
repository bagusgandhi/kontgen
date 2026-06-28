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
    mode: str = "balanced"  # "balanced" | "golden"


class ScoreRequest(BaseModel):
    keyword: str


@router.post("/research", summary="Research trending keywords")
async def research_keywords(
    request: ResearchRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Research trending keywords dari semua source termasuk GPT.

    Mode:
    - **balanced**: distribusi merata antar niche (default)
    - **golden**: fokus keyword low-competition, long-tail, question-based
    """
    from sqlalchemy import select as sa_sel
    from services.database import ArticleRecord
    from core.openai_client import create_openai_client

    # Load existing agar GPT tidak duplikat
    stmt = sa_sel(ArticleRecord.keyword)
    result = await db.execute(stmt)
    existing = list(result.scalars().all())

    from services.trend_research.researcher import TrendResearcher
    researcher = TrendResearcher(openai_client=create_openai_client())
    keywords = await researcher.research(
        limit=request.limit,
        mode=request.mode,
        existing_keywords=existing,
    )
    return {
        "mode": request.mode,
        "count": len(keywords),
        "keywords": [
            {
                "keyword": k.keyword,
                "source": k.source,
                "raw_score": k.raw_score,
                "rationale": k.related_keywords[0] if k.related_keywords else "",
            }
            for k in keywords
        ],
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
