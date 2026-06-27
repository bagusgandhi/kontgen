"""
AutoBlog Generator - Main FastAPI Application
Entry point for the API server.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import structlog

from services.database import init_db
from api.routes import pipeline, health, articles, keywords
from core.config import settings
from core.logging import configure_logging

configure_logging()
logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    logger.info("AutoBlog Generator starting up", env=settings.APP_ENV)
    await init_db()
    yield
    logger.info("AutoBlog Generator shutting down")


app = FastAPI(
    title="AutoBlog Generator API",
    description="""
    Automated blog content generation pipeline for WordPress.
    
    Workflow:
    1. Research trending keywords in electronics niche
    2. Score and rank keywords
    3. Generate SEO & GEO friendly articles using GPT-4o Mini
    4. Find legal thumbnail images
    5. Process and overlay images
    6. Publish draft to WordPress
    7. Send Telegram notification
    """,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routes
app.include_router(health.router, prefix="/health", tags=["Health"])
app.include_router(pipeline.router, prefix="/api/v1/pipeline", tags=["Pipeline"])
app.include_router(articles.router, prefix="/api/v1/articles", tags=["Articles"])
app.include_router(keywords.router, prefix="/api/v1/keywords", tags=["Keywords"])
