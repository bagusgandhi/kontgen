"""
Integration tests for Pipeline API endpoints.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime
from core.models import PipelineResult


@pytest.mark.asyncio
async def test_health_check(client):
    response = await client.get("/health/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "AutoBlog Generator"


@pytest.mark.asyncio
async def test_pipeline_run_with_mocked_services(client):
    """Test pipeline API endpoint with all services mocked."""
    mock_result = PipelineResult(
        success=True,
        keyword="cara merawat AC",
        article_title="Cara Merawat AC Split Inverter",
        wp_post_id=123,
        wp_draft_url="https://example.com/?p=123",
        thumbnail_source="unsplash",
        word_count=2000,
        processing_time_seconds=15.5,
        seo_score=7.5,
        timestamp=datetime.utcnow(),
    )

    with patch(
        "api.routes.pipeline.PipelineOrchestrator"
    ) as MockOrchestrator:
        mock_instance = AsyncMock()
        mock_instance.run = AsyncMock(return_value=mock_result)
        MockOrchestrator.return_value = mock_instance

        response = await client.post(
            "/api/v1/pipeline/run",
            json={"keyword": "cara merawat AC", "force": False},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["keyword"] == "cara merawat AC"
    assert data["wp_post_id"] == 123


@pytest.mark.asyncio
async def test_pipeline_run_without_keyword(client):
    """Test pipeline auto-research when no keyword provided."""
    mock_result = PipelineResult(
        success=True,
        keyword="kulkas 2 pintu inverter",
        article_title="Review Kulkas 2 Pintu Inverter Terbaik 2024",
        wp_post_id=456,
        wp_draft_url="https://example.com/?p=456",
        thumbnail_source="pexels",
        word_count=2100,
        processing_time_seconds=18.0,
        timestamp=datetime.utcnow(),
    )

    with patch(
        "api.routes.pipeline.PipelineOrchestrator"
    ) as MockOrchestrator:
        mock_instance = AsyncMock()
        mock_instance.run = AsyncMock(return_value=mock_result)
        MockOrchestrator.return_value = mock_instance

        response = await client.post(
            "/api/v1/pipeline/run",
            json={},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True


@pytest.mark.asyncio
async def test_pipeline_history_empty(client):
    response = await client.get("/api/v1/pipeline/history")
    assert response.status_code == 200
    data = response.json()
    assert data == []


@pytest.mark.asyncio
async def test_articles_list_empty(client):
    response = await client.get("/api/v1/articles/")
    assert response.status_code == 200
    data = response.json()
    assert data["articles"] == []


@pytest.mark.asyncio
async def test_keywords_research_endpoint(client):
    with patch(
        "api.routes.keywords.TrendResearcher"
    ) as MockResearcher:
        from core.models import TrendingKeyword
        mock_instance = AsyncMock()
        mock_instance.research = AsyncMock(
            return_value=[
                TrendingKeyword(keyword="AC split terbaik", source="google_suggest"),
                TrendingKeyword(keyword="cara hemat listrik", source="google_trends"),
            ]
        )
        MockResearcher.return_value = mock_instance

        response = await client.post(
            "/api/v1/keywords/research",
            json={"limit": 10},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 2
