"""CP3 rate limiting with a Redis-backed token bucket."""

from __future__ import annotations

import time

from fastapi import HTTPException, status

BUCKET_TTL_SECONDS = 3600


class TokenBucket:
    def __init__(self, client, capacity: int, refill_per_minute: int) -> None:
        self.client = client
        self.capacity = capacity
        self.refill_per_minute = refill_per_minute

    @staticmethod
    def _key(client_id: str) -> str:
        return f"bucket:{client_id}"

    @property
    def refill_per_second(self) -> float:
        return self.refill_per_minute / 60.0

    def available(self, client_id: str, now: float | None = None) -> float:
        """Return the current number of tokens, including refills."""
        now = now if now is not None else time.time()
        key = self._key(client_id)
        state = self.client.hgetall(key)

        if not state:
            return float(self.capacity)

        tokens = float(state["tokens"])
        last = float(state["ts"])
        tokens += (now - last) * self.refill_per_second
        return max(0.0, min(float(self.capacity), tokens))

    def consume(self, client_id: str, now: float | None = None) -> None:
        """Consume one token or raise HTTP 429 when the bucket is empty."""
        now = now if now is not None else time.time()
        tokens = self.available(client_id, now)

        if tokens < 1:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="rate limit exceeded",
                headers={"Retry-After": str(self.retry_after(tokens))},
            )

        key = self._key(client_id)
        self.client.hset(key, mapping={"tokens": tokens - 1, "ts": now})
        self.client.expire(key, BUCKET_TTL_SECONDS)

    def retry_after(self, tokens: float) -> int:
        """Return seconds until the next token is expected."""
        if self.refill_per_second <= 0:
            return BUCKET_TTL_SECONDS
        return max(1, int((1 - tokens) / self.refill_per_second) + 1)
