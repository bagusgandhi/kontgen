"""
Application configuration using Pydantic Settings.
All settings are loaded from environment variables.
"""

from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    APP_ENV: Literal["development", "staging", "production"] = "development"
    LOG_LEVEL: str = "INFO"

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/autoblog.db"

    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_BASE_URL: str = ""  # Leave empty to use default https://api.openai.com/v1
    OPENAI_MAX_TOKENS: int = 4096
    OPENAI_TEMPERATURE: float = 0.7

    # WordPress
    WORDPRESS_URL: str = ""
    WORDPRESS_USERNAME: str = ""
    WORDPRESS_APP_PASSWORD: str = ""
    WORDPRESS_DEFAULT_CATEGORY_ID: int = 1
    WORDPRESS_DEFAULT_STATUS: str = "draft"

    # Image Provider
    IMAGE_PROVIDER: Literal["unsplash", "pexels", "pixabay", "wikimedia"] = "unsplash"
    UNSPLASH_ACCESS_KEY: str = ""
    PEXELS_API_KEY: str = ""
    PIXABAY_API_KEY: str = ""

    # Image Processing
    THUMBNAIL_WIDTH: int = 1200
    THUMBNAIL_HEIGHT: int = 630
    DEFAULT_THUMBNAIL_PATH: str = "/app/assets/default_thumbnail.webp"
    COMPANY_LOGO_PATH: str = "/app/assets/logo.png"

    # Telegram
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Scheduler
    SCHEDULER_CRON: str = "0 6 * * *"
    TIMEZONE: str = "Asia/Jakarta"

    # Article Generation
    ARTICLE_MIN_WORDS: int = 1800
    ARTICLE_MAX_WORDS: int = 2500
    ARTICLES_PER_RUN: int = 1

    # Keyword Scoring Weights (must sum to 1.0)
    SCORE_WEIGHT_SEARCH_VOLUME: float = 0.25
    SCORE_WEIGHT_SEARCH_INTENT: float = 0.20
    SCORE_WEIGHT_EVERGREEN: float = 0.15
    SCORE_WEIGHT_COMMERCIAL: float = 0.20
    SCORE_WEIGHT_COMPETITION: float = 0.10
    SCORE_WEIGHT_RELEVANCE: float = 0.10

    # Retry settings
    RETRY_MAX_ATTEMPTS: int = 3
    RETRY_WAIT_SECONDS: int = 2

    # Temp directory for image processing
    TEMP_DIR: str = "/app/temp"

    # Target niche keywords (comma separated)
    NICHE_KEYWORDS: str = (
        "AC,kulkas,mesin cuci,freezer,showcase,water heater,dispenser,"
        "hemat listrik,merawat elektronik,kode error,troubleshooting,perbandingan produk"
    )

    @property
    def niche_keyword_list(self) -> list[str]:
        return [k.strip() for k in self.NICHE_KEYWORDS.split(",")]


settings = Settings()
