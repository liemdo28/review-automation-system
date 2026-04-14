# Review Operations Dashboard — Developer README

> Automated review collection, AI-assisted reply generation, and management dashboard for multi-location restaurant operations.

---

## Project Overview

**review-automation-system** is a FastAPI-based internal operations tool used by restaurant staff to monitor, triage, and respond to online reviews across Google Business and Yelp.

Key responsibilities:

- **Collect** reviews via configurable, provider-based web scrapers (no official Google/Yelp APIs required)
- **Prioritize** unreplied reviews first in the operations queue
- **Generate** AI-assisted reply suggestions (OpenAI GPT-4o-mini) for staff review
- **Alert** owners/managers when negative reviews are detected
- **Post** operator-assisted replies directly through portal session reuse

---

## Tech Stack

| Layer | Technology |
|---|---|
| Web framework | FastAPI + Jinja2 templates |
| Database | PostgreSQL 16 · SQLAlchemy 2.0 · Alembic migrations |
| Task queue | Redis 7 · optional RQ worker mode |
| Browser automation | Playwright (Chromium) |
| AI generation | OpenAI GPT-4o-mini |
| Job scheduling | APScheduler (fetch + processing cycles) |
| Infrastructure | Docker Compose (PostgreSQL + Redis for local dev) |

---

## Project Structure

```text
review-automation-system/
├── app/
│   ├── main.py              # FastAPI app entry point
│   ├── api/                 # REST API routes (reviews, sources, jobs, stats)
│   ├── db/                  # SQLAlchemy models, session, migrations
│   ├── models/              # Domain models
│   ├── services/            # Business logic (fetch, AI suggestions, posting)
│   ├── providers/           # Source collectors (Google, Yelp)
│   └── templates/           # Jinja2 dashboard templates
├── scripts/
│   ├── seed_locations.py    # Seed restaurant locations into DB
│   └── run_worker.py        # Standalone RQ worker process
├── alembic/                 # Alembic migration scripts
├── docker-compose.yml       # PostgreSQL + Redis for local dev
├── start.bat / stop.bat     # One-click Windows launcher / shutdown
├── .env.example             # Environment variable template
└── docs/
    └── review-ops-architecture-plan.md
```

---

## Main Features

### Review Collection
- Provider-based collectors for Google Business and Yelp
- Uses source URLs + operator-managed authenticated sessions
- Fetches review data directly from page DOM (no third-party API needed)

### AI Reply Suggestions
- GPT-4o-mini generates context-aware reply drafts
- Staff can approve, edit, or regenerate before posting
- Tone-based regeneration endpoint (`POST /api/reviews/{id}/suggestions/regenerate`)

### Operations Dashboard
- Web UI listing all reviews with filters: store, platform, date range, status
- Unreplied reviews surface first by default
- Source health and session status at a glance

### Alerting
- Negative reviews trigger immediate notification to owner/manager
- Source auth expiration triggers re-authentication flag in the dashboard

### Job Scheduling
- `inline` mode (default): APScheduler triggers jobs in-process — ideal for local one-click runs
- `rq` mode: jobs dispatched to a dedicated Redis queue with a separate worker process

---

## Supported Locations

| Restaurant | City | Google | Yelp |
|---|---|---|---|
| Raw Sushi Bistro | Stockton, CA | Active | Active |
| Bakudan Ramen (Bandera) | San Antonio, TX | Active | Active |
| Bakudan Ramen (The Rim) | San Antonio, TX | Active | Active |
| Bakudan Ramen (Stone Oak) | San Antonio, TX | Active | Active |

---

## How to Run

### Option A — One-Click (Windows)

Double-click `start.bat` (or `start-review-ops.bat`).

The launcher will automatically:

1. Create and activate a Python virtual environment (`.venv`) if not present
2. Install Python dependencies
3. Install Playwright Chromium browser
4. Copy `.env.example` → `.env` if `.env` does not exist
5. Start PostgreSQL and Redis via Docker Desktop (when available)
6. Run Alembic database migrations
7. Seed restaurant locations
8. Launch the web app at `http://127.0.0.1:8000`

To stop: double-click `stop.bat` (or `stop-review-ops.bat`).

---

### Option B — Manual / Linux / Mac

```bash
# 1. Start infrastructure
docker-compose up -d

# 2. Install Python dependencies
pip install -e .

# 3. Install Playwright Chromium
playwright install chromium

# 4. Configure environment
cp .env.example .env
# Then edit .env and fill in your secrets

# 5. Run database migrations
alembic upgrade head

# 6. Seed restaurant locations
python -m scripts.seed_locations

# 7. Start the web app
uvicorn app.main:app --reload --port 8000

# 8. (Optional) Start a dedicated RQ worker — only needed when JOB_EXECUTION_MODE=rq
python -m scripts.run_worker
```

**Dashboard:** `http://localhost:8000`

---

## Key API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health` | System health check |
| `GET` | `/api/stats` | Operations dashboard statistics |
| `GET` | `/api/reviews` | List reviews (filter by store / platform / date / status) |
| `GET` | `/api/reviews/{id}` | Review detail with source and suggestion history |
| `POST` | `/api/reviews/{id}/approve` | Approve operator-assisted reply and post |
| `POST` | `/api/reviews/{id}/suggestions/regenerate` | Regenerate AI suggestion by tone |
| `POST` | `/api/fetch/trigger` | Manually trigger a fetch for all or selected sources |
| `GET` | `/api/locations` | List configured restaurant locations |
| `GET` | `/api/sources` | List sources and their session auth status |
| `GET` | `/api/jobs` | Recent background job history |

---

## Business Rules

| Condition | Action |
|---|---|
| Any unreplied review | Collect and queue for operations |
| Negative review | Generate AI suggestion; alert owner/manager immediately |
| Positive review | Generate AI suggestion for staff review |
| Source auth expired | Mark source as requiring re-authentication in dashboard |

---

## Developer Notes

- **`JOB_EXECUTION_MODE=inline`** is the default and is recommended for local/one-click runs. Jobs run in-process via APScheduler — no separate worker needed.
- **`JOB_EXECUTION_MODE=rq`** enables the Redis queue backend. Use `python -m scripts.run_worker` to start a dedicated worker process alongside the web server.
- Portal-based posting is intentionally **operator-assisted** (staff reviews and approves before the reply is submitted live).
- Full architecture, migration strategy, rollout plan, and risk notes are documented in `docs/review-ops-architecture-plan.md`.
