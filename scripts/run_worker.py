"""Start the rq worker process."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rq import Worker
from app.redis import redis_conn, default_queue

if __name__ == "__main__":
    worker = Worker([default_queue], connection=redis_conn)
    worker.work()
