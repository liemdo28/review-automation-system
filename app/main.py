"""FastAPI application with APScheduler for START review operations."""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.workers.fetch_worker import fetch_all_reviews
from app.workers.process_worker import process_queued_jobs

# ── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-5s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("review_system")

# ── Scheduler ────────────────────────────────────────────────────────────────

scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("START is starting up...")
    logger.info(f"DRY_RUN={settings.dry_run}")
    logger.info(f"Fetch interval: {settings.fetch_interval_minutes}m")

    scheduler.add_job(
        fetch_all_reviews,
        "interval",
        minutes=settings.fetch_interval_minutes,
        id="fetch_reviews",
        name="Fetch reviews from Google + Yelp",
        max_instances=1,
    )

    scheduler.add_job(
        _run_process_worker,
        "interval",
        minutes=settings.process_interval_minutes,
        id="process_queue",
        name="Process job queue",
        max_instances=1,
    )

    scheduler.start()
    logger.info("Scheduler started")

    yield

    # Shutdown
    scheduler.shutdown(wait=False)
    logger.info("START shut down")


async def _run_process_worker():
    """Run the sync process worker in a thread pool."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, process_queued_jobs)


# ── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="START",
    version="1.0.0",
    lifespan=lifespan,
)

# Static files & templates
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# Routes
from app.routes.dashboard import router as dashboard_router  # noqa: E402
from app.routes.api import router as api_router  # noqa: E402

app.include_router(dashboard_router)
app.include_router(api_router, prefix="/api")
