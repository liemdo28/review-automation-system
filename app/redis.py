import redis as sync_redis

from app.config import settings

redis_conn = sync_redis.from_url(settings.redis_url)


def get_queue(name: str = "default"):
    from rq import Queue

    return Queue(name, connection=redis_conn)


def get_default_queue():
    return get_queue("default")
