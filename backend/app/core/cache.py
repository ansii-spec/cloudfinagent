"""Small key/value cache on Redis (credential cache, rate limits, locks).

Falls back to an in-process dict when Redis is unreachable (unit tests, single-process dev)."""
import logging
import threading
import time

import redis

from app.config import get_settings

log = logging.getLogger("cache")


class MemoryCache:
    def __init__(self):
        self._d: dict[str, tuple[str, float | None]] = {}
        self._lock = threading.Lock()

    def _alive(self, key):
        item = self._d.get(key)
        if item and item[1] is not None and item[1] < time.time():
            self._d.pop(key, None)
            return None
        return item

    def get(self, key):
        with self._lock:
            item = self._alive(key)
            return item[0] if item else None

    def set(self, key, value, ex=None, nx=False):
        with self._lock:
            if nx and self._alive(key):
                return False
            self._d[key] = (value, time.time() + ex if ex else None)
            return True

    def incr(self, key):
        with self._lock:
            item = self._alive(key)
            val = int(item[0]) + 1 if item else 1
            self._d[key] = (str(val), item[1] if item else None)
            return val

    def expire(self, key, seconds):
        with self._lock:
            item = self._alive(key)
            if item:
                self._d[key] = (item[0], time.time() + seconds)

    def delete(self, *keys):
        with self._lock:
            for k in keys:
                self._d.pop(k, None)

    def flushall(self):
        with self._lock:
            self._d.clear()


_client = None


def get_cache():
    global _client
    if _client is None:
        try:
            c = redis.Redis.from_url(get_settings().redis_url, decode_responses=True, socket_connect_timeout=1)
            c.ping()
            _client = c
        except Exception:  # noqa: BLE001
            log.warning("Redis unreachable, using in-memory cache (fine for tests / single process)")
            _client = MemoryCache()
    return _client


def set_cache(client) -> None:
    global _client
    _client = client


def hit_rate_limit(key: str, limit: int, window_s: int) -> bool:
    """Fixed-window counter. Returns True when the limit is exceeded."""
    c = get_cache()
    n = c.incr(key)
    if n == 1:
        c.expire(key, window_s)
    return n > limit
