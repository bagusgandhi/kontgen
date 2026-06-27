"""
Tests for SEO Validator Service.
"""

import pytest
from core.models import ArticleContent, FAQItem
from services.seo_validator.validator import SEOValidator


def make_article(**kwargs) -> ArticleContent:
    """Helper to create test article with defaults."""
    defaults = {
        "seo_title": "Cara Merawat AC Split Inverter agar Hemat Listrik",
        "slug": "cara-merawat-ac-split-inverter",
        "meta_description": (
            "Panduan lengkap cara merawat AC split inverter agar awet dan hemat listrik. "
            "Tips dari teknisi berpengalaman untuk rumah tangga Indonesia."
        ),
        "excerpt": "Pelajari cara merawat AC split inverter dengan benar.",
        "focus_keyword": "cara merawat AC",
        "h1": "Cara Merawat AC Split Inverter agar Hemat Listrik",
        "body_html": (
            "<h2>Mengapa Perawatan AC Penting?</h2>"
            "<p>Cara merawat AC yang benar adalah hal yang sangat penting untuk dilakukan "
            "setiap pemilik AC. Berdasarkan penelitian, AC yang terawat dapat menghemat listrik "
            "hingga 30%. Pertama, bersihkan filter setiap 2 minggu. Kedua, cek freon setiap tahun. "
            "Cara merawat AC secara rutin akan membuatnya lebih awet dan efisien. "
            "Kesimpulannya adalah perawatan rutin sangat diperlukan.</p>"
            "<h2>Langkah-Langkah Perawatan AC</h2>"
            "<p>Langkah 1: Matikan AC sebelum membersihkan filter. "
            "Cara merawat AC dimulai dari membersihkan filter secara berkala. "
            "Menurut panduan resmi pabrikan, filter harus dibersihkan minimal setiap bulan. "
            "Cara merawat AC yang efektif membutuhkan konsistensi.</p>"
            "<h3>Membersihkan Filter AC</h3>"
            "<p>Langkah pertama cara merawat AC adalah melepas filter dengan hati-hati.</p>"
            "<h3>Memeriksa Freon</h3>"
            "<p>Freon yang kurang akan menurunkan kinerja AC secara signifikan.</p>"
            "<h2>Tips Hemat Listrik dengan AC</h2>"
            "<p>Cara merawat AC dengan benar juga berarti mengatur suhu yang tepat. "
            "Suhu ideal adalah 24-26 derajat Celsius untuk efisiensi optimal.</p>" * 5
        ),
        "faq": [
            FAQItem(
                question="Berapa kali filter AC harus dibersihkan?",
                answer="Filter AC sebaiknya dibersihkan setiap 1-2 minggu sekali.",
            )
        ],
        "faq_schema_json": "{}",
        "cta": "Hubungi teknisi kami sekarang!",
        "internal_link_suggestions": [],
        "external_reference_suggestions": [],
        "image_search_keywords": ["air conditioner maintenance"],
        "word_count": 1900,
    }
    defaults.update(kwargs)
    return ArticleContent(**defaults)


class TestSEOValidator:
    def setup_method(self):
        self.validator = SEOValidator()

    def test_valid_article_passes(self):
        article = make_article()
        result = self.validator.validate(article)
        # Should have no critical issues (may have suggestions)
        assert result.keyword_density >= 0
        assert result.word_count > 0

    def test_keyword_density_too_low(self):
        article = make_article(
            body_html="<h2>Judul</h2><p>Ini adalah artikel tentang elektronik rumah tangga yang sangat bagus dan informatif untuk semua orang yang ingin tahu lebih banyak tentang elektronik modern.</p>" * 20,
            focus_keyword="cara merawat AC",
        )
        result = self.validator.validate(article)
        assert result.keyword_density < 1.0

    def test_meta_description_too_short(self):
        article = make_article(meta_description="Terlalu pendek.")
        result = self.validator.validate(article)
        assert any("meta description" in issue.lower() for issue in result.issues)

    def test_meta_description_too_long(self):
        article = make_article(
            meta_description="A" * 200
        )
        result = self.validator.validate(article)
        assert any("meta description" in issue.lower() for issue in result.issues)

    def test_missing_focus_keyword_in_title(self):
        article = make_article(
            seo_title="Tips Elektronik Terbaik untuk Anda",
            focus_keyword="cara merawat AC",
        )
        result = self.validator.validate(article)
        assert any("focus keyword" in issue.lower() for issue in result.issues)

    def test_duplicate_headings_detected(self):
        article = make_article(
            body_html=(
                "<h2>Tips Penting</h2><p>content</p>"
                "<h2>Tips Penting</h2><p>content</p>"
            ) * 5
        )
        result = self.validator.validate(article)
        assert len(result.duplicate_headings) > 0

    def test_geo_signals_detected(self):
        """Test that GEO-friendly content is recognized."""
        geo_body = (
            "<h2>Definisi AC</h2>"
            "<p>AC atau Air Conditioner adalah perangkat yang berdasarkan prinsip refrigerasi "
            "berfungsi untuk mendinginkan udara. Menurut standar SNI, efisiensi energi "
            "didefinisikan sebagai perbandingan antara daya pendinginan dengan konsumsi daya. "
            "Pertama, pastikan filter bersih. Kedua, periksa freon. Ketiga, cek kondensasi. "
            "Berdasarkan data ESDM 2023, konsumsi listrik AC mencapai 60% dari total listrik rumah. "
            "Kesimpulannya, perawatan rutin menghemat 30% listrik.</p>"
        ) * 10
        article = make_article(body_html=geo_body)
        result = self.validator.validate(article)
        assert result.geo_friendly is True

    def test_strip_html(self):
        validator = self.validator
        assert validator._strip_html("<p>Hello <b>World</b></p>") == "Hello World"
        assert validator._strip_html("") == ""

    def test_keyword_density_calculation(self):
        words = "cara merawat ac cara merawat ac testing content".split()
        density = self.validator._calculate_keyword_density("cara merawat ac", words)
        assert density > 0

    def test_find_duplicate_headings(self):
        headings = [
            ("h2", "Tips Penting"),
            ("h2", "Cara Kerja AC"),
            ("h2", "Tips Penting"),
        ]
        dupes = self.validator._find_duplicate_headings(headings)
        assert "tips penting" in dupes
