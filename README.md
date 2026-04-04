# Review Automation System v1.0

Production-ready review automation for **Raw Sushi Bistro** and **Bakudan Ramen** restaurants. Automatically fetches, classifies, and responds to Google Business Profile and Yelp reviews.

## Architecture

```
[APScheduler (10 min)] --> [FETCH] --> [PostgreSQL] --> [PROCESS (1 min)] --> [Redis/rq Queue]
                                                                                    |
                                                                    +-- generate_reply (OpenAI)
                                                                    +-- post_reply (Google API)
                                                                    +-- send_alert_email (SMTP)
```

## Business Rules

| Condition | Action |
|---|---|
| Google 4-5 star | Auto-generate AI reply, auto-post |
| Google 1-3 star | Generate AI suggestion, email owner, wait for approval |
| Yelp (any rating) | Generate AI suggestion, display on dashboard (no auto-post) |

## Quick Start

```bash
# 1. Start infrastructure
docker-compose up -d

# 2. Install Python dependencies
pip install -e .

# 3. Install Playwright browser
playwright install chromium

# 4. Configure environment
cp .env.example .env
# Edit .env with your credentials

# 5. Run database migrations
alembic upgrade head

# 6. Seed restaurant locations
python -m scripts.seed_locations

# 7. Start the web app (includes scheduler)
uvicorn app.main:app --reload --port 8000

# 8. Start rq worker (separate terminal)
python -m scripts.run_worker
```

Dashboard: http://localhost:8000

## Tech Stack

- **FastAPI** + Jinja2 (web dashboard + API)
- **PostgreSQL 16** + SQLAlchemy 2.0 + Alembic
- **Redis 7** + rq (job queue)
- **Playwright** stealth (Yelp scraping)
- **OpenAI** GPT-4o-mini (AI reply generation)
- **APScheduler** (automated fetch + process cycles)
- **Docker Compose** (PostgreSQL + Redis)

## Restaurants

| Restaurant | City | Google | Yelp |
|---|---|---|---|
| Raw Sushi Bistro | Stockton, CA | Active | Active |
| Bakudan Ramen (Bandera) | San Antonio, TX | Active | Active |
| Bakudan Ramen (The Rim) | San Antonio, TX | Active | Active |
| Bakudan Ramen (Stone Oak) | San Antonio, TX | Active | Active |

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | System health check |
| GET | `/api/stats` | Dashboard statistics |
| GET | `/api/reviews` | List reviews (filterable) |
| GET | `/api/reviews/{id}` | Review detail |
| POST | `/api/reviews/{id}/approve` | Approve & post a reply |
| POST | `/api/fetch/trigger` | Manual fetch trigger |
| GET | `/api/locations` | List locations |
| GET | `/api/jobs` | Recent job history |

## Testing

```bash
# DRY_RUN=true (default) - generates replies but doesn't post to Google
# Set DRY_RUN=false in .env for production
```
