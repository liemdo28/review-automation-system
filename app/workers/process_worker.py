"""Process queued jobs either inline or through rq."""

import logging
from datetime import datetime

from sqlalchemy import select

from app.config import settings
from app.database import SyncSessionLocal
from app.models import Job
from app.workers.reply_worker import task_generate_reply, task_post_reply, task_send_alert_email

logger = logging.getLogger("review_system.process_worker")

TASK_MAP = {
    "generate_reply": task_generate_reply,
    "post_reply": task_post_reply,
    "send_alert_email": task_send_alert_email,
}


def process_queued_jobs():
    """Pick up queued jobs and process them using the configured execution mode."""
    session = SyncSessionLocal()
    try:
        jobs = session.execute(
            select(Job)
            .where(Job.status == "queued")
            .order_by(Job.queued_at.asc())
            .limit(50)
        ).scalars().all()

        if not jobs:
            return

        mode = (settings.job_execution_mode or "inline").lower()
        if mode == "rq":
            _dispatch_to_rq(session, jobs)
        else:
            _process_inline(session, jobs)

    except Exception as exc:
        logger.error("process_queued_jobs failed: %s", exc)
        session.rollback()
    finally:
        session.close()


def _dispatch_to_rq(session, jobs):
    from app.redis import get_default_queue

    default_queue = get_default_queue()
    dispatched = 0
    for job in jobs:
        task_fn = TASK_MAP.get(job.job_type)
        if not task_fn:
            logger.warning("Unknown job type: %s", job.job_type)
            job.status = "failed"
            job.error_message = f"Unknown job type: {job.job_type}"
            continue

        default_queue.enqueue(task_fn, job.id, job_timeout="5m", retry=None)
        job.status = "processing"
        job.started_at = datetime.utcnow()
        dispatched += 1

    session.commit()
    if dispatched:
        logger.info("Dispatched %s jobs to rq", dispatched)


def _process_inline(session, jobs):
    to_run: list[tuple[int, callable]] = []
    for job in jobs:
        task_fn = TASK_MAP.get(job.job_type)
        if not task_fn:
            logger.warning("Unknown job type: %s", job.job_type)
            job.status = "failed"
            job.error_message = f"Unknown job type: {job.job_type}"
            continue

        job.status = "processing"
        job.started_at = datetime.utcnow()
        to_run.append((job.id, task_fn))

    session.commit()

    for job_id, task_fn in to_run:
        try:
            task_fn(job_id)
        except Exception as exc:
            logger.error("Inline job %s failed: %s", job_id, exc)
