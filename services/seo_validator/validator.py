"""
SEO Validator Service
Validates generated articles against SEO and GEO (Generative Engine Optimization)
criteria before publishing.
"""

import re
from collections import Counter
import structlog

from core.models import ArticleContent, SEOValidationResult

logger = structlog.get_logger(__name__)

# GEO quality signals
GEO_SIGNALS = [
    r"\b(adalah|merupakan|didefinisikan sebagai|artinya)\b",  # definition patterns
    r"\b(berdasarkan|menurut|sesuai dengan)\b",               # citation patterns
    r"\b(pertama|kedua|ketiga|langkah \d+)\b",                # structured steps
    r"\b(\d+%|\d+ persen)\b",                                 # statistics
    r"\b(kesimpulan|ringkasan|intinya)\b",                    # summary signals
]


class SEOValidator:
    """
    Validates article content for:
    - Keyword density (target: 1-2%)
    - Heading structure (H1 → H2 → H3)
    - Readability (syllable-based approximation)
    - Duplicate headings
    - AI/GEO-friendly signals
    - Minimum word count
    """

    def validate(self, article: ArticleContent) -> SEOValidationResult:
        """Run all SEO checks and return validation result."""
        logger.info("Validating SEO", title=article.seo_title)

        issues: list[str] = []
        suggestions: list[str] = []

        # Extract plain text from HTML
        plain_text = self._strip_html(article.body_html)
        full_text = f"{article.h1} {plain_text} {article.excerpt}"
        words = full_text.lower().split()
        word_count = len(words)

        # 1. Word count check
        if word_count < 1800:
            issues.append(f"Article too short: {word_count} words (minimum 1800)")
        elif word_count > 2500:
            suggestions.append(f"Article is {word_count} words, consider trimming to 1800-2500")

        # 2. Keyword density
        keyword_density = self._calculate_keyword_density(
            article.focus_keyword, words
        )
        if keyword_density < 0.5:
            issues.append(
                f"Keyword density too low: {keyword_density:.2f}% "
                f"(keyword: {article.focus_keyword})"
            )
            suggestions.append("Add focus keyword naturally in more paragraphs")
        elif keyword_density > 3.0:
            issues.append(
                f"Keyword stuffing detected: {keyword_density:.2f}% (max 3%)"
            )
            suggestions.append("Reduce keyword repetition for natural reading")

        # 3. Heading structure
        headings = self._extract_headings(article.body_html)
        heading_ok, heading_issues = self._check_heading_structure(headings, article.h1)
        issues.extend(heading_issues)

        # 4. Duplicate headings
        duplicate_headings = self._find_duplicate_headings(headings)
        if duplicate_headings:
            issues.append(f"Duplicate headings found: {duplicate_headings}")

        # 5. Readability score (Flesch approximation for Indonesian)
        readability = self._estimate_readability(plain_text)
        if readability < 40:
            suggestions.append(
                "Consider shorter sentences for better readability"
            )

        # 6. Meta description length
        meta_len = len(article.meta_description)
        if meta_len < 120:
            issues.append(f"Meta description too short: {meta_len} chars (min 120)")
        elif meta_len > 160:
            issues.append(f"Meta description too long: {meta_len} chars (max 160)")

        # 7. SEO title length
        title_len = len(article.seo_title)
        if title_len < 40:
            suggestions.append(f"SEO title short: {title_len} chars (ideal 50-60)")
        elif title_len > 65:
            issues.append(f"SEO title too long: {title_len} chars (max 60-65)")

        # 8. GEO / AI-friendly check
        geo_friendly = self._check_geo_signals(plain_text)
        if not geo_friendly:
            suggestions.append(
                "Add more factual statements, definitions, or structured data for GEO"
            )

        # 9. FAQ check
        if not article.faq:
            suggestions.append("Add FAQ section to improve AI search visibility")

        # 10. Focus keyword in title
        if article.focus_keyword.lower() not in article.seo_title.lower():
            issues.append("Focus keyword not found in SEO title")

        # 11. Focus keyword in meta description
        if article.focus_keyword.lower() not in article.meta_description.lower():
            suggestions.append("Consider including focus keyword in meta description")

        is_valid = len(issues) == 0

        result = SEOValidationResult(
            is_valid=is_valid,
            keyword_density=keyword_density,
            word_count=word_count,
            heading_structure_ok=heading_ok,
            readability_score=readability,
            duplicate_headings=duplicate_headings,
            geo_friendly=geo_friendly,
            issues=issues,
            suggestions=suggestions,
        )

        logger.info(
            "SEO validation complete",
            is_valid=is_valid,
            word_count=word_count,
            keyword_density=keyword_density,
            issues_count=len(issues),
        )
        return result

    def _strip_html(self, html: str) -> str:
        """Remove HTML tags, return plain text."""
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _calculate_keyword_density(self, keyword: str, words: list[str]) -> float:
        """Calculate keyword density as percentage."""
        if not words or not keyword:
            return 0.0
        keyword_words = keyword.lower().split()
        if len(keyword_words) == 1:
            count = words.count(keyword_words[0])
        else:
            # Multi-word keyword: count phrase occurrences
            text = " ".join(words)
            count = text.count(keyword.lower())
        return round((count / len(words)) * 100, 2)

    def _extract_headings(self, html: str) -> list[tuple[str, str]]:
        """Extract (tag, text) pairs for all headings."""
        pattern = r"<(h[1-6])[^>]*>(.*?)</h[1-6]>"
        matches = re.findall(pattern, html, re.IGNORECASE | re.DOTALL)
        return [(tag.lower(), re.sub(r"<[^>]+>", "", text).strip())
                for tag, text in matches]

    def _check_heading_structure(
        self, headings: list[tuple[str, str]], h1: str
    ) -> tuple[bool, list[str]]:
        """Validate heading hierarchy."""
        issues = []
        ok = True

        if not headings:
            issues.append("No H2 or H3 headings found in article body")
            return False, issues

        # Check H2 exists
        h2_count = sum(1 for tag, _ in headings if tag == "h2")
        if h2_count < 2:
            issues.append(f"Too few H2 headings: {h2_count} (recommend at least 3)")
            ok = False

        # Check H3 under H2 (no H3 before first H2)
        seen_h2 = False
        for tag, text in headings:
            if tag == "h2":
                seen_h2 = True
            elif tag == "h3" and not seen_h2:
                issues.append(f"H3 '{text}' appears before any H2 heading")
                ok = False
                break

        return ok, issues

    def _find_duplicate_headings(self, headings: list[tuple[str, str]]) -> list[str]:
        """Find headings with identical text."""
        texts = [text.lower() for _, text in headings]
        counter = Counter(texts)
        return [text for text, count in counter.items() if count > 1]

    def _estimate_readability(self, text: str) -> float:
        """
        Approximate Flesch Reading Ease for Indonesian text.
        Indonesian has different syllable structure; this is a heuristic.
        Returns score 0-100 (higher = easier to read).
        """
        sentences = re.split(r"[.!?]+", text)
        sentences = [s.strip() for s in sentences if s.strip()]
        if not sentences:
            return 50.0

        words = text.split()
        if not words:
            return 50.0

        # Estimate syllables: Indonesian averages ~2.5 syllables per word
        avg_syllables_per_word = 2.5
        avg_words_per_sentence = len(words) / len(sentences)

        # Flesch-Kincaid adapted
        score = 206.835 - (1.015 * avg_words_per_sentence) - (84.6 * avg_syllables_per_word)
        return max(0.0, min(100.0, round(score, 1)))

    def _check_geo_signals(self, text: str) -> bool:
        """Check for GEO (AI Search) friendly patterns."""
        signal_count = 0
        for pattern in GEO_SIGNALS:
            if re.search(pattern, text, re.IGNORECASE):
                signal_count += 1
        return signal_count >= 2
