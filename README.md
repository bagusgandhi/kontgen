# AutoBlog Generator

Pipeline otomatis untuk menghasilkan artikel SEO & GEO friendly tentang elektronik rumah tangga dan mempublikasikannya ke WordPress setiap hari.

## Arsitektur

```
n8n (Cron Trigger)
    │
    ▼
FastAPI (Python Backend)
    │
    ├── TrendResearcher      → Google Trends, Suggest, Reddit
    ├── KeywordScorer        → GPT-4o Mini scoring (6 dimensi)
    ├── ContentGenerator     → GPT-4o Mini (outline + artikel)
    ├── SEOValidator         → density, structure, GEO signals
    ├── ImageProviderFactory → Unsplash → Pexels → Pixabay → Wikimedia
    ├── ImageProcessor       → Resize 1200x630, overlay, WebP
    ├── WordPressClient      → REST API v2
    └── TeamsNotifier        → Adaptive Card
```

## Tech Stack

- **Orchestrator**: n8n
- **Backend**: Python 3.12 + FastAPI
- **AI**: OpenAI GPT-4o Mini
- **Database**: SQLite (MVP) / PostgreSQL (production)
- **Cache**: Redis
- **Image**: Pillow
- **Container**: Docker + Docker Compose

## Quick Start

### 1. Clone & Setup

```bash
git clone <repo>
cd autoblog-generator
cp .env.example .env
```

### 2. Isi .env

```env
OPENAI_API_KEY=sk-...
WORDPRESS_URL=https://yourblog.com
WORDPRESS_USERNAME=admin
WORDPRESS_APP_PASSWORD=xxxx xxxx xxxx xxxx
IMAGE_PROVIDER=unsplash
UNSPLASH_ACCESS_KEY=...
PEXELS_API_KEY=...
PIXABAY_API_KEY=...
TEAMS_WEBHOOK_URL=https://...
```

### 3. Tambahkan Assets

```
assets/
├── logo.png              # Logo perusahaan (120x60px recommended)
└── default_thumbnail.webp # Fallback thumbnail (1200x630px)
```

### 4. Jalankan

```bash
docker-compose up -d
```

Akses:
- **API Docs**: http://localhost:8000/docs
- **n8n**: http://localhost:5678

### 5. Import n8n Workflow

1. Buka n8n di http://localhost:5678
2. Menu → Import from File
3. Pilih `n8n_workflows/autoblog_daily_pipeline.json`
4. Aktifkan workflow

## API Endpoints

### Pipeline

```
POST /api/v1/pipeline/run
{
  "keyword": "cara merawat AC",  // optional, auto-research jika kosong
  "force": false                  // skip duplicate check
}
```

Response:
```json
{
  "success": true,
  "keyword": "cara merawat AC",
  "article_title": "Cara Merawat AC Split Inverter...",
  "wp_post_id": 123,
  "wp_draft_url": "https://yourblog.com/?p=123",
  "thumbnail_source": "unsplash",
  "word_count": 2150,
  "processing_time_seconds": 18.5,
  "seo_score": 7.2
}
```

```
GET /api/v1/pipeline/history     # Riwayat pipeline runs
GET /api/v1/pipeline/status/{id} # Status run tertentu
```

### Keyword

```
POST /api/v1/keywords/research   # Research trending keywords
POST /api/v1/keywords/score      # Score specific keyword
GET  /api/v1/keywords/           # List scored keywords
```

### Articles

```
GET    /api/v1/articles/         # List all articles
GET    /api/v1/articles/{id}     # Detail article
DELETE /api/v1/articles/{id}     # Delete record (not from WP)
```

## WordPress Setup

1. **Buat Application Password**:
   - WP Admin → Users → Your Profile
   - Scroll ke "Application Passwords"
   - Buat password baru dengan nama "AutoBlog Generator"
   - Copy passwordnya ke `.env` sebagai `WORDPRESS_APP_PASSWORD`

2. **Pastikan plugin terpasang** (opsional tapi disarankan):
   - Yoast SEO atau RankMath (untuk meta SEO fields)
   - REST API Taxonomy support

## Image Provider Priority

Pipeline mencoba provider secara berurutan:

```
IMAGE_PROVIDER=unsplash  →  Unsplash → Pexels → Pixabay → Wikimedia
IMAGE_PROVIDER=pexels    →  Pexels → Unsplash → Pixabay → Wikimedia
```

Jika semua provider gagal, gunakan `default_thumbnail.webp` dari assets.

## SEO & GEO Validation

Artikel divalidasi sebelum publish:

| Check | Target |
|-------|--------|
| Keyword density | 1-2% |
| Word count | 1800-2500 |
| H2 headings | ≥ 3 |
| Meta description | 120-160 chars |
| SEO title | 50-65 chars |
| GEO signals | ≥ 2 patterns |
| FAQ section | Required |

## Running Tests

```bash
# Install deps
pip install -r requirements.txt

# Run tests
pytest

# With coverage
pytest --cov=. --cov-report=html
```

## Project Structure

```
autoblog-generator/
├── main.py                      # FastAPI app entry point
├── core/
│   ├── config.py                # Settings (pydantic-settings)
│   ├── models.py                # Pydantic schemas
│   ├── exceptions.py            # Custom exceptions
│   └── logging.py               # Structured logging
├── services/
│   ├── pipeline.py              # Main orchestrator
│   ├── database.py              # SQLAlchemy models & session
│   ├── trend_research/          # Google Trends, Suggest, Reddit
│   ├── keyword_scoring/         # GPT-4o Mini scoring
│   ├── content_generator/       # Article generation
│   ├── seo_validator/           # SEO & GEO validation
│   ├── image_provider/          # Factory + 4 providers
│   ├── wordpress/               # WP REST API client
│   ├── scheduler/               # APScheduler (standalone mode)
│   └── utils/
│       ├── http_client.py       # Async HTTP with retry
│       ├── image_processor.py   # Pillow processing
│       └── notifier.py          # Teams Adaptive Cards
├── api/routes/
│   ├── pipeline.py              # Pipeline endpoints
│   ├── articles.py              # Articles CRUD
│   ├── keywords.py              # Keyword management
│   └── health.py                # Health checks
├── tests/                       # Unit & integration tests
├── n8n_workflows/               # n8n workflow JSON files
├── migrations/                  # Alembic DB migrations
├── assets/                      # logo.png, default_thumbnail.webp
├── docker-compose.yml
├── Dockerfile
└── .env.example
```

## Target Niche

- AC (Air Conditioner)
- Kulkas & Freezer
- Mesin Cuci
- Water Heater
- Dispenser
- Showcase
- Tips Hemat Listrik
- Cara Merawat Elektronik
- Kode Error Elektronik
- Troubleshooting
- Perbandingan Produk

## Future Enhancements

- [ ] PostgreSQL support (change `DATABASE_URL`)
- [ ] OpenAI Image Provider (DALL-E)
- [ ] Flux Image Provider
- [ ] Article scheduling (publish at specific time)
- [ ] Multi-site WordPress support
- [ ] Keyword performance tracking
- [ ] Auto-internal linking
- [ ] Article series generation
