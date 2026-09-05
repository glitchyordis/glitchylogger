"""FastAPI wiring reference.

    uvicorn examples.fastapi_app:app

Switch the log target at runtime::

    curl -X POST localhost:8000/admin/log-file -H "content-type: application/json" \
         -d '{"path": "logB.log"}'

Multiple OS workers (``--workers N``): each worker process is started by uvicorn
itself, so no parent process owns a shared queue. Either give each worker its own
file (``MPMT_LOG_FILE=logs/worker-$PID.log``) or run a single worker and scale with
threads/async. The queue transport here covers processes you spawn yourself.
"""

from __future__ import annotations

import logging
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi import Depends, FastAPI, HTTPException, Request  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from glitchylogger import (  # noqa: E402
    LoggerConfig,
    bind_context,
    configure_logging,
    get_dropped_count,
    get_log_file,
    get_logger,
    set_log_file,
    shutdown_logging,
)

LOG_DIR = Path(__file__).resolve().parent / "api-logs"
UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi")

log = get_logger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(
        LoggerConfig(file_path=LOG_DIR / "logA.log", level="INFO", allowed_root=LOG_DIR)
    )
    for name in UVICORN_LOGGERS:  # route uvicorn's own logs through the same pipeline
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
    log.info("api starting, logging to %s", get_log_file())
    yield
    log.info("api stopping")
    shutdown_logging()


app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    with bind_context(request_id=request_id):
        log.info("-> %s %s", request.method, request.url.path)
        response = await call_next(request)
        log.info("<- %s %s", response.status_code, request.url.path)
        response.headers["x-request-id"] = request_id
        return response


class SwitchRequest(BaseModel):
    path: str
    migrate: bool = False


def require_admin(request: Request) -> None:
    """Replace with real authentication.

    This endpoint chooses where the process writes files. Without auth it is an
    arbitrary-file-write primitive; `allowed_root` in LoggerConfig is the second
    line of defence, not the first.
    """
    if request.headers.get("x-admin-token") != "change-me":
        raise HTTPException(status_code=401, detail="unauthorized")


@app.get("/health")
async def health() -> dict:
    return {"log_file": str(get_log_file()), "dropped": get_dropped_count()}


@app.get("/work")
async def work(n: int = 3) -> dict:
    for i in range(n):
        log.info("step %d", i)
    return {"ok": True}


@app.post("/admin/log-file", dependencies=[Depends(require_admin)])
async def switch_log_file(payload: SwitchRequest) -> dict:
    try:
        ok = set_log_file(payload.path, migrate=payload.migrate)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=500, detail="log switch failed; still writing to old file")
    return {"log_file": str(get_log_file())}
