from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
from conftest import messages, read_jsonl

from glitchylogger import (
    LoggerConfig,
    bind_context,
    configure_logging,
    flush_logs,
    get_dropped_count,
    get_log_file,
    get_logger,
    set_log_file,
)

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

pytestmark = pytest.mark.fastapi


def build_app(log_file: Path, allowed_root: Path) -> FastAPI:
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging(
            LoggerConfig(
                file_path=log_file,
                console=False,
                level="DEBUG",
                allowed_root=allowed_root,
            )
        )
        for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            uvicorn_logger = __import__("logging").getLogger(name)
            uvicorn_logger.handlers.clear()
            uvicorn_logger.propagate = True
        yield
        from glitchylogger import shutdown_logging

        shutdown_logging(timeout=10)

    app = FastAPI(lifespan=lifespan)
    log = get_logger("api")

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        with bind_context(request_id=request_id):
            log.info("request start %s", request.url.path)
            response = await call_next(request)
            log.info("request end %s", request.url.path)
            response.headers["x-request-id"] = request_id
            return response

    @app.get("/work")
    async def work(n: int = 3):
        for i in range(n):
            await asyncio.sleep(0)
            log.info("step-%d", i)
        return {"ok": True}

    @app.get("/health")
    async def health():
        return {"log_file": str(get_log_file()), "dropped": get_dropped_count()}

    @app.post("/admin/log-file")
    async def switch(payload: dict):
        try:
            ok = set_log_file(payload["path"])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not ok:
            raise HTTPException(status_code=500, detail="switch failed")
        return {"log_file": str(get_log_file())}

    return app


def test_lifespan_starts_and_stops_logging(log_file: Path, tmp_path: Path):
    with TestClient(build_app(log_file, tmp_path)) as client:
        assert client.get("/work").status_code == 200
        assert flush_logs(timeout=10)
        assert any(m == "step-0" for m in messages(log_file))
    assert read_jsonl(log_file)[-1]["event"] == "log_close"


def test_each_request_gets_its_own_request_id(log_file: Path, tmp_path: Path):
    with TestClient(build_app(log_file, tmp_path)) as client:
        ids = {client.get("/work", headers={"x-request-id": f"req-{i}"}).headers["x-request-id"] for i in range(5)}
        assert flush_logs(timeout=10)
        records = [r for r in read_jsonl(log_file) if "event" not in r]

    assert ids == {f"req-{i}" for i in range(5)}
    for i in range(5):
        stamped = [r for r in records if r.get("request_id") == f"req-{i}"]
        assert any(r["msg"] == "step-0" for r in stamped)


def test_endpoint_switches_log_file(log_file: Path, alt_file: Path, tmp_path: Path):
    with TestClient(build_app(log_file, tmp_path)) as client:
        client.get("/work")
        response = client.post("/admin/log-file", json={"path": str(alt_file)})
        assert response.status_code == 200
        assert response.json()["log_file"] == str(alt_file)
        client.get("/work")
        assert flush_logs(timeout=10)

        assert any(m == "step-0" for m in messages(alt_file))
        assert client.get("/health").json()["log_file"] == str(alt_file)


def test_traversal_payload_is_rejected(log_file: Path, tmp_path: Path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    with TestClient(build_app(allowed / "logA.log", allowed)) as client:
        response = client.post("/admin/log-file", json={"path": "../../escape.log"})
        assert response.status_code == 400
        assert client.get("/work").status_code == 200


def test_health_reports_dropped_counter(log_file: Path, tmp_path: Path):
    with TestClient(build_app(log_file, tmp_path)) as client:
        assert client.get("/health").json()["dropped"] == 0
