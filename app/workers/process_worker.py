"""Scheduled worker: process queued jobs by dispatching to rq."""
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.database import SyncSessionLocal
from app.models import Job
from app.redis import default_queue
from app.workers.reply_worker import (
    task_analyze_review,
    task_generate_reply,
    task_post_reply,
    task_send_alert_email,
)

logger = logging.getLogger("review_system.process_worker")

TASK_MAP = {
    "analyze_review": task_analyze_review,
    "generate_reply": task_generate_reply,   # legacy compat
    "post_reply": task_post_reply,
    "send_alert_email": task_send_alert_email,
}


def process_queued_jobs():
    """Pick up queued jobs from DB and dispatch to rq."""
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

        dispatched = 0
        for job in jobs:
            task_fn = TASK_MAP.get(job.job_type)
            if not task_fn:
                logger.warning(f"Unknown job type: {job.job_type}")
                job.status = "failed"
                job.error_message = f"Unknown job type: {job.job_type}"
                continue

            # Enqueue to rq
            rq_job = default_queue.enqueue(
                task_fn,
                job.id,
                job_timeout="5m",
                retry=None,  # We handle retries ourselves
            )

            job.status = "processing"
            job.started_at = datetime.now(timezone.utc)
            dispatched += 1

        session.commit()
        if dispatched:
            logger.info(f"Dispatched {dispatched} jobs to rq")

    except Exception as e:
        logger.error(f"process_queued_jobs failed: {e}")
        session.rollback()
    finally:
        session.close()
