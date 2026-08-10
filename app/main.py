"""Chat service application."""

from __future__ import annotations

from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from utils.mock_llm import generate_reply

from .auth import verify_bearer_token
from .config import get_settings
from .cost_guard import CostGuard
from .lifecycle import shutdown_guard
from .logging_utils import emit
from .rate_limiter import TokenBucket
from .store import ChatStore, get_redis_client

SERVICE_NAME = "day12-chat-service"
SERVICE_VERSION = "1.0.0"
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@lru_cache(maxsize=1)
def get_store() -> ChatStore:
    return ChatStore(get_redis_client())


@lru_cache(maxsize=1)
def get_bucket() -> TokenBucket:
    settings = get_settings()
    return TokenBucket(
        get_redis_client(),
        capacity=settings.bucket_capacity,
        refill_per_minute=settings.refill_per_minute,
    )


@lru_cache(maxsize=1)
def get_cost_guard() -> CostGuard:
    return CostGuard(get_redis_client(), get_settings().daily_budget_usd)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    shutdown_guard.arm()
    emit("service_started", service=SERVICE_NAME, version=SERVICE_VERSION)
    yield
    emit("service_stopped", service=SERVICE_NAME)


app = FastAPI(title="Day 12 Chat Service", version=SERVICE_VERSION, lifespan=lifespan)

app.mount("/assets", StaticFiles(directory=FRONTEND_DIR), name="assets")


@app.get("/", include_in_schema=False)
def frontend_index():
    """Serve the lightweight web client from the same origin as the API."""
    return FileResponse(FRONTEND_DIR / "index.html")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


@app.get("/healthz")
def healthz():
    if shutdown_guard.draining:
        return JSONResponse(
            status_code=503,
            content={"status": "draining"},
        )

    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
    }


@app.get("/readyz")
def readyz(store: ChatStore = Depends(get_store)):
    if shutdown_guard.draining:
        return JSONResponse(
            status_code=503,
            content={"status": "draining"},
        )

    if not store.ping():
        return JSONResponse(
            status_code=503,
            content={"status": "not ready", "redis": False},
        )

    return {"status": "ready", "redis": True}


@app.post("/chat")
def chat(
    payload: ChatRequest,
    client_id: str = Depends(verify_bearer_token),
    store: ChatStore = Depends(get_store),
    bucket: TokenBucket = Depends(get_bucket),
    guard: CostGuard = Depends(get_cost_guard),
):
    bucket.consume(client_id)
    guard.check(client_id)

    history = store.history(client_id)
    result = generate_reply(payload.message, history)

    store.add_turn(client_id, "user", payload.message)
    store.add_turn(client_id, "assistant", result["text"])
    guard.record(client_id, result["usd_cost"])

    emit(
        "chat_completed",
        client_id=client_id,
        prompt_tokens=result["prompt_tokens"],
        completion_tokens=result["completion_tokens"],
        usd_cost=result["usd_cost"],
    )

    return {
        "reply": result["text"],
        "client_id": client_id,
        "turns_before": len(history),
        "usd_cost": result["usd_cost"],
        "usage": {
            "prompt": result["prompt_tokens"],
            "completion": result["completion_tokens"],
        },
    }


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
