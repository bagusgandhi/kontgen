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


TITLE_STYLE_GUIDE = """
PANDUAN JUDUL — WAJIB DIBACA SEBELUM MEMBUAT JUDUL:

❌ HINDARI pola judul yang flat dan generik:
  - "Cara Merawat AC Split dengan Benar"
  - "Panduan Lengkap Memilih Kulkas 2 Pintu"
  - "Tips Hemat Listrik untuk Rumah Tangga"
  - "Mengenal Kode Error Mesin Cuci"
  - "Panduan Memilih Water Heater Terbaik"

✅ GUNAKAN pola judul yang human, engaging, dan curiosity-driven:

  Pola 1 — NUMBER + BENEFIT (listicle):
    "7 Alasan AC Kamu Boros Listrik (dan Cara Mengatasinya)"
    "5 Tanda Kulkas Mulai Rusak yang Sering Diabaikan"
    "3 Kesalahan Fatal Saat Mencuci yang Merusak Mesin Cuci"

  Pola 2 — PROBLEM/PAIN POINT:
    "AC Tidak Dingin Padahal Baru Diservice? Ini Penyebabnya"
    "Kenapa Tagihan Listrik Tiba-Tiba Naik 2x Lipat?"
    "Kulkas Berembun Terus? Jangan Dulu Panggil Teknisi"

  Pola 3 — SURPRISING FACT / MYTH BUSTING:
    "Ternyata Mencuci Pakaian Jam 9 Malam Lebih Hemat Listrik"
    "Salah Kaprah Soal Freon AC yang Masih Dipercaya Banyak Orang"
    "Bukan Kompressornya yang Rusak — Ini yang Sebenarnya Terjadi"

  Pola 4 — DIRECT ANSWER (untuk question keyword):
    "Freezer Tidak Beku? Ini 6 Penyebab Paling Umum"
    "Berapa Watt Sebenarnya AC 1 PK? Ini Hitungan Pastinya"
    "Mana yang Lebih Hemat: AC Inverter atau Non-Inverter?"

  Pola 5 — STORY / SCENARIO:
    "Saya Matikan AC Tiap Malam, Ternyata Ini yang Terjadi pada Tagihan Listrik"
    "Dispenser Bocor Tiba-Tiba — Ini yang Harus Dilakukan Dalam 10 Menit"

  Pola 6 — SPECIFIC + ACTIONABLE:
    "Cara Membersihkan Filter AC Sharp tanpa Bongkar Unit (5 Menit)"
    "Setting Suhu Kulkas yang Tepat agar Sayuran Tahan 2 Minggu"
    "Kode E4 di Mesin Cuci LG? Reset dalam 3 Langkah Ini"

ATURAN TAMBAHAN:
- Judul harus spesifik, bukan generik
- Boleh pakai tanda tanya, tanda seru, atau tanda kurung untuk emphasis
- Masukkan angka jika relevan (lebih menarik dari kata "beberapa" atau "banyak")
- Hindari kata "Lengkap", "Terlengkap", "Terbaik" tanpa konteks spesifik
- Maksimal 65 karakter untuk SEO title, tapi H1 boleh lebih panjang
"""

OUTLINE_PROMPT = """
Anda adalah Content Strategist senior spesialis elektronik rumah tangga Indonesia.
Anda menulis untuk media digital seperti Kompas Tekno, IDN Times Tech, dan Cekaja.

Buat outline artikel untuk keyword: "{keyword}"

Target pembaca: Pemilik rumah Indonesia usia 25-45 tahun yang ingin solusi praktis,
bukan sekadar teori. Mereka punya masalah nyata dan butuh jawaban cepat.

{title_guide}

Panjang artikel target: {min_words}-{max_words} kata.

Return ONLY valid JSON:
{{
  "title": "<judul H1 engaging, human, curiosity-driven — BUKAN pola Cara/Panduan/Tips>",
  "seo_title": "<SEO title 50-60 karakter — boleh berbeda dari H1, harus ada keyword>",
  "focus_keyword": "<focus keyword utama>",
  "target_audience": "<deskripsi target pembaca>",
  "article_angle": "<sudut pandang unik artikel ini — problem solving/myth busting/listicle/etc>",
  "main_sections": ["<section 1>", "<section 2>", "<section 3>", "<section 4>", "<section 5>"],
  "key_points": ["<point penting 1>", "<point penting 2>", "<point penting 3>"],
  "faq_questions": ["<pertanyaan FAQ 1>", "<pertanyaan FAQ 2>", "<pertanyaan FAQ 3>", "<pertanyaan FAQ 4>", "<pertanyaan FAQ 5>"],
  "image_search_keywords": ["<keyword gambar bahasa Inggris 1>", "<keyword gambar bahasa Inggris 2>", "<keyword gambar bahasa Inggris 3>"]
}}
"""

ARTICLE_PROMPT = """
Anda adalah content writer senior untuk media digital Indonesia.
Gaya menulis Anda: conversational, relatable, langsung ke poin — seperti IDN Times,
Kompas Tekno, atau Tirto.id. Bukan buku teks atau manual produk.

Tugas: Tulis artikel lengkap berdasarkan outline berikut.

Keyword Utama: {keyword}
Judul: {title}
Sudut Pandang: {angle}
Seksi yang harus dibahas: {sections}
Target Kata: {min_words}-{max_words} kata

══════════════════════════════════════════
PANDUAN HEADING — WAJIB DIIKUTI:
══════════════════════════════════════════

❌ DILARANG memasukkan nomor urut di heading:
  SALAH: <h2>1. Penyebab AC Tidak Dingin</h2>
  SALAH: <h2>2. Cara Mengecek Freon</h2>
  SALAH: <h3>1.1 Freon Habis</h3>

✅ Heading harus bersih tanpa nomor, tapi tetap deskriptif:
  BENAR: <h2>Penyebab AC Tidak Dingin yang Paling Sering Terjadi</h2>
  BENAR: <h2>Cara Mengecek Freon Sendiri di Rumah</h2>
  BENAR: <h3>Freon Habis: Tanda dan Solusinya</h3>

Heading boleh pakai tanda tanya, tanda seru, atau angka di DALAM teks
(bukan nomor urut):
  BENAR: <h2>Kenapa AC Tetap Tidak Dingin Setelah Dicuci?</h2>
  BENAR: <h2>5 Tanda Freon AC Kamu Sudah Habis</h2>

══════════════════════════════════════════
PANDUAN TONE & VOICE:
══════════════════════════════════════════
- Sapa pembaca dengan "kamu" bukan "Anda"
- Kalimat pembuka HARUS langsung ke pain point — bukan definisi atau latar belakang
  CONTOH BAGUS: "Tagihan listrik bulan ini naik drastis padahal tidak ada alat baru?"
  CONTOH BURUK: "Artikel ini akan membahas tentang cara menghemat listrik rumah tangga."
- Gunakan pertanyaan retoris untuk engage: "Pernah nggak sih kamu..."
- Boleh pakai kata informal secukupnya: "nggak", "nih", "lho", "banget", "sih"
- Gunakan analogi sehari-hari untuk konsep teknis

══════════════════════════════════════════
PANDUAN STRUKTUR KONTEN:
══════════════════════════════════════════
- Paragraf pembuka: 2-3 kalimat, langsung masuk ke masalah/skenario relatable
- Setiap H2 section: kalimat pertama harus ada hook atau konteks
- Gunakan <ul> atau <ol> untuk langkah-langkah atau daftar praktis
- Sisipkan 1-2 callout dalam format:
    <div class="pro-tip"><strong>Pro Tip:</strong> isi tips singkat di sini</div>
  atau
    <div class="perhatian"><strong>Perhatian:</strong> isi peringatan di sini</div>
- Penutup artikel: ringkasan 2-3 kalimat + CTA natural (bukan hard sell)

══════════════════════════════════════════
PANDUAN KONTEN:
══════════════════════════════════════════
- Keyword density 1-2%, sisipkan secara natural
- Sertakan angka spesifik jika relevan (watt, suhu, harga estimasi, durasi)
- Sebutkan merk populer Indonesia jika relevan (Sharp, Panasonic, LG, Daikin, Aqua, Polytron, Samsung)
- Hindari kalimat pasif berlebihan
- Hindari pengulangan kata "sangat", "amat", "sekali"
- GEO: sisipkan kalimat definisi langsung ("X adalah..."), jawab pertanyaan di awal section

Format output: HTML (hanya body content, tanpa tag html/body/head)

Return ONLY valid JSON:
{{
  "seo_title": "<SEO title 50-60 karakter, ada keyword, engaging>",
  "slug": "<url-friendly-slug>",
  "meta_description": "<150-160 karakter, ada keyword, pancing klik>",
  "excerpt": "<2-3 kalimat preview yang menarik pembaca untuk lanjut baca>",
  "focus_keyword": "<focus keyword>",
  "h1": "<H1 — sama dengan title dari outline, engaging dan human>",
  "body_html": "<full article HTML content — TANPA nomor urut di heading>",
  "faq": [
    {{"question": "<pertanyaan natural yang orang benar-benar tanyakan>", "answer": "<jawaban langsung dan praktis>"}},
    {{"question": "...", "answer": "..."}},
    {{"question": "...", "answer": "..."}},
    {{"question": "...", "answer": "..."}},
    {{"question": "...", "answer": "..."}}
  ],
  "cta": "<CTA natural — ajak share/comment/coba tips, bukan hard sell>",
  "internal_link_suggestions": ["<topik terkait 1>", "<topik terkait 2>", "<topik terkait 3>"],
  "external_reference_suggestions": ["<referensi terpercaya 1>", "<referensi terpercaya 2>"],
  "image_search_keywords": ["<english keyword 1>", "<english keyword 2>", "<english keyword 3>"]
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
        """Step 1: Generate article outline with engaging, human title."""
        logger.info("Generating article outline", keyword=keyword)

        prompt = OUTLINE_PROMPT.format(
            keyword=keyword,
            title_guide=TITLE_STYLE_GUIDE,
            min_words=settings.ARTICLE_MIN_WORDS,
            max_words=settings.ARTICLE_MAX_WORDS,
        )

        try:
            response = await self._client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.85,  # Lebih tinggi = lebih kreatif untuk judul
                max_tokens=1200,
                response_format={"type": "json_object"},
            )

            data = json.loads(response.choices[0].message.content)

            # Ambil seo_title dari outline jika ada (outline sekarang generate keduanya)
            outline = ArticleOutline(
                title=data.get("title", ""),
                focus_keyword=data.get("focus_keyword", keyword),
                target_audience=data.get("target_audience", ""),
                main_sections=data.get("main_sections", []),
                key_points=data.get("key_points", []),
                faq_questions=data.get("faq_questions", []),
                image_search_keywords=data.get("image_search_keywords", []),
            )
            # Simpan seo_title dan angle dari outline untuk dipakai di article generation
            outline._seo_title_hint = data.get("seo_title", "")
            outline._article_angle = data.get("article_angle", "problem solving")

            logger.info("Outline generated", title=outline.title, angle=outline._article_angle)
            return outline

        except Exception as e:
            raise ContentGenerationError(f"Outline generation failed: {e}") from e

    async def generate_article(
        self, keyword: str, outline: ArticleOutline
    ) -> ArticleContent:
        """Step 2: Generate full article with human, conversational tone."""
        logger.info("Generating full article", keyword=keyword, title=outline.title)

        # Ambil angle dari outline jika ada, fallback ke default
        angle = getattr(outline, "_article_angle", "problem solving")

        prompt = ARTICLE_PROMPT.format(
            keyword=keyword,
            title=outline.title,
            angle=angle,
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

            # ── Post-processing: strip nomor urut dari heading ──────────────
            body_html = self._clean_heading_numbers(data.get("body_html", ""))
            h1 = self._clean_heading_numbers(data.get("h1", outline.title))

            # Build FAQ items
            faq_items = [FAQItem(**item) for item in data.get("faq", [])]

            # Generate JSON-LD FAQ Schema
            faq_schema = self._build_faq_schema(faq_items)

            # Count words in body
            body_text = re.sub(r"<[^>]+>", " ", body_html)
            word_count = len(body_text.split())

            # Auto-generate slug if not provided
            slug = data.get("slug") or slugify(data.get("seo_title", keyword))

            article = ArticleContent(
                seo_title=data.get("seo_title", outline.title),
                slug=slug,
                meta_description=data.get("meta_description", ""),
                excerpt=data.get("excerpt", ""),
                focus_keyword=data.get("focus_keyword", keyword),
                h1=h1,
                body_html=body_html,
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

    def _clean_heading_numbers(self, html: str) -> str:
        """
        Strip nomor urut dari heading yang kadang masih dihasilkan GPT.

        Pola yang dihapus:
          <h2>1. Judul</h2>       → <h2>Judul</h2>
          <h2>2. Judul</h2>       → <h2>Judul</h2>
          <h3>1.1 Sub Judul</h3>  → <h3>Sub Judul</h3>
          <h2>Langkah 1: Judul</h2> → <h2>Judul</h2>  (hanya jika prefix)

        Angka di TENGAH atau AKHIR heading dibiarkan:
          <h2>5 Tanda Freon Habis</h2>   → tetap (angka bukan nomor urut)
          <h2>AC 1 PK vs 2 PK</h2>       → tetap
        """
        def strip_prefix_number(match: re.Match) -> str:
            tag = match.group(1)      # e.g. "h2"
            content = match.group(2)  # e.g. "1. Judul Section"
            attrs = match.group(3)    # e.g. "" or ' class="..."'

            # Pattern 1: "1. Teks" atau "1) Teks" di awal
            content = re.sub(r"^\d+[\.\)]\s+", "", content)
            # Pattern 2: "1.1 Teks" atau "1.2.3 Teks"
            content = re.sub(r"^\d+(\.\d+)+\s+", "", content)
            # Pattern 3: "Langkah 1: Teks" atau "Langkah 1 -" di awal
            content = re.sub(r"^Langkah\s+\d+\s*[:\-]\s*", "", content, flags=re.IGNORECASE)
            # Pattern 4: "Bagian 1:" atau "Poin 1:" di awal
            content = re.sub(r"^(Bagian|Poin|Bab|Part)\s+\d+\s*[:\-]\s*", "", content, flags=re.IGNORECASE)

            return f"<{tag}{attrs}>{content.strip()}</{tag}>"

        # Match semua heading h1-h6, termasuk yang punya attributes
        pattern = r"<(h[1-6])([^>]*)>(.*?)</h[1-6]>"
        cleaned = re.sub(pattern, strip_prefix_number, html, flags=re.IGNORECASE | re.DOTALL)

        if cleaned != html:
            logger.debug("Heading numbers stripped from article HTML")

        return cleaned

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
