"""Optional standalone worker for rq mode."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings
from app.redis import get_default_queue, redis_conn
from app.workers.process_worker import process_queued_jobs


if __name__ == "__main__":
    if (settings.job_execution_mode or "inline").lower() != "rq":
        print("JOB_EXECUTION_MODE is not set to 'rq'. Running queued jobs inline once instead.")
        process_queued_jobs()
        raise SystemExit(0)

    from rq import Worker

    worker = Worker([get_default_queue()], connection=redis_conn)
    worker.work()
