"""Redis-backed conversation history for the chat service."""

from __future__ import annotations

import json

import redis

from .config import get_settings

HISTORY_MAX_MESSAGES = 12
HISTORY_TTL_SECONDS = 3 * 24 * 3600


def get_redis_client(url: str | None = None):
    url = url or get_settings().redis_url
    if url.startswith("fake://"):
        import fakeredis

        return fakeredis.FakeRedis(decode_responses=True)
    return redis.from_url(url, decode_responses=True)


class ChatStore:
    """Store each client's conversation in a Redis List."""

    def __init__(self, client) -> None:
        self.client = client

    @staticmethod
    def _key(client_id: str) -> str:
        return f"chat:{client_id}"

    def ping(self) -> bool:
        try:
            return bool(self.client.ping())
        except Exception:
            return False

    def add_turn(self, client_id: str, role: str, content: str) -> None:
        key = self._key(client_id)
        value = json.dumps(
            {"role": role, "content": content},
            ensure_ascii=False,
        )
        self.client.rpush(key, value)
        self.client.ltrim(key, -HISTORY_MAX_MESSAGES, -1)
        self.client.expire(key, HISTORY_TTL_SECONDS)

    def history(self, client_id: str) -> list[dict]:
        values = self.client.lrange(self._key(client_id), 0, -1)
        return [json.loads(value) for value in values]

    def reset(self, client_id: str) -> None:
        self.client.delete(self._key(client_id))
