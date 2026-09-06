from __future__ import annotations

import argparse
import asyncio
import hmac
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from typing import Any, AsyncIterator, Callable

try:
    from starlette.requests import Request
except ImportError:
    Request = Any  # type: ignore[misc,assignment]

_LOG_SUFFIXES = {".jsonl", ".log"}
_CREDENTIAL_SERVICE = "glitchylogger"
_VIEWER_CREDENTIAL = "viewer-token"
_ADMIN_CREDENTIAL = "admin-token"


def _resolve_secret(
    explicit: str | None,
    env_name: str,
    credential_name: str,
    credential_reader: Callable[[str, str], str | None] | None = None,
) -> str | None:
    if explicit:
        return explicit
    environment_value = os.environ.get(env_name)
    if environment_value:
        return environment_value
    if credential_reader is None:
        try:
            import keyring
        except ImportError as exc:
            raise RuntimeError(
                'Install viewer dependencies with: pip install "glitchylogger[viewer]"'
            ) from exc
        credential_reader = keyring.get_password
    try:
        return credential_reader(_CREDENTIAL_SERVICE, credential_name)
    except Exception as exc:
        raise RuntimeError(
            f"could not read {credential_name} from the system credential store"
        ) from exc


def _store_credentials(
    password_reader: Callable[[str], str],
    credential_writer: Callable[[str, str, str], None],
) -> None:
    viewer_token = password_reader("Viewer token: ")
    admin_token = password_reader("Admin token: ")
    if not viewer_token or not admin_token:
        raise ValueError("viewer and admin tokens must not be empty")
    if hmac.compare_digest(viewer_token, admin_token):
        raise ValueError("admin token must differ from viewer token")
    credential_writer(_CREDENTIAL_SERVICE, _VIEWER_CREDENTIAL, viewer_token)
    credential_writer(_CREDENTIAL_SERVICE, _ADMIN_CREDENTIAL, admin_token)


def store_credentials() -> None:
    """Prompt for and save viewer credentials in the operating-system vault."""
    from getpass import getpass

    try:
        import keyring
    except ImportError as exc:
        raise SystemExit(
            'Install viewer dependencies with: pip install "glitchylogger[viewer]"'
        ) from exc
    try:
        _store_credentials(getpass, keyring.set_password)
    except ValueError as exc:
        raise SystemExit(f"Could not store viewer credentials: {exc}") from exc
    except Exception as exc:
        raise SystemExit("Could not store viewer credentials in the system store.") from exc
    print("Viewer and admin tokens stored in the system credential store.")


def _decode_record(raw: bytes) -> dict[str, Any]:
    text = raw.decode("utf-8", errors="replace").rstrip("\r\n")
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        return {"level": "PARSE_ERROR", "msg": text, "parse_error": str(exc)}
    if isinstance(value, dict):
        return value
    return {"level": "PARSE_ERROR", "msg": text, "parse_error": "record is not an object"}


def _tail_records(path: Path, limit: int) -> tuple[list[tuple[int, dict[str, Any]]], bool]:
    if limit <= 0 or not path.exists():
        return [], False

    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        end = stream.tell()
        position = end
        data = b""
        while position > 0 and data.count(b"\n") <= limit:
            size = min(64 * 1024, position)
            position -= size
            stream.seek(position)
            data = stream.read(size) + data

    complete_end = end if data.endswith(b"\n") else end - len(data.rsplit(b"\n", 1)[-1])
    complete = data[: complete_end - position]
    complete_lines = complete.splitlines(keepends=True)
    truncated = position > 0 or len(complete_lines) > limit
    lines = complete_lines[-limit:]
    first_offset = complete_end - sum(len(line) for line in lines)
    records: list[tuple[int, dict[str, Any]]] = []
    offset = first_offset
    for line in lines:
        offset += len(line)
        if line.strip():
            records.append((offset, _decode_record(line)))
    return records, truncated


def tail_records(path: Path, limit: int = 1_000) -> list[tuple[int, dict[str, Any]]]:
    """Return the last complete JSONL records and their ending byte offsets."""
    return _tail_records(path, limit)[0]


@dataclass
class JsonlFollower:
    path: Path
    offset: int = 0
    identity: tuple[int, int] | None = None

    def read_available(self) -> tuple[bool, list[tuple[int, dict[str, Any]]]]:
        """Read newly completed records, returning whether the file reset."""
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            self.identity = None
            self.offset = 0
            return False, []

        identity = (stat.st_dev, stat.st_ino)
        reset = stat.st_size < self.offset or (
            self.identity is not None and identity != self.identity
        )
        if self.identity is None or reset:
            self.identity = identity
            if reset:
                self.offset = 0

        with self.path.open("rb") as stream:
            stream.seek(self.offset)
            data = stream.read()

        complete_length = len(data)
        if data and not data.endswith(b"\n"):
            complete_length -= len(data.rsplit(b"\n", 1)[-1])
        complete = data[:complete_length]
        records: list[tuple[int, dict[str, Any]]] = []
        offset = self.offset
        for line in complete.splitlines(keepends=True):
            offset += len(line)
            if line.strip():
                records.append((offset, _decode_record(line)))
        self.offset += complete_length
        return reset, records


@dataclass
class LogSourceCatalog:
    fixed_file: Path | None = None
    directory: Path | None = None

    def __post_init__(self) -> None:
        if (self.fixed_file is None) == (self.directory is None):
            raise ValueError("configure exactly one log file or directory")
        if self.fixed_file is not None:
            self.fixed_file = self.fixed_file.expanduser().resolve()
        if self.directory is not None:
            self.directory = self.directory.expanduser().resolve()

    def resolve_directory(self, directory: Path | None = None) -> Path:
        if self.fixed_file is not None:
            raise ValueError("directory switching is unavailable in single-file mode")
        selected = directory or self.directory
        assert selected is not None
        resolved = selected.expanduser().resolve()
        if not resolved.is_dir():
            raise ValueError("log directory does not exist")
        return resolved

    def directories(self, directory: Path | None = None) -> tuple[Path, list[Path]]:
        resolved = self.resolve_directory(directory)
        try:
            children = sorted(
                (path for path in resolved.iterdir() if path.is_dir()),
                key=lambda path: path.name.casefold(),
            )
        except OSError as exc:
            raise ValueError("log directory cannot be read") from exc
        return resolved, children

    def files(self, directory: Path | None = None) -> list[Path]:
        if self.fixed_file is not None:
            return [self.fixed_file]
        resolved = self.resolve_directory(directory)
        paths = [
            path
            for path in resolved.iterdir()
            if path.is_file() and path.suffix.lower() in _LOG_SUFFIXES
        ]
        return sorted(paths, key=lambda path: (path.stat().st_mtime_ns, path.name), reverse=True)

    def resolve(self, name: str | None = None, directory: Path | None = None) -> Path | None:
        if self.fixed_file is not None:
            if name not in (None, self.fixed_file.name):
                raise ValueError("file selection is unavailable in single-file mode")
            return self.fixed_file
        paths = self.files(directory)
        if name is None:
            return paths[0] if paths else None
        if Path(name).name != name:
            raise ValueError("invalid log filename")
        match = next((path for path in paths if path.name == name), None)
        if match is None:
            raise ValueError("log file is not available")
        return match

    def describe(self, directory: Path | None = None) -> list[dict[str, Any]]:
        return [
            {
                "name": path.name,
                "size": path.stat().st_size,
                "modified_ns": path.stat().st_mtime_ns,
            }
            for path in self.files(directory)
        ]


@dataclass
class ViewerSession:
    id: str
    connected_at: datetime
    connected_monotonic: float
    last_activity_at: datetime
    last_activity_monotonic: float
    remote_host: str
    user_agent: str
    directory: str | None
    requested_file: str | None
    active_file: str | None = None
    disconnect_event: asyncio.Event = field(default_factory=asyncio.Event)


class ViewerSessionRegistry:
    def __init__(self) -> None:
        self._sessions: dict[str, ViewerSession] = {}

    def create(
        self,
        *,
        remote_host: str,
        user_agent: str,
        directory: str | None,
        requested_file: str | None,
    ) -> ViewerSession:
        now = datetime.now(timezone.utc)
        monotonic_now = time.monotonic()
        session = ViewerSession(
            id=str(uuid.uuid4()),
            connected_at=now,
            connected_monotonic=monotonic_now,
            last_activity_at=now,
            last_activity_monotonic=monotonic_now,
            remote_host=remote_host,
            user_agent=user_agent,
            directory=directory,
            requested_file=requested_file,
        )
        self._sessions[session.id] = session
        return session

    def remove(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def touch(self, session_id: str) -> bool:
        session = self._sessions.get(session_id)
        if session is None or session.disconnect_event.is_set():
            return False
        session.last_activity_at = datetime.now(timezone.utc)
        session.last_activity_monotonic = time.monotonic()
        return True

    def disconnect(self, session_id: str) -> bool:
        session = self._sessions.get(session_id)
        if session is None:
            return False
        session.disconnect_event.set()
        return True

    def disconnect_all(self) -> int:
        sessions = [
            session
            for session in self._sessions.values()
            if not session.disconnect_event.is_set()
        ]
        for session in sessions:
            session.disconnect_event.set()
        return len(sessions)

    def snapshot(self) -> list[dict[str, Any]]:
        monotonic_now = time.monotonic()
        return [
            {
                "id": session.id,
                "connected_at": session.connected_at.isoformat(),
                "last_activity_at": session.last_activity_at.isoformat(),
                "connected_seconds": round(monotonic_now - session.connected_monotonic, 1),
                "idle_seconds": round(monotonic_now - session.last_activity_monotonic, 1),
                "remote_host": session.remote_host,
                "user_agent": session.user_agent,
                "directory": session.directory,
                "requested_file": session.requested_file,
                "active_file": session.active_file,
                "disconnecting": session.disconnect_event.is_set(),
            }
            for session in sorted(self._sessions.values(), key=lambda item: item.connected_at)
        ]


def _sse(event: str, data: Any, event_id: int | None = None) -> str:
    parts = []
    if event_id is not None:
        parts.append(f"id: {event_id}")
    parts.append(f"event: {event}")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    parts.extend(f"data: {line}" for line in payload.splitlines())
    return "\n".join(parts) + "\n\n"


async def _stream_events(
    catalog: LogSourceCatalog,
    *,
    file: str | None,
    directory: Path | None,
    offset: int | None,
    source: str | None,
    tail: int,
    poll_interval: float = 0.1,
    stop_event: asyncio.Event | None = None,
    on_source: Callable[[Path | None], None] | None = None,
) -> AsyncIterator[str]:
    active: Path | None = None
    follower: JsonlFollower | None = None
    source_announced = False
    first_source = True
    heartbeat = 0
    while True:
        if stop_event is not None and stop_event.is_set():
            yield _sse("disconnect", {"reason": "Disconnected by administrator"})
            return
        try:
            desired = catalog.resolve(file, directory)
        except ValueError:
            desired = None
        if not source_announced or desired != active:
            if source_announced and active is not None:
                yield _sse("reset", {"reason": "log source changed"})
            active = desired
            follower = None
            source_announced = True
            if on_source is not None:
                on_source(active)
            yield _sse("source", {"file": None if active is None else active.name})
            if active is not None:
                follower = JsonlFollower(active)
                can_resume = first_source and offset is not None and source == active.name
                if can_resume:
                    follower.offset = offset
                else:
                    initial, truncated = _tail_records(active, tail)
                    yield _sse("history", {"older_records": truncated})
                    if initial:
                        follower.offset = initial[-1][0]
                        try:
                            stat = active.stat()
                            follower.identity = (stat.st_dev, stat.st_ino)
                        except FileNotFoundError:
                            pass
                    for record_offset, record in initial:
                        yield _sse("log", record, record_offset)
            first_source = False
        if follower is not None:
            reset, records = follower.read_available()
            if reset:
                yield _sse("reset", {"reason": "file replaced or truncated"})
            for record_offset, record in records:
                yield _sse("log", record, record_offset)
        heartbeat += 1
        if heartbeat >= 150:
            yield ": heartbeat\n\n"
            heartbeat = 0
        if stop_event is None:
            await asyncio.sleep(poll_interval)
        else:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=poll_interval)
            except TimeoutError:
                pass


def create_app(
    log_file: str | os.PathLike[str] | None,
    token: str,
    tail: int = 1_000,
    directory: str | os.PathLike[str] | None = None,
    admin_token: str | None = None,
):
    try:
        from fastapi import FastAPI, Header, HTTPException, Query
        from fastapi.responses import FileResponse, StreamingResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:
        raise RuntimeError('Install viewer dependencies with: pip install "glitchylogger[viewer]"') from exc

    if not token:
        raise ValueError("viewer token must not be empty")
    if admin_token is not None and hmac.compare_digest(admin_token, token):
        raise ValueError("admin token must differ from viewer token")
    if tail <= 0:
        raise ValueError("tail must be positive")

    catalog = LogSourceCatalog(
        fixed_file=None if log_file is None else Path(log_file),
        directory=None if directory is None else Path(directory),
    )
    assets = files("glitchylogger").joinpath("viewer_assets")
    app = FastAPI(title="GlitchyLogger Viewer", docs_url=None, redoc_url=None)
    session_registry = ViewerSessionRegistry()
    app.state.viewer_sessions = session_registry
    app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    def authorize(authorization: str | None) -> None:
        supplied = ""
        if authorization and authorization.startswith("Bearer "):
            supplied = authorization[7:]
        if not hmac.compare_digest(supplied, token):
            raise HTTPException(status_code=401, detail="unauthorized")

    def authorize_admin(authorization: str | None) -> None:
        if admin_token is None:
            raise HTTPException(status_code=404, detail="admin utility is disabled")
        supplied = ""
        if authorization and authorization.startswith("Bearer "):
            supplied = authorization[7:]
        if not hmac.compare_digest(supplied, admin_token):
            raise HTTPException(status_code=401, detail="unauthorized")

    @app.get("/")
    async def index():
        return FileResponse(str(assets.joinpath("index.html")))

    @app.get("/admin")
    async def admin_index():
        if admin_token is None:
            raise HTTPException(status_code=404, detail="admin utility is disabled")
        return FileResponse(str(assets.joinpath("admin.html")))

    @app.get("/healthz")
    async def healthz(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        authorize(authorization)
        path = catalog.resolve()
        return {
            "ok": True,
            "mode": "directory" if catalog.directory is not None else "file",
            "file": None if path is None else str(path),
            "exists": path is not None and path.is_file(),
        }

    @app.get("/api/logs/files")
    async def log_files(
        authorization: str | None = Header(default=None),
        directory: str | None = Query(default=None),
    ) -> dict[str, Any]:
        authorize(authorization)
        selected_directory = None if directory is None else Path(directory)
        try:
            current = catalog.resolve(directory=selected_directory)
            resolved_directory = (
                None if catalog.fixed_file is not None
                else catalog.resolve_directory(selected_directory)
            )
            described = catalog.describe(selected_directory)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "mode": "directory" if catalog.directory is not None else "file",
            "directory": None if resolved_directory is None else str(resolved_directory),
            "latest": None if current is None else current.name,
            "files": described,
        }

    @app.put("/api/logs/directory")
    async def set_log_directory(
        payload: dict[str, Any],
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        authorize(authorization)
        path = payload.get("path")
        if not isinstance(path, str) or not path.strip():
            raise HTTPException(status_code=400, detail="directory path is required")
        selected_directory = Path(path.strip())
        try:
            resolved_directory = catalog.resolve_directory(selected_directory)
            current = catalog.resolve(directory=selected_directory)
            described = catalog.describe(selected_directory)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "mode": "directory",
            "directory": str(resolved_directory),
            "latest": None if current is None else current.name,
            "files": described,
        }

    @app.get("/api/logs/directories")
    async def log_directories(
        authorization: str | None = Header(default=None),
        path: str | None = Query(default=None),
    ) -> dict[str, Any]:
        authorize(authorization)
        try:
            current, children = catalog.directories(None if path is None else Path(path))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        parent = current.parent
        return {
            "path": str(current),
            "parent": None if parent == current else str(parent),
            "directories": [
                {"name": child.name, "path": str(child)}
                for child in children
            ],
        }

    @app.get("/api/logs/stream")
    async def stream_logs(
        request: Request,
        authorization: str | None = Header(default=None),
        offset: int | None = Query(default=None, ge=0),
        file: str | None = Query(default=None),
        source: str | None = Query(default=None),
        directory: str | None = Query(default=None),
    ):
        authorize(authorization)
        selected_directory = None if directory is None else Path(directory)
        try:
            catalog.resolve(file, selected_directory)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        resolved_directory = (
            None
            if catalog.fixed_file is not None
            else str(catalog.resolve_directory(selected_directory))
        )
        session = session_registry.create(
            remote_host="" if request.client is None else request.client.host,
            user_agent=request.headers.get("user-agent", ""),
            directory=resolved_directory,
            requested_file=file,
        )

        async def tracked_events() -> AsyncIterator[str]:
            try:
                yield _sse("session", {"id": session.id})
                async for event in _stream_events(
                    catalog,
                    file=file,
                    directory=selected_directory,
                    offset=offset,
                    source=source,
                    tail=tail,
                    stop_event=session.disconnect_event,
                    on_source=lambda path: setattr(
                        session,
                        "active_file",
                        None if path is None else path.name,
                    ),
                ):
                    yield event
            finally:
                session_registry.remove(session.id)

        return StreamingResponse(
            tracked_events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/viewer/sessions/{session_id}/activity")
    async def viewer_activity(
        session_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, bool]:
        authorize(authorization)
        if not session_registry.touch(session_id):
            raise HTTPException(status_code=404, detail="viewer session is not connected")
        return {"ok": True}

    @app.get("/api/admin/sessions")
    async def admin_sessions(
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        authorize_admin(authorization)
        sessions = session_registry.snapshot()
        return {"count": len(sessions), "sessions": sessions}

    @app.delete("/api/admin/sessions")
    async def disconnect_all_viewers(
        authorization: str | None = Header(default=None),
    ) -> dict[str, int]:
        authorize_admin(authorization)
        return {"disconnected": session_registry.disconnect_all()}

    @app.delete("/api/admin/sessions/{session_id}")
    async def disconnect_viewer(
        session_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, bool]:
        authorize_admin(authorization)
        if not session_registry.disconnect(session_id):
            raise HTTPException(status_code=404, detail="viewer session is not connected")
        return {"ok": True}

    return app


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="View a JSONL log in a web browser")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path, help="single JSONL file to follow")
    source.add_argument(
        "--directory",
        type=Path,
        help="directory containing selectable .log and .jsonl files",
    )
    parser.add_argument("--host", default="127.0.0.1", help="bind address")
    parser.add_argument("--port", default=8765, type=int, help="bind port")
    parser.add_argument("--tail", default=1_000, type=int, help="initial record count")
    parser.add_argument("--token", help="viewer token (prefer environment or credential store)")
    parser.add_argument(
        "--admin-token",
        help="admin token (prefer environment or credential store)",
    )
    return parser


def main() -> None:
    parser = _parser()
    args = parser.parse_args()
    try:
        viewer_token = _resolve_secret(
            args.token,
            "GLITCHYLOGGER_VIEWER_TOKEN",
            _VIEWER_CREDENTIAL,
        )
        admin_token = _resolve_secret(
            args.admin_token,
            "GLITCHYLOGGER_ADMIN_TOKEN",
            _ADMIN_CREDENTIAL,
        )
    except RuntimeError as exc:
        parser.error(str(exc))
    if not viewer_token:
        parser.error(
            "set --token, GLITCHYLOGGER_VIEWER_TOKEN, or store the viewer token"
        )
    if not admin_token:
        parser.error(
            "set --admin-token, GLITCHYLOGGER_ADMIN_TOKEN, or store the admin token"
        )
    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit('Install viewer dependencies with: pip install "glitchylogger[viewer]"') from exc
    uvicorn.run(
        create_app(
            args.file,
            viewer_token,
            args.tail,
            directory=args.directory,
            admin_token=admin_token,
        ),
        host=args.host,
        port=args.port,
    )


if __name__ == "__main__":
    main()