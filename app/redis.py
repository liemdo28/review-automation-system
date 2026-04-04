import redis as sync_redis
from rq import Queue

from app.config import settings

# Sync Redis for rq workers
redis_conn = sync_redis.from_url(settings.redis_url)

# rq queues
default_queue = Queue("default", connection=redis_conn)
fetch_queue = Queue("fetch", connection=redis_conn)
