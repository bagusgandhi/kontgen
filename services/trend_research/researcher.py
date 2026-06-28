"""
Trend Research Service
Collects and enriches trending keywords from multiple sources:

Source 1 — Google Trends RSS     : real-time trending (Indonesia)
Source 2 — Google Suggest        : autocomplete per niche (1 acak per niche)
Source 3 — Reddit                : community discussions
Source 4 — GPT-4o Mini           : gap analysis + golden keyword generation

Mode:
  - "balanced"  (default) : distribusi merata antar niche
  - "golden"              : fokus cari keyword low-competition + ada search volume
                            (long-tail, question-based, specific model numbers)
"""

import asyncio
import json
import random
import re
from typing import Literal, Optional
from xml.etree import ElementTree

import structlog
from openai import AsyncOpenAI

from core.config import settings
from core.exceptions import KeywordResearchError
from core.models import TrendingKeyword
from core.openai_client import create_openai_client
from services.utils.http_client import AsyncHTTPClient

logger = structlog.get_logger(__name__)

ResearchMode = Literal["balanced", "golden"]

# ─── Seed keywords per niche ──────────────────────────────────────────────────
SEED_KEYWORDS_BY_NICHE: dict[str, list[str]] = {
    "ac":           ["AC split inverter", "cara merawat AC", "kode error AC"],
    "kulkas":       ["kulkas 2 pintu hemat listrik", "kulkas tidak dingin", "kulkas inverter terbaik"],
    "mesin_cuci":   ["mesin cuci front loading", "cara merawat mesin cuci", "mesin cuci error"],
    "freezer":      ["freezer chest murah", "freezer portable", "cara pakai freezer"],
    "showcase":     ["showcase minuman bekas", "showcase buah", "harga showcase"],
    "water_heater": ["water heater solar terbaik", "water heater listrik hemat", "cara pasang water heater"],
    "dispenser":    ["dispenser galon atas bawah", "dispenser air panas dingin", "dispenser murah terbaik"],
    "hemat_listrik":["cara hemat listrik rumah", "tips hemat listrik AC", "listrik rumah boros"],
    "troubleshoot": ["kode error mesin cuci", "kulkas berbunyi keras", "AC tidak dingin penyebab"],
    "review":       ["perbandingan AC terbaik", "rekomendasi kulkas 2024", "review mesin cuci terbaik"],
}

SEED_KEYWORDS_FLAT: list[str] = [
    kw for seeds in SEED_KEYWORDS_BY_NICHE.values() for kw in seeds
]

# ─── GPT Prompts ──────────────────────────────────────────────────────────────

GPT_BALANCED_PROMPT = """
Kamu adalah SEO researcher spesialis elektronik rumah tangga Indonesia.

Tugasmu: Generate keyword IDEAS yang beragam dan belum banyak dibahas di blog Indonesia.

Context:
- Niche: elektronik rumah tangga (AC, kulkas, mesin cuci, freezer, water heater, dispenser, showcase)
- Target: pembaca Indonesia yang ingin beli atau merawat elektronik rumah tangga
- Sudah ada artikel tentang: {existing_keywords}

Buat {count} keyword yang:
1. BERAGAM — tidak boleh lebih dari 2 keyword dari niche yang sama
2. SPECIFIC — bukan keyword generik seperti "AC bagus", tapi seperti "AC Daikin 1/2 PK untuk kamar 3x4"
3. INFORMATIONAL — jawab pertanyaan spesifik pembaca
4. BAHASA INDONESIA — natural, bukan terjemahan kaku
5. BELUM ADA di existing articles di atas

Return JSON array:
[
  {{"keyword": "...", "niche": "...", "rationale": "kenapa ini menarik"}},
  ...
]
"""

GPT_GOLDEN_PROMPT = """
Kamu adalah SEO expert spesialis "golden keyword" untuk blog elektronik Indonesia.

Golden keyword = keyword yang memiliki:
- Search volume: ADA (orang benar-benar mencari ini)
- Kompetisi: RENDAH (sedikit artikel Indonesia yang membahas dengan detail)
- Intent: CLEAR (pembaca tahu apa yang mau mereka pelajari)

Karakteristik golden keyword yang bagus:
- Long-tail (4+ kata): "cara membersihkan filter AC split tanpa teknisi"
- Question-based: "kenapa freezer berembun di dalam"
- Model-specific: "kode error E5 mesin cuci LG front loading"
- Comparison-specific: "perbedaan AC inverter dan non inverter konsumsi listrik"
- Seasonal-specific: "tips AC saat musim hujan bocor air"
- How-to procedural: "langkah-langkah isi freon AC sendiri yang benar"

Niche yang tersedia: {niches}
Keyword yang sudah pernah dibuat: {existing_keywords}

Buat {count} golden keyword yang BELUM ADA di existing list.
Prioritaskan keyword yang:
1. Mengandung angka atau spesifikasi teknis (suhu, watt, PK, liter)
2. Mengandung merk populer Indonesia (Sharp, Panasonic, LG, Samsung, Daikin, Aqua, Polytron)
3. Berupa pertanyaan "kenapa", "cara", "apakah", "berapa"
4. Long-tail 4-7 kata

Return JSON array:
[
  {{
    "keyword": "...",
    "niche": "...",
    "competition_estimate": "low|medium",
    "search_intent": "informational|commercial|navigational",
    "rationale": "kenapa ini golden keyword"
  }},
  ...
]
"""


class TrendResearcher:
    """
    Aggregates trending keyword data dari 4 source.
    Support 2 mode: balanced (default) dan golden (low-competition hunting).
    """

    def __init__(
        self,
        http_client: Optional[AsyncHTTPClient] = None,
        openai_client: Optional[AsyncOpenAI] = None,
    ):
        self._client = http_client
        self._openai = openai_client or create_openai_client()

    async def research(
        self,
        limit: int = 20,
        mode: ResearchMode = "balanced",
        existing_keywords: Optional[list[str]] = None,
    ) -> list[TrendingKeyword]:
        """
        Main entry point.

        Args:
            limit: Jumlah keyword yang dikembalikan.
            mode: "balanced" = merata antar niche, "golden" = fokus low-competition.
            existing_keywords: Keyword yang sudah pernah dibuat artikel — GPT akan
                               menghindari keyword yang sudah ada.
        """
        existing_keywords = existing_keywords or []
        logger.info("Starting trend research", limit=limit, mode=mode)

        try:
            # ── Jalankan semua source secara parallel ──────────────────────
            results = await asyncio.gather(
                self._fetch_google_trends(),
                self._fetch_google_suggest(),
                self._fetch_reddit(),
                self._fetch_gpt_keywords(
                    mode=mode,
                    count=max(10, limit // 2),   # GPT isi ~50% slot
                    existing_keywords=existing_keywords,
                ),
                return_exceptions=True,
            )

            source_names = ["google_trends", "google_suggest", "reddit", "gpt"]
            all_keywords: list[TrendingKeyword] = []
            for source_name, result in zip(source_names, results):
                if isinstance(result, Exception):
                    logger.warning("Trend source failed", source=source_name, error=str(result))
                    continue
                logger.debug("Source fetched", source=source_name, count=len(result))
                all_keywords.extend(result)

            # ── Deduplikasi ────────────────────────────────────────────────
            seen: set[str] = set()
            unique: list[TrendingKeyword] = []
            for kw in all_keywords:
                normalized = kw.keyword.lower().strip()
                # Juga skip jika sudah ada artikel dengan keyword ini
                if (normalized not in seen
                        and len(normalized) > 3
                        and normalized not in {e.lower() for e in existing_keywords}):
                    seen.add(normalized)
                    unique.append(kw)

            # ── Pilih strategy berdasarkan mode ───────────────────────────
            if mode == "golden":
                final = self._select_golden(unique, limit=limit)
            else:
                final = self._balance_by_niche(unique, limit=limit)

            logger.info(
                "Trend research completed",
                mode=mode,
                total_candidates=len(unique),
                returned=len(final),
            )
            return final

        except Exception as e:
            raise KeywordResearchError(f"Trend research failed: {e}") from e

    # ─── Source 1: Google Trends ───────────────────────────────────────────────

    async def _fetch_google_trends(self) -> list[TrendingKeyword]:
        """Fetch real-time trending searches dari Google Trends RSS Indonesia."""
        keywords: list[TrendingKeyword] = []
        url = "https://trends.google.com/trends/trendingsearches/daily/rss?geo=ID"

        try:
            async with AsyncHTTPClient(
                headers={"Accept": "application/rss+xml, application/xml, text/xml"}
            ) as client:
                response = await client.get(url)
                root = ElementTree.fromstring(response.text)
                for item in root.findall(".//item"):
                    title = item.find("title")
                    if title is not None and title.text:
                        raw_term = title.text.strip()
                        if self._is_electronics_related(raw_term):
                            keywords.append(TrendingKeyword(
                                keyword=raw_term,
                                source="google_trends",
                                raw_score=8.0,
                            ))
            logger.debug("Google Trends fetched", count=len(keywords))
        except Exception as e:
            logger.warning("Google Trends fetch failed", error=str(e))

        if not keywords:
            for niche, seeds in SEED_KEYWORDS_BY_NICHE.items():
                keywords.append(TrendingKeyword(
                    keyword=random.choice(seeds),
                    source="seed_fallback",
                    raw_score=4.0,
                ))

        return keywords

    # ─── Source 2: Google Suggest ──────────────────────────────────────────────

    async def _fetch_google_suggest(self) -> list[TrendingKeyword]:
        """Autocomplete suggestions, 1 seed acak per niche."""
        keywords: list[TrendingKeyword] = []
        selected_seeds = [random.choice(seeds) for seeds in SEED_KEYWORDS_BY_NICHE.values()]

        async def fetch_suggest(seed: str) -> list[str]:
            try:
                async with AsyncHTTPClient() as client:
                    response = await client.get(
                        "https://suggestqueries.google.com/complete/search",
                        params={"client": "firefox", "hl": "id", "gl": "ID", "q": seed},
                    )
                    data = response.json()
                    if isinstance(data, list) and len(data) > 1:
                        return [s for s in data[1] if isinstance(s, str)]
            except Exception as e:
                logger.warning("Google Suggest failed", seed=seed, error=str(e))
            return []

        results = await asyncio.gather(
            *[fetch_suggest(s) for s in selected_seeds], return_exceptions=True
        )
        for suggestions in results:
            if isinstance(suggestions, Exception):
                continue
            for suggestion in suggestions:
                keywords.append(TrendingKeyword(
                    keyword=suggestion, source="google_suggest", raw_score=5.0,
                ))

        logger.debug("Google Suggest keywords", count=len(keywords))
        return keywords

    # ─── Source 3: Reddit ──────────────────────────────────────────────────────

    async def _fetch_reddit(self) -> list[TrendingKeyword]:
        """Trending posts dari electronics subreddits."""
        keywords: list[TrendingKeyword] = []
        for subreddit in ["r/homeautomation", "r/hvac", "r/appliancerepair"]:
            try:
                async with AsyncHTTPClient(headers={"User-Agent": "AutoBlog/1.0"}) as client:
                    response = await client.get(
                        f"https://www.reddit.com/{subreddit}/hot.json?limit=10"
                    )
                    posts = response.json().get("data", {}).get("children", [])
                    for post in posts:
                        title = post.get("data", {}).get("title", "")
                        if title and self._is_electronics_related(title):
                            cleaned = re.sub(r"[^\w\s]", " ", title)[:100]
                            keywords.append(TrendingKeyword(
                                keyword=cleaned.strip(), source="reddit", raw_score=4.0,
                            ))
            except Exception as e:
                logger.warning("Reddit fetch failed", subreddit=subreddit, error=str(e))

        if not keywords:
            for seeds in SEED_KEYWORDS_BY_NICHE.values():
                keywords.append(TrendingKeyword(
                    keyword=random.choice(seeds), source="seed_fallback", raw_score=3.0,
                ))

        logger.debug("Reddit keywords", count=len(keywords))
        return keywords

    # ─── Source 4: GPT-4o Mini ─────────────────────────────────────────────────

    async def _fetch_gpt_keywords(
        self,
        mode: ResearchMode,
        count: int,
        existing_keywords: list[str],
    ) -> list[TrendingKeyword]:
        """
        Generate keyword suggestions menggunakan GPT-4o Mini.

        Mode balanced: cari keyword beragam yang belum dicover
        Mode golden  : fokus pada keyword long-tail, low competition
        """
        # Ringkas existing keywords agar prompt tidak terlalu panjang
        existing_summary = ", ".join(existing_keywords[-30:]) if existing_keywords else "belum ada"

        if mode == "golden":
            prompt = GPT_GOLDEN_PROMPT.format(
                niches=", ".join(SEED_KEYWORDS_BY_NICHE.keys()),
                existing_keywords=existing_summary,
                count=count,
            )
            raw_score = 9.0   # Golden keyword = prioritas tinggi
        else:
            prompt = GPT_BALANCED_PROMPT.format(
                existing_keywords=existing_summary,
                count=count,
            )
            raw_score = 7.0

        logger.info("Fetching GPT keywords", mode=mode, count=count)

        try:
            response = await self._openai.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.8,   # Sedikit lebih kreatif untuk variasi
                max_tokens=2000,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            # GPT return object dengan key apapun, kita ambil array pertama
            data = json.loads(content)
            items = self._extract_array(data)

            keywords: list[TrendingKeyword] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                kw_text = item.get("keyword", "").strip()
                if not kw_text or len(kw_text) < 5:
                    continue

                # Golden keyword dapat tag khusus agar mudah difilter
                source_tag = "gpt_golden" if mode == "golden" else "gpt_balanced"

                keywords.append(TrendingKeyword(
                    keyword=kw_text,
                    source=source_tag,
                    raw_score=raw_score,
                    related_keywords=[item.get("rationale", "")],
                ))

            logger.info("GPT keywords generated", mode=mode, count=len(keywords))
            return keywords

        except json.JSONDecodeError as e:
            logger.warning("GPT keyword response not valid JSON", error=str(e))
            return []
        except Exception as e:
            logger.error("GPT keyword fetch failed", error=str(e))
            return []

    # ─── Selection Strategies ──────────────────────────────────────────────────

    def _select_golden(
        self, keywords: list[TrendingKeyword], limit: int
    ) -> list[TrendingKeyword]:
        """
        Golden mode selection:
        - Prioritaskan keyword dari source "gpt_golden" (raw_score 9.0)
        - Kemudian keyword panjang (long-tail = 4+ kata) dari source lain
        - Sisanya random dari semua source

        Juga pastikan tetap ada variasi niche.
        """
        # Kelompokkan berdasarkan prioritas
        gpt_golden = [k for k in keywords if k.source == "gpt_golden"]
        long_tail = [
            k for k in keywords
            if k.source != "gpt_golden" and len(k.keyword.split()) >= 4
        ]
        others = [
            k for k in keywords
            if k.source != "gpt_golden" and len(k.keyword.split()) < 4
        ]

        # Shuffle masing-masing agar tidak selalu urutan sama
        random.shuffle(gpt_golden)
        random.shuffle(long_tail)
        random.shuffle(others)

        # Proporsi: 50% GPT golden, 35% long-tail, 15% others
        n_golden = int(limit * 0.50)
        n_longtail = int(limit * 0.35)
        n_others = limit - n_golden - n_longtail

        selected = (
            gpt_golden[:n_golden]
            + long_tail[:n_longtail]
            + others[:n_others]
        )

        # Pad jika kurang
        if len(selected) < limit:
            remaining = [k for k in keywords if k not in selected]
            random.shuffle(remaining)
            selected += remaining[:limit - len(selected)]

        logger.info(
            "Golden selection done",
            gpt_golden=len(gpt_golden[:n_golden]),
            long_tail=len(long_tail[:n_longtail]),
            others=len(others[:n_others]),
        )
        return selected[:limit]

    def _balance_by_niche(
        self, keywords: list[TrendingKeyword], limit: int
    ) -> list[TrendingKeyword]:
        """
        Balanced mode: distribusi merata antar niche.
        GPT balanced keywords tetap dapat slot lebih karena raw_score 7.0,
        tapi tidak mendominasi — max slots_per_niche per niche.
        """
        niche_buckets: dict[str, list[TrendingKeyword]] = {
            niche: [] for niche in SEED_KEYWORDS_BY_NICHE
        }
        niche_buckets["other"] = []

        for kw in keywords:
            niche = self._classify_niche(kw.keyword)
            niche_buckets[niche].append(kw)

        num_niches = len(niche_buckets)
        slots_per_niche = max(2, limit // num_niches)

        balanced: list[TrendingKeyword] = []
        for bucket in niche_buckets.values():
            # Sort by raw_score desc dalam bucket — GPT golden dapat prioritas
            bucket.sort(key=lambda k: k.raw_score, reverse=True)
            balanced.extend(bucket[:slots_per_niche])

        random.shuffle(balanced)

        distribution = {
            n: len([k for k in balanced if self._classify_niche(k.keyword) == n])
            for n in SEED_KEYWORDS_BY_NICHE
        }
        logger.info("Niche distribution after balancing", distribution=distribution)
        return balanced[:limit]

    # ─── Helpers ───────────────────────────────────────────────────────────────

    def _extract_array(self, data: dict | list) -> list:
        """Extract array dari GPT JSON response — key bisa apapun."""
        if isinstance(data, list):
            return data
        # Cari value pertama yang berupa list
        for value in data.values():
            if isinstance(value, list):
                return value
        return []

    def _classify_niche(self, text: str) -> str:
        text_lower = text.lower()
        niche_signals = {
            "ac":           ["ac ", " ac", "air conditioner", "inverter ac", "freon", "hvac", "daikin", "panasonic ac"],
            "kulkas":       ["kulkas", "refrigerator", "fridge", "lemari es"],
            "mesin_cuci":   ["mesin cuci", "washing machine", "laundry", "spin"],
            "freezer":      ["freezer", "chest freezer", "deep freezer"],
            "showcase":     ["showcase", "display cooler", "lemari display"],
            "water_heater": ["water heater", "pemanas air", "solar heater"],
            "dispenser":    ["dispenser", "galon", "water dispenser", "air minum"],
            "hemat_listrik":["hemat listrik", "tagihan listrik", "watt", "kwh", "efisiensi energi"],
            "troubleshoot": ["error", "rusak", "bunyi", "bocor", "mati", "kode", "troubleshoot", "perbaikan", "servis"],
            "review":       ["terbaik", "rekomendasi", "review", "perbandingan", "harga", "murah", "mahal"],
        }
        for niche, signals in niche_signals.items():
            if any(sig in text_lower for sig in signals):
                return niche
        return "other"

    def _is_electronics_related(self, text: str) -> bool:
        electronics_terms = {
            "ac", "kulkas", "mesin cuci", "freezer", "showcase", "water heater",
            "dispenser", "listrik", "elektronik", "inverter", "freon", "kompresor",
            "heater", "refrigerator", "washing machine", "air conditioner",
            "pendingin", "pompa", "filter", "energi", "watt", "ampere",
            "troubleshooting", "error", "rusak", "servis", "perbaikan",
            "hemat", "efisiensi", "tips", "cara", "panduan",
        }
        text_lower = text.lower()
        return any(term in text_lower for term in electronics_terms)
