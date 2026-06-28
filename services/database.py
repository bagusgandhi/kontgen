"""
Database setup and session management using SQLAlchemy async.
"""

from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Float, Integer, Boolean, Text, DateTime
import structlog

from core.config import settings

logger = structlog.get_logger(__name__)

# Fix SQLite URL for async
_db_url = settings.DATABASE_URL
if _db_url.startswith("sqlite:///"):
    _db_url = _db_url.replace("sqlite:///", "sqlite+aiosqlite:///")

engine = create_async_engine(
    _db_url,
    echo=settings.APP_ENV == "development",
    connect_args={"check_same_thread": False} if "sqlite" in _db_url else {},
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


class ArticleRecord(Base):
    """Tracks all published/drafted articles to prevent duplicates."""
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    keyword: Mapped[str] = mapped_column(String(255), index=True)
    slug: Mapped[str] = mapped_column(String(300), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(500))
    wp_post_id: Mapped[int] = mapped_column(Integer, nullable=True)
    wp_url: Mapped[str] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="draft")
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    seo_score: Mapped[float] = mapped_column(Float, default=0.0)
    thumbnail_source: Mapped[str] = mapped_column(String(100), default="")
    # Store the image URL used so we can avoid reusing it
    thumbnail_url: Mapped[str] = mapped_column(String(2000), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class KeywordRecord(Base):
    """Tracks keyword research history and scores."""
    __tablename__ = "keywords"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    keyword: Mapped[str] = mapped_column(String(255), index=True)
    total_score: Mapped[float] = mapped_column(Float, default=0.0)
    search_volume_score: Mapped[float] = mapped_column(Float, default=0.0)
    search_intent_score: Mapped[float] = mapped_column(Float, default=0.0)
    evergreen_score: Mapped[float] = mapped_column(Float, default=0.0)
    commercial_value_score: Mapped[float] = mapped_column(Float, default=0.0)
    competition_score: Mapped[float] = mapped_column(Float, default=0.0)
    relevance_score: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(String(100), default="")
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PipelineRunRecord(Base):
    """Tracks each pipeline run for monitoring."""
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    keyword: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(50), default="running")
    progress_step: Mapped[str] = mapped_column(String(200), default="")
    article_title: Mapped[str] = mapped_column(String(500), default="")
    wp_post_id: Mapped[int] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str] = mapped_column(Text, default="")
    processing_time_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)


class UsedImageRecord(Base):
    """
    Tracks every image URL that has been used as a thumbnail.
    Used by ImageProviderFactory to skip already-used images
    and ensure variety across articles with similar keywords.
    """
    __tablename__ = "used_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Normalized URL for dedup (strip query params)
    url_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    url: Mapped[str] = mapped_column(String(2000))
    source: Mapped[str] = mapped_column(String(50), default="")      # unsplash/pexels/etc
    keyword: Mapped[str] = mapped_column(String(255), default="")    # keyword used to find it
    used_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


async def init_db() -> None:
    """Create all tables if they don't exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database initialized")


async def get_db() -> AsyncSession:
    """Dependency injection for database sessions."""
    async with AsyncSessionLocal() as session:
        yield session
