# START v1.0

Review operations dashboard for **Raw Sushi Bistro** and **Bakudan Ramen** restaurants. It collects Google Business and Yelp reviews through configurable providers, surfaces unreplied reviews first, and prepares AI-assisted reply suggestions for staff.

This app does not rely on Google or Yelp review APIs for collection. It opens review pages on the web, reuses an authorized staff session where needed, and pulls review data directly from the visible page content.

## One-Click Start on Windows

Double-click [start.bat](/E:/Project/Master/review-automation-system/start.bat).

Or use [start-review-ops.bat](/E:/Project/Master/review-automation-system/start-review-ops.bat) if you prefer the longer name.

The launcher will:

- create `.venv` if needed
- install Python dependencies
- install Playwright Chromium once
- copy `.env.example` to `.env` if missing
- start PostgreSQL and Redis via Docker Desktop when Docker is available
- run database migrations
- seed locations
- launch the web app at `http://127.0.0.1:8000`

To stop the local app, double-click [stop.bat](/E:/Project/Master/review-automation-system/stop.bat) or [stop-review-ops.bat](/E:/Project/Master/review-automation-system/stop-review-ops.bat).

## Architecture

```text
[APScheduler] --> [Provider-based Fetch] --> [PostgreSQL] --> [Inline Jobs or rq]
                                                        |
                                                        +-- GoogleReviewsPortalProvider
                                                        +-- YelpReviewsProvider
                                                        +-- AI reply suggestions
                                                        +-- alerting
```

## Business Rules

| Condition | Action |
|---|---|
| Any unreplied review | Collect and place into the operations queue |
| Negative review | Generate AI suggestion, alert owner or manager |
| Positive review | Generate AI suggestion for staff review |
| Source auth expired | Mark source as re-authentication required |

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

# 5. Run database migrations
alembic upgrade head

# 6. Seed restaurant locations
python -m scripts.seed_locations

# 7. Start the web app
uvicorn app.main:app --reload --port 8000

# 8. Optional: run a dedicated worker only when JOB_EXECUTION_MODE=rq
python -m scripts.run_worker
```

Dashboard: http://localhost:8000

## Tech Stack

- **FastAPI** + Jinja2
- **PostgreSQL 16** + SQLAlchemy 2.0 + Alembic
- **Redis 7** + optional rq mode
- **Playwright** provider collectors
- **Web-first ingestion** using source URLs plus operator-managed sessions
- **OpenAI** GPT-4o-mini
- **APScheduler** for fetch and processing cycles
- **Docker Compose** for local PostgreSQL + Redis

## Restaurants

| Restaurant | City | Google | Yelp |
|---|---|---|---|
| Raw Sushi Bistro | Stockton, CA | Active | Active |
| Bakudan Ramen (Bandera) | San Antonio, TX | Active | Active |
| Bakudan Ramen (The Rim) | San Antonio, TX | Active | Active |
| Bakudan Ramen (Stone Oak) | San Antonio, TX | Active | Active |

## Key API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | System health check |
| GET | `/api/stats` | Operations dashboard statistics |
| GET | `/api/reviews` | List reviews with store/platform/date/status filters |
| GET | `/api/reviews/{id}` | Review detail with source and suggestion history |
| POST | `/api/reviews/{id}/approve` | Approve an operator-assisted reply |
| POST | `/api/reviews/{id}/suggestions/regenerate` | Regenerate AI suggestion by tone |
| POST | `/api/fetch/trigger` | Manual fetch trigger for all or selected sources |
| GET | `/api/locations` | List locations |
| GET | `/api/sources` | List source and session status |
| GET | `/api/jobs` | Recent job history |

## Notes

- `JOB_EXECUTION_MODE=inline` is the default local mode and is recommended for one-click Windows runs.
- Switch to `JOB_EXECUTION_MODE=rq` only when you want a dedicated queue worker.
- Portal-based posting is intentionally operator-assisted right now.
- Full architecture, migration, rollout, and risk notes are documented in [docs/review-ops-architecture-plan.md](/E:/Project/Master/review-automation-system/docs/review-ops-architecture-plan.md).
