"""Articles management API routes."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from services.database import get_db, ArticleRecord

router = APIRouter()


@router.get("/", summary="List all articles")
async def list_articles(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str = Query(default="all"),
    db: AsyncSession = Depends(get_db),
):
    """List all articles created by the pipeline."""
    stmt = select(ArticleRecord).order_by(desc(ArticleRecord.created_at)).offset(offset).limit(limit)
    if status != "all":
        stmt = stmt.where(ArticleRecord.status == status)
    result = await db.execute(stmt)
    records = result.scalars().all()

    return {
        "total": len(records),
        "articles": [
            {
                "id": r.id,
                "keyword": r.keyword,
                "title": r.title,
                "slug": r.slug,
                "wp_post_id": r.wp_post_id,
                "wp_url": r.wp_url,
                "status": r.status,
                "word_count": r.word_count,
                "seo_score": r.seo_score,
                "thumbnail_source": r.thumbnail_source,
                "created_at": r.created_at,
            }
            for r in records
        ],
    }


@router.get("/{article_id}", summary="Get article by ID")
async def get_article(article_id: int, db: AsyncSession = Depends(get_db)):
    """Get a specific article record."""
    stmt = select(ArticleRecord).where(ArticleRecord.id == article_id)
    result = await db.execute(stmt)
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Article not found")
    return record


@router.delete("/{article_id}", summary="Delete article record")
async def delete_article(article_id: int, db: AsyncSession = Depends(get_db)):
    """Delete article record from local DB (does not delete from WordPress)."""
    stmt = select(ArticleRecord).where(ArticleRecord.id == article_id)
    result = await db.execute(stmt)
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Article not found")
    await db.delete(record)
    await db.commit()
    return {"message": "Article record deleted", "id": article_id}
