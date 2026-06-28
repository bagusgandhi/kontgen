"""
Pydantic models (schemas) used across the application.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, HttpUrl


# ─── Keyword Models ────────────────────────────────────────────────────────────

class KeywordScore(BaseModel):
    keyword: str
    search_volume_score: float = Field(ge=0, le=10)
    search_intent_score: float = Field(ge=0, le=10)
    evergreen_score: float = Field(ge=0, le=10)
    commercial_value_score: float = Field(ge=0, le=10)
    competition_score: float = Field(ge=0, le=10)  # inverted: low competition = high score
    relevance_score: float = Field(ge=0, le=10)
    total_score: float = Field(ge=0, le=10)
    source: str = ""
    reasoning: str = ""


class TrendingKeyword(BaseModel):
    keyword: str
    source: str  # google_trends, google_suggest, reddit, etc.
    raw_score: float = 0.0
    related_keywords: list[str] = []


# ─── Article Models ────────────────────────────────────────────────────────────

class ArticleOutline(BaseModel):
    title: str
    focus_keyword: str
    target_audience: str
    main_sections: list[str]
    key_points: list[str]
    faq_questions: list[str]
    image_search_keywords: list[str]

    # Hints dari outline generation — dipakai saat article generation
    # Tidak perlu disimpan ke DB, hanya dipakai dalam satu pipeline run
    model_config = {"extra": "allow"}


class FAQItem(BaseModel):
    question: str
    answer: str


class ArticleContent(BaseModel):
    seo_title: str
    slug: str
    meta_description: str
    excerpt: str
    focus_keyword: str
    h1: str
    body_html: str
    faq: list[FAQItem]
    faq_schema_json: str
    cta: str
    internal_link_suggestions: list[str]
    external_reference_suggestions: list[str]
    image_search_keywords: list[str]
    word_count: int = 0


# ─── SEO Validation Models ─────────────────────────────────────────────────────

class SEOValidationResult(BaseModel):
    is_valid: bool
    keyword_density: float
    word_count: int
    heading_structure_ok: bool
    readability_score: float  # Flesch-like approximation
    duplicate_headings: list[str]
    geo_friendly: bool
    issues: list[str]
    suggestions: list[str]


# ─── Image Models ──────────────────────────────────────────────────────────────

class ImageResult(BaseModel):
    url: str
    photographer: str = ""
    photographer_url: str = ""
    source: str  # unsplash, pexels, pixabay, wikimedia, default
    license: str = "Free to use"
    alt_text: str = ""


class ProcessedImage(BaseModel):
    local_path: str
    width: int
    height: int
    format: str
    size_bytes: int
    source: str


class WordPressMedia(BaseModel):
    media_id: int
    url: str
    title: str


# ─── WordPress Models ──────────────────────────────────────────────────────────

class WordPressPost(BaseModel):
    wp_post_id: int
    title: str
    slug: str
    url: str
    status: str
    featured_media_id: Optional[int] = None


# ─── Pipeline Models ───────────────────────────────────────────────────────────

class PipelineRequest(BaseModel):
    """Manual trigger request for the pipeline."""
    keyword: Optional[str] = None  # If None, auto-research trending keywords
    force: bool = False             # Skip duplicate check
    mode: str = "balanced"          # "balanced" | "golden" — keyword research strategy


class PipelineResult(BaseModel):
    success: bool
    keyword: str
    article_title: str = ""
    wp_post_id: Optional[int] = None
    wp_draft_url: str = ""
    thumbnail_source: str = ""
    word_count: int = 0
    processing_time_seconds: float = 0.0
    error_message: str = ""
    seo_score: float = 0.0
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class PipelineStatus(BaseModel):
    run_id: str
    status: str  # running, completed, failed
    keyword: str = ""
    progress_step: str = ""
    result: Optional[PipelineResult] = None
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
