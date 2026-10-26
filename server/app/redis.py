"""Upstash / Redis Integration with Sliding-Window Rate Limiter and Memory Fallback."""

import time

import redis.asyncio as aioredis

from app.config import get_settings

settings = get_settings()


class InMemoryLimiter:
    """In-memory rate limiter and cache fallback for testing/local setups."""
    def __init__(self):
        self._store = {}
        self._lockouts = {}
        self._blacklists = {}
        self._cache = {}

    def check_rate_limit(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int, int]:
        now = time.time()
        # Check lockout
        if key in self._lockouts:
            unlock_time = self._lockouts[key]
            if now < unlock_time:
                return False, 0, int(unlock_time - now)
            del self._lockouts[key]

        timestamps = self._store.get(key, [])
        valid_from = now - window_seconds
        timestamps = [ts for ts in timestamps if ts > valid_from]

        if len(timestamps) >= limit:
            remaining = 0
            reset = int(window_seconds - (now - timestamps[0])) if timestamps else window_seconds
            return False, remaining, max(1, reset)

        timestamps.append(now)
        self._store[key] = timestamps
        remaining = limit - len(timestamps)
        reset = window_seconds
        return True, remaining, reset

    def set_lockout(self, key: str, duration_seconds: int) -> None:
        self._lockouts[key] = time.time() + duration_seconds

    def is_locked_out(self, key: str) -> bool:
        now = time.time()
        if key in self._lockouts:
            if now < self._lockouts[key]:
                return True
            del self._lockouts[key]
        return False

    def blacklist_jti(self, jti: str, ttl_seconds: int) -> None:
        self._blacklists[jti] = time.time() + ttl_seconds

    def is_jti_blacklisted(self, jti: str) -> bool:
        now = time.time()
        if jti in self._blacklists:
            if now < self._blacklists[jti]:
                return True
            del self._blacklists[jti]
        return False

    def cache_get(self, key: str) -> str | None:
        now = time.time()
        if key in self._cache:
            val, exp = self._cache[key]
            if exp is None or now < exp:
                return val
            del self._cache[key]
        return None

    def cache_set(self, key: str, value: str, ttl_seconds: int | None = None) -> None:
        exp = (time.time() + ttl_seconds) if ttl_seconds else None
        self._cache[key] = (value, exp)


class RedisService:
    """Async Redis wrapper supporting Upstash TLS connection with graceful fallback."""

    def __init__(self):
        self.redis_client: aioredis.Redis | None = None
        self.memory_limiter = InMemoryLimiter()
        self._connected = False

    async def init(self) -> None:
        try:
            if settings.REDIS_URL.startswith("redis"):
                self.redis_client = aioredis.from_url(
                    settings.REDIS_URL,
                    encoding="utf-8",
                    decode_responses=True,
                    socket_connect_timeout=2
                )
                await self.redis_client.ping()
                self._connected = True
        except Exception:
            # Fallback to in-memory store
            self._connected = False
            self.redis_client = None

    async def close(self) -> None:
        if self.redis_client:
            await self.redis_client.close()

    async def check_rate_limit(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int, int]:
        """
        Sliding-window rate limiter.
        Returns: (is_allowed, remaining_attempts, reset_seconds)
        """
        if not self._connected or not self.redis_client:
            return self.memory_limiter.check_rate_limit(key, limit, window_seconds)

        now = time.time()
        lockout_key = f"lockout:{key}"
        try:
            if await self.redis_client.exists(lockout_key):
                ttl = await self.redis_client.ttl(lockout_key)
                return False, 0, max(1, ttl)

            pipeline = self.redis_client.pipeline()
            window_start = now - window_seconds
            zset_key = f"ratelimit:{key}"

            pipeline.zremrangebyscore(zset_key, 0, window_start)
            pipeline.zcard(zset_key)
            pipeline.zadd(zset_key, {str(now): now})
            pipeline.expire(zset_key, window_seconds)
            results = await pipeline.execute()

            current_count = results[1]
            if current_count >= limit:
                remaining = 0
                return False, remaining, window_seconds

            remaining = max(0, limit - (current_count + 1))
            return True, remaining, window_seconds
        except Exception:
            return self.memory_limiter.check_rate_limit(key, limit, window_seconds)

    async def set_lockout(self, key: str, duration_seconds: int) -> None:
        """Lock out a key for specified seconds."""
        if not self._connected or not self.redis_client:
            self.memory_limiter.set_lockout(key, duration_seconds)
            return

        try:
            await self.redis_client.set(f"lockout:{key}", "1", ex=duration_seconds)
        except Exception:
            self.memory_limiter.set_lockout(key, duration_seconds)

    async def is_locked_out(self, key: str) -> bool:
        """Check if key is currently locked out."""
        if not self._connected or not self.redis_client:
            return self.memory_limiter.is_locked_out(key)

        try:
            return bool(await self.redis_client.exists(f"lockout:{key}"))
        except Exception:
            return self.memory_limiter.is_locked_out(key)

    async def blacklist_jti(self, jti: str, ttl_seconds: int) -> None:
        """Add JWT jti to blacklist."""
        if not self._connected or not self.redis_client:
            self.memory_limiter.blacklist_jti(jti, ttl_seconds)
            return

        try:
            await self.redis_client.set(f"revoked_jti:{jti}", "1", ex=ttl_seconds)
        except Exception:
            self.memory_limiter.blacklist_jti(jti, ttl_seconds)

    async def is_jti_blacklisted(self, jti: str) -> bool:
        """Check if JWT jti is blacklisted."""
        if not self._connected or not self.redis_client:
            return self.memory_limiter.is_jti_blacklisted(jti)

        try:
            return bool(await self.redis_client.exists(f"revoked_jti:{jti}"))
        except Exception:
            return self.memory_limiter.is_jti_blacklisted(jti)

    async def cache_get(self, key: str) -> str | None:
        if not self._connected or not self.redis_client:
            return self.memory_limiter.cache_get(key)
        try:
            return await self.redis_client.get(f"cache:{key}")
        except Exception:
            return self.memory_limiter.cache_get(key)

    async def cache_set(self, key: str, value: str, ttl_seconds: int = 60) -> None:
        if not self._connected or not self.redis_client:
            self.memory_limiter.cache_set(key, value, ttl_seconds)
            return
        try:
            await self.redis_client.set(f"cache:{key}", value, ex=ttl_seconds)
        except Exception:
            self.memory_limiter.cache_set(key, value, ttl_seconds)


# Singleton instance
redis_service = RedisService()


async def get_redis() -> RedisService:
    """Dependency for obtaining Redis service."""
    return redis_service
