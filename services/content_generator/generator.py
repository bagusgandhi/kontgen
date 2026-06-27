"""
Content Generator Service
Generates SEO & GEO friendly articles using GPT-4o Mini.
Output: full article with all SEO metadata, FAQ, JSON-LD schema, CTA.
"""

import json
import re
from typing import Optional
import structlog
from openai import AsyncOpenAI
from slugify import slugify

from core.config import settings
from core.exceptions import ContentGenerationError
from core.models import ArticleOutline, ArticleContent, FAQItem
from core.openai_client import create_openai_client

logger = structlog.get_logger(__name__)


OUTLINE_PROMPT = """
Anda adalah SEO Content Strategist spesialis elektronik rumah tangga Indonesia.

Buat outline artikel untuk keyword: "{keyword}"

Target pembaca: Rumah tangga Indonesia yang mencari informasi elektronik.
Panjang artikel target: {min_words}-{max_words} kata.

Return ONLY valid JSON:
{{
  "title": "<judul artikel menarik dan SEO friendly>",
  "focus_keyword": "<focus keyword utama>",
  "target_audience": "<deskripsi target pembaca>",
  "main_sections": ["<section 1>", "<section 2>", "<section 3>", "<section 4>", "<section 5>"],
  "key_points": ["<point penting 1>", "<point penting 2>", "<point penting 3>"],
  "faq_questions": ["<pertanyaan FAQ 1>", "<pertanyaan FAQ 2>", "<pertanyaan FAQ 3>", "<pertanyaan FAQ 4>", "<pertanyaan FAQ 5>"],
  "image_search_keywords": ["<keyword gambar bahasa Inggris 1>", "<keyword gambar bahasa Inggris 2>", "<keyword gambar bahasa Inggris 3>"]
}}
"""

ARTICLE_PROMPT = """
Anda adalah penulis konten SEO profesional untuk blog elektronik rumah tangga Indonesia.

Tugas: Tulis artikel lengkap berdasarkan outline berikut.

Keyword Utama: {keyword}
Judul: {title}
Seksi Utama: {sections}
Target Kata: {min_words}-{max_words} kata

PANDUAN PENULISAN:
- Tulis dalam Bahasa Indonesia yang natural dan mudah dipahami
- Keyword density 1-2% (jangan keyword stuffing)
- Gunakan H2 untuk seksi utama, H3 untuk sub-seksi
- Sertakan data, fakta, atau tips praktis
- Tulis untuk manusia, bukan mesin (natural language)
- Sertakan transisi yang smooth antar paragraf
- CTA yang menarik di akhir artikel
- Format dalam HTML (hanya body content, tanpa <html><body> tags)

GEO (Generative Engine Optimization) REQUIREMENTS:
- Gunakan kalimat faktual yang dapat dikutip AI
- Struktur jawaban langsung untuk pertanyaan umum
- Definisikan istilah teknis dengan jelas
- Gunakan list dan tabel untuk informasi terstruktur

Return ONLY valid JSON dengan format berikut:
{{
  "seo_title": "<SEO title 50-60 karakter>",
  "slug": "<url-friendly-slug>",
  "meta_description": "<meta description 150-160 karakter dengan keyword>",
  "excerpt": "<excerpt 2-3 kalimat untuk preview artikel>",
  "focus_keyword": "<focus keyword>",
  "h1": "<H1 heading artikel>",
  "body_html": "<full article HTML content>",
  "faq": [
    {{"question": "<pertanyaan>", "answer": "<jawaban lengkap>"}},
    {{"question": "<pertanyaan>", "answer": "<jawaban lengkap>"}},
    {{"question": "<pertanyaan>", "answer": "<jawaban lengkap>"}},
    {{"question": "<pertanyaan>", "answer": "<jawaban lengkap>"}},
    {{"question": "<pertanyaan>", "answer": "<jawaban lengkap>"}}
  ],
  "cta": "<Call to Action yang menarik>",
  "internal_link_suggestions": ["<topik terkait untuk internal link 1>", "<topik terkait 2>", "<topik terkait 3>"],
  "external_reference_suggestions": ["<referensi eksternal terpercaya 1>", "<referensi eksternal 2>"],
  "image_search_keywords": ["<english keyword for image search 1>", "<english keyword 2>", "<english keyword 3>"]
}}
"""

FAQ_SCHEMA_TEMPLATE = """{{
  "@context": "https://schema.org",
  "@type": "FAQPage",
  "mainEntity": [{faq_items}]
}}"""

FAQ_ITEM_TEMPLATE = """{{
    "@type": "Question",
    "name": "{question}",
    "acceptedAnswer": {{
      "@type": "Answer",
      "text": "{answer}"
    }}
  }}"""


class ContentGenerator:
    """
    Generates complete SEO/GEO-optimized articles using GPT-4o Mini.
    Two-step process: outline → full article.
    """

    def __init__(self, openai_client: Optional[AsyncOpenAI] = None):
        self._client = openai_client or create_openai_client()

    async def generate_outline(self, keyword: str) -> ArticleOutline:
        """Step 1: Generate article outline."""
        logger.info("Generating article outline", keyword=keyword)

        prompt = OUTLINE_PROMPT.format(
            keyword=keyword,
            min_words=settings.ARTICLE_MIN_WORDS,
            max_words=settings.ARTICLE_MAX_WORDS,
        )

        try:
            response = await self._client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=1000,
                response_format={"type": "json_object"},
            )

            data = json.loads(response.choices[0].message.content)
            outline = ArticleOutline(**data)
            logger.info("Outline generated", title=outline.title)
            return outline

        except Exception as e:
            raise ContentGenerationError(f"Outline generation failed: {e}") from e

    async def generate_article(
        self, keyword: str, outline: ArticleOutline
    ) -> ArticleContent:
        """Step 2: Generate full article from outline."""
        logger.info("Generating full article", keyword=keyword, title=outline.title)

        prompt = ARTICLE_PROMPT.format(
            keyword=keyword,
            title=outline.title,
            sections=json.dumps(outline.main_sections, ensure_ascii=False),
            min_words=settings.ARTICLE_MIN_WORDS,
            max_words=settings.ARTICLE_MAX_WORDS,
        )

        try:
            response = await self._client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=settings.OPENAI_TEMPERATURE,
                max_tokens=settings.OPENAI_MAX_TOKENS,
                response_format={"type": "json_object"},
            )

            data = json.loads(response.choices[0].message.content)

            # Build FAQ items
            faq_items = [FAQItem(**item) for item in data.get("faq", [])]

            # Generate JSON-LD FAQ Schema
            faq_schema = self._build_faq_schema(faq_items)

            # Count words in body
            body_text = re.sub(r"<[^>]+>", " ", data.get("body_html", ""))
            word_count = len(body_text.split())

            # Auto-generate slug if not provided
            slug = data.get("slug") or slugify(data.get("seo_title", keyword))

            article = ArticleContent(
                seo_title=data.get("seo_title", outline.title),
                slug=slug,
                meta_description=data.get("meta_description", ""),
                excerpt=data.get("excerpt", ""),
                focus_keyword=data.get("focus_keyword", keyword),
                h1=data.get("h1", outline.title),
                body_html=data.get("body_html", ""),
                faq=faq_items,
                faq_schema_json=faq_schema,
                cta=data.get("cta", ""),
                internal_link_suggestions=data.get("internal_link_suggestions", []),
                external_reference_suggestions=data.get("external_reference_suggestions", []),
                image_search_keywords=data.get(
                    "image_search_keywords", outline.image_search_keywords
                ),
                word_count=word_count,
            )

            logger.info(
                "Article generated",
                title=article.seo_title,
                word_count=article.word_count,
            )
            return article

        except Exception as e:
            raise ContentGenerationError(f"Article generation failed: {e}") from e

    def _build_faq_schema(self, faq_items: list[FAQItem]) -> str:
        """Build JSON-LD FAQ schema for structured data."""
        items = []
        for item in faq_items:
            # Escape special JSON characters in answer
            answer_clean = item.answer.replace('"', '\\"').replace("\n", " ")
            question_clean = item.question.replace('"', '\\"')
            items.append(
                FAQ_ITEM_TEMPLATE.format(
                    question=question_clean,
                    answer=answer_clean,
                )
            )

        schema = FAQ_SCHEMA_TEMPLATE.format(faq_items=",\n  ".join(items))

        # Validate JSON
        try:
            json.loads(schema)
        except json.JSONDecodeError:
            logger.warning("FAQ schema JSON is invalid, returning empty schema")
            return "{}"

        return schema
