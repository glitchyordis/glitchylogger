from __future__ import annotations

import asyncio
import getpass
import json
from pathlib import Path

import pytest

from glitchylogger.viewer import (
    JsonlFollower,
    LogSourceCatalog,
    _resolve_secret,
    _store_credentials,
    _stream_events,
    _tail_records,
    store_credentials,
    tail_records,
)


def append_record(path: Path, record: dict, newline: bool = True) -> None:
    with path.open("ab") as stream:
        stream.write(json.dumps(record).encode("utf-8"))
        if newline:
            stream.write(b"\n")


def test_tail_records_returns_last_complete_records(tmp_path: Path):
    path = tmp_path / "app.jsonl"
    for index in range(5):
        append_record(path, {"msg": f"record-{index}"})

    records = tail_records(path, limit=3)

    assert [record["msg"] for _, record in records] == ["record-2", "record-3", "record-4"]
    assert records[-1][0] == path.stat().st_size


def test_tail_records_reports_older_history(tmp_path: Path):
    path = tmp_path / "app.jsonl"
    for index in range(4):
        append_record(path, {"msg": f"record-{index}"})

    records, truncated = _tail_records(path, limit=3)

    assert truncated
    assert [record["msg"] for _, record in records] == ["record-1", "record-2", "record-3"]


def test_tail_records_ignores_incomplete_final_line(tmp_path: Path):
    path = tmp_path / "app.jsonl"
    append_record(path, {"msg": "complete"})
    append_record(path, {"msg": "partial"}, newline=False)

    records = tail_records(path)

    assert [record["msg"] for _, record in records] == ["complete"]


def test_malformed_line_becomes_visible_parse_error(tmp_path: Path):
    path = tmp_path / "app.jsonl"
    path.write_bytes(b"not-json\n")

    [(offset, record)] = tail_records(path)

    assert offset == len(b"not-json\n")
    assert record["level"] == "PARSE_ERROR"
    assert record["msg"] == "not-json"
    assert "parse_error" in record


def test_follower_waits_for_line_completion(tmp_path: Path):
    path = tmp_path / "app.jsonl"
    path.write_bytes(b'{"msg":"split')
    follower = JsonlFollower(path)

    assert follower.read_available() == (False, [])
    with path.open("ab") as stream:
        stream.write(b' write"}\n')

    reset, records = follower.read_available()

    assert not reset
    assert [record["msg"] for _, record in records] == ["split write"]
    assert follower.offset == path.stat().st_size


def test_follower_emits_only_appended_records(tmp_path: Path):
    path = tmp_path / "app.jsonl"
    append_record(path, {"msg": "first"})
    follower = JsonlFollower(path)

    _, first = follower.read_available()
    append_record(path, {"msg": "second"})
    _, second = follower.read_available()

    assert [record["msg"] for _, record in first] == ["first"]
    assert [record["msg"] for _, record in second] == ["second"]


def test_follower_resets_after_truncation(tmp_path: Path):
    path = tmp_path / "app.jsonl"
    append_record(path, {"msg": "a much longer first record"})
    follower = JsonlFollower(path)
    follower.read_available()
    path.write_text('{"msg":"new"}\n', encoding="utf-8")

    reset, records = follower.read_available()

    assert reset
    assert [record["msg"] for _, record in records] == ["new"]


def test_reconnecting_past_truncated_file_resets(tmp_path: Path):
    path = tmp_path / "app.jsonl"
    append_record(path, {"msg": "new"})
    follower = JsonlFollower(path, offset=10_000)

    reset, records = follower.read_available()

    assert reset
    assert [record["msg"] for _, record in records] == ["new"]


def test_directory_catalog_lists_newest_log_first(tmp_path: Path):
    old = tmp_path / "old.log"
    new = tmp_path / "new.jsonl"
    ignored = tmp_path / "notes.txt"
    append_record(old, {"msg": "old"})
    append_record(new, {"msg": "new"})
    ignored.write_text("not a log", encoding="utf-8")
    old.touch()
    new.touch()
    old_stat = old.stat()
    new_stat = new.stat()
    import os

    os.utime(old, ns=(old_stat.st_atime_ns, new_stat.st_mtime_ns - 1_000_000))

    catalog = LogSourceCatalog(directory=tmp_path)

    assert [path.name for path in catalog.files()] == ["new.jsonl", "old.log"]
    assert catalog.resolve() == new.resolve()
    assert catalog.resolve("old.log") == old.resolve()


def test_directory_catalog_rejects_traversal(tmp_path: Path):
    catalog = LogSourceCatalog(directory=tmp_path)

    with pytest.raises(ValueError, match="invalid"):
        catalog.resolve("../secret.log")


def test_directory_catalog_resolves_alternate_directory_without_mutation(tmp_path: Path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    append_record(second / "app.log", {"msg": "second"})
    catalog = LogSourceCatalog(directory=first)

    assert catalog.resolve(directory=second) == (second / "app.log").resolve()
    assert catalog.directory == first.resolve()
    assert catalog.resolve() is None


def test_directory_catalog_browses_child_directories(tmp_path: Path):
    (tmp_path / "Zulu").mkdir()
    (tmp_path / "alpha").mkdir()
    (tmp_path / "file.log").touch()
    catalog = LogSourceCatalog(directory=tmp_path)

    current, children = catalog.directories()

    assert current == tmp_path.resolve()
    assert [path.name for path in children] == ["alpha", "Zulu"]


def test_viewer_page_and_assets_are_served(tmp_path: Path):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from glitchylogger.viewer import create_app

    with TestClient(create_app(tmp_path / "app.jsonl", "secret")) as client:
        page = client.get("/")
        script = client.get("/assets/viewer.js")

    assert page.status_code == 200
    assert "GlitchyLogger Viewer" in page.text
    assert '<span id="connectionDot"' in page.text
    assert '<span id="connectionText" class="connection-status"' in page.text
    assert '<span class="status-label">Live</span>' not in page.text
    assert script.status_code == 200
    assert "Authorization" in script.text


def test_health_endpoint_requires_bearer_token(tmp_path: Path):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from glitchylogger.viewer import create_app

    with TestClient(create_app(tmp_path / "app.jsonl", "secret")) as client:
        assert client.get("/healthz").status_code == 401
        assert client.get("/healthz", headers={"Authorization": "Bearer wrong"}).status_code == 401
        response = client.get("/healthz", headers={"Authorization": "Bearer secret"})

    assert response.status_code == 200
    assert response.json()["exists"] is False


def test_directory_endpoint_lists_files_and_rejects_traversal(tmp_path: Path):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from glitchylogger.viewer import create_app

    append_record(tmp_path / "first.log", {"msg": "first"})
    append_record(tmp_path / "second.jsonl", {"msg": "second"})
    headers = {"Authorization": "Bearer secret"}
    with TestClient(create_app(None, "secret", directory=tmp_path)) as client:
        response = client.get("/api/logs/files", headers=headers)
        traversal = client.get(
            "/api/logs/stream",
            params={"file": "../secret.log"},
            headers=headers,
        )

    assert response.status_code == 200
    assert response.json()["mode"] == "directory"
    assert {item["name"] for item in response.json()["files"]} == {
        "first.log",
        "second.jsonl",
    }
    assert traversal.status_code == 400


def test_directory_endpoint_selects_source_without_changing_other_clients(tmp_path: Path):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from glitchylogger.viewer import create_app

    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    append_record(second / "switched.log", {"msg": "switched"})
    headers = {"Authorization": "Bearer secret"}

    with TestClient(create_app(None, "secret", directory=first)) as client:
        response = client.put(
            "/api/logs/directory",
            json={"path": str(second)},
            headers=headers,
        )
        default_files = client.get("/api/logs/files", headers=headers)
        selected_files = client.get(
            "/api/logs/files",
            params={"directory": str(second)},
            headers=headers,
        )

    assert response.status_code == 200
    assert response.json()["directory"] == str(second.resolve())
    assert response.json()["latest"] == "switched.log"
    assert default_files.json()["directory"] == str(first.resolve())
    assert default_files.json()["files"] == []
    assert selected_files.json()["directory"] == str(second.resolve())
    assert selected_files.json()["latest"] == "switched.log"


def test_three_streams_receive_independent_file_updates(tmp_path: Path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    shared = first / "shared.log"
    other = second / "other.log"
    shared.touch()
    other.touch()
    catalog = LogSourceCatalog(directory=first)

    async def event_data(stream, expected_event: str) -> dict:
        frame = await asyncio.wait_for(anext(stream), timeout=1)
        lines = frame.splitlines()
        assert f"event: {expected_event}" in lines
        data = next(line[6:] for line in lines if line.startswith("data: "))
        return json.loads(data)

    async def scenario() -> None:
        streams = [
            _stream_events(
                catalog,
                file="shared.log",
                directory=first,
                offset=None,
                source=None,
                tail=100,
                poll_interval=0.001,
            ),
            _stream_events(
                catalog,
                file="shared.log",
                directory=first,
                offset=None,
                source=None,
                tail=100,
                poll_interval=0.001,
            ),
            _stream_events(
                catalog,
                file="other.log",
                directory=second,
                offset=None,
                source=None,
                tail=100,
                poll_interval=0.001,
            ),
        ]
        try:
            sources = await asyncio.gather(*(event_data(stream, "source") for stream in streams))
            assert [payload["file"] for payload in sources] == [
                "shared.log",
                "shared.log",
                "other.log",
            ]
            await asyncio.gather(*(event_data(stream, "history") for stream in streams))

            append_record(shared, {"msg": "shared update"})
            append_record(other, {"msg": "other update"})

            updates = await asyncio.gather(*(event_data(stream, "log") for stream in streams))
            assert [payload["msg"] for payload in updates] == [
                "shared update",
                "shared update",
                "other update",
            ]
        finally:
            await asyncio.gather(*(stream.aclose() for stream in streams))

    asyncio.run(scenario())


def test_stream_resumes_from_offset_without_replaying_history(tmp_path: Path):
    path = tmp_path / "app.log"
    append_record(path, {"msg": "first"})
    append_record(path, {"msg": "second"})
    first_offset = tail_records(path)[0][0]
    catalog = LogSourceCatalog(fixed_file=path)

    async def scenario() -> None:
        stream = _stream_events(
            catalog,
            file=None,
            directory=None,
            offset=first_offset,
            source=path.name,
            tail=100,
            poll_interval=0.001,
        )
        try:
            source_frame = await asyncio.wait_for(anext(stream), timeout=1)
            resumed_frame = await asyncio.wait_for(anext(stream), timeout=1)
            assert "event: source" in source_frame
            assert "event: history" not in resumed_frame
            assert "event: log" in resumed_frame
            assert '"msg":"second"' in resumed_frame
            assert '"msg":"first"' not in resumed_frame
        finally:
            await stream.aclose()

    asyncio.run(scenario())


def test_automatic_stream_switches_to_newest_file(tmp_path: Path):
    import os

    old = tmp_path / "old.log"
    old.touch()
    os.utime(old, ns=(1_000_000, 1_000_000))
    catalog = LogSourceCatalog(directory=tmp_path)

    async def scenario() -> None:
        stream = _stream_events(
            catalog,
            file=None,
            directory=tmp_path,
            offset=None,
            source=None,
            tail=100,
            poll_interval=0.001,
        )
        try:
            assert 'data: {"file":"old.log"}' in await asyncio.wait_for(
                anext(stream), timeout=1
            )
            assert "event: history" in await asyncio.wait_for(anext(stream), timeout=1)

            new = tmp_path / "new.log"
            append_record(new, {"msg": "newest"})

            assert "event: reset" in await asyncio.wait_for(anext(stream), timeout=1)
            assert 'data: {"file":"new.log"}' in await asyncio.wait_for(
                anext(stream), timeout=1
            )
            assert "event: history" in await asyncio.wait_for(anext(stream), timeout=1)
            record = await asyncio.wait_for(anext(stream), timeout=1)
            assert "event: log" in record
            assert '"msg":"newest"' in record
        finally:
            await stream.aclose()

    asyncio.run(scenario())


def test_stream_announces_empty_directory(tmp_path: Path):
    catalog = LogSourceCatalog(directory=tmp_path)

    async def scenario() -> None:
        stream = _stream_events(
            catalog,
            file=None,
            directory=tmp_path,
            offset=None,
            source=None,
            tail=100,
            poll_interval=0.001,
        )
        try:
            frame = await asyncio.wait_for(anext(stream), timeout=1)
            assert "event: source" in frame
            assert 'data: {"file":null}' in frame
        finally:
            await stream.aclose()

    asyncio.run(scenario())


def test_stream_emits_admin_disconnect_event(tmp_path: Path):
    path = tmp_path / "app.log"
    path.touch()
    catalog = LogSourceCatalog(fixed_file=path)

    async def scenario() -> None:
        stop_event = asyncio.Event()
        stop_event.set()
        stream = _stream_events(
            catalog,
            file=None,
            directory=None,
            offset=None,
            source=None,
            tail=100,
            poll_interval=0.001,
            stop_event=stop_event,
        )
        try:
            frame = await asyncio.wait_for(anext(stream), timeout=1)
            assert "event: disconnect" in frame
            assert "Disconnected by administrator" in frame
        finally:
            await stream.aclose()

    asyncio.run(scenario())


def test_admin_sessions_use_separate_token_and_track_activity(tmp_path: Path):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from glitchylogger.viewer import create_app

    path = tmp_path / "app.log"
    path.touch()
    app = create_app(path, "viewer-secret", admin_token="admin-secret")
    session = app.state.viewer_sessions.create(
        remote_host="192.0.2.10",
        user_agent="Test browser",
        directory=None,
        requested_file=None,
    )
    session.connected_monotonic -= 60
    session.last_activity_monotonic -= 20
    viewer_headers = {"Authorization": "Bearer viewer-secret"}
    admin_headers = {"Authorization": "Bearer admin-secret"}

    with TestClient(app) as client:
        assert client.get("/admin").status_code == 200
        assert client.get("/api/admin/sessions", headers=viewer_headers).status_code == 401
        assert client.get("/api/logs/files", headers=admin_headers).status_code == 401

        response = client.get("/api/admin/sessions", headers=admin_headers)
        assert response.status_code == 200
        [payload] = response.json()["sessions"]
        assert payload["id"] == session.id
        assert payload["remote_host"] == "192.0.2.10"
        assert payload["user_agent"] == "Test browser"
        assert payload["connected_seconds"] >= 60
        assert payload["idle_seconds"] >= 20

        activity = client.post(
            f"/api/viewer/sessions/{session.id}/activity",
            headers=viewer_headers,
        )
        assert activity.status_code == 200
        refreshed = client.get("/api/admin/sessions", headers=admin_headers).json()
        assert refreshed["sessions"][0]["idle_seconds"] < 1

        denied = client.delete(
            f"/api/admin/sessions/{session.id}",
            headers=viewer_headers,
        )
        disconnected = client.delete(
            f"/api/admin/sessions/{session.id}",
            headers=admin_headers,
        )
        activity_after_disconnect = client.post(
            f"/api/viewer/sessions/{session.id}/activity",
            headers=viewer_headers,
        )
        missing_disconnect = client.delete(
            "/api/admin/sessions/missing",
            headers=admin_headers,
        )

    assert denied.status_code == 401
    assert disconnected.status_code == 200
    assert activity_after_disconnect.status_code == 404
    assert missing_disconnect.status_code == 404
    assert session.disconnect_event.is_set()


def test_admin_utility_requires_distinct_token(tmp_path: Path):
    pytest.importorskip("fastapi")
    from glitchylogger.viewer import create_app

    with pytest.raises(ValueError, match="must differ"):
        create_app(tmp_path / "app.log", "shared", admin_token="shared")


def test_admin_can_disconnect_all_viewer_sessions(tmp_path: Path):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from glitchylogger.viewer import create_app

    app = create_app(tmp_path / "app.log", "viewer-secret", admin_token="admin-secret")
    sessions = [
        app.state.viewer_sessions.create(
            remote_host=f"192.0.2.{index}",
            user_agent="Test browser",
            directory=None,
            requested_file=None,
        )
        for index in range(1, 4)
    ]

    with TestClient(app) as client:
        denied = client.delete(
            "/api/admin/sessions",
            headers={"Authorization": "Bearer viewer-secret"},
        )
        response = client.delete(
            "/api/admin/sessions",
            headers={"Authorization": "Bearer admin-secret"},
        )
        repeated = client.delete(
            "/api/admin/sessions",
            headers={"Authorization": "Bearer admin-secret"},
        )

    assert denied.status_code == 401
    assert response.status_code == 200
    assert response.json() == {"disconnected": 3}
    assert repeated.status_code == 200
    assert repeated.json() == {"disconnected": 0}
    assert all(session.disconnect_event.is_set() for session in sessions)


def test_disconnect_all_with_no_sessions_is_successful(tmp_path: Path):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from glitchylogger.viewer import create_app

    app = create_app(tmp_path / "app.log", "viewer-secret", admin_token="admin-secret")
    with TestClient(app) as client:
        response = client.delete(
            "/api/admin/sessions",
            headers={"Authorization": "Bearer admin-secret"},
        )

    assert response.status_code == 200
    assert response.json() == {"disconnected": 0}


def test_admin_routes_are_disabled_without_admin_token(tmp_path: Path):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from glitchylogger.viewer import create_app

    with TestClient(create_app(tmp_path / "app.log", "viewer-secret")) as client:
        page = client.get("/admin")
        sessions = client.get(
            "/api/admin/sessions",
            headers={"Authorization": "Bearer anything"},
        )
        disconnect_all = client.delete(
            "/api/admin/sessions",
            headers={"Authorization": "Bearer anything"},
        )

    assert page.status_code == 404
    assert sessions.status_code == 404
    assert disconnect_all.status_code == 404


def test_admin_page_includes_bulk_disconnect_assets(tmp_path: Path):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from glitchylogger.viewer import create_app

    with TestClient(
        create_app(tmp_path / "app.log", "viewer-secret", admin_token="admin-secret")
    ) as client:
        page = client.get("/admin")
        script = client.get("/assets/admin.js")

    assert page.status_code == 200
    assert 'id="disconnectAllButton"' in page.text
    assert script.status_code == 200
    assert 'method: "DELETE"' in script.text
    assert 'window.confirm("Disconnect all active viewers?")' in script.text


def test_directory_endpoint_rejects_missing_directory(tmp_path: Path):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from glitchylogger.viewer import create_app

    headers = {"Authorization": "Bearer secret"}
    with TestClient(create_app(None, "secret", directory=tmp_path)) as client:
        response = client.put(
            "/api/logs/directory",
            json={"path": str(tmp_path / "missing")},
            headers=headers,
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "log directory does not exist"


def test_directory_endpoint_rejects_single_file_mode(tmp_path: Path):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from glitchylogger.viewer import create_app

    headers = {"Authorization": "Bearer secret"}
    with TestClient(create_app(tmp_path / "app.log", "secret")) as client:
        response = client.put(
            "/api/logs/directory",
            json={"path": str(tmp_path)},
            headers=headers,
        )

    assert response.status_code == 400
    assert "single-file mode" in response.json()["detail"]


def test_directory_browser_endpoint_lists_server_folders(tmp_path: Path):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from glitchylogger.viewer import create_app

    child = tmp_path / "child"
    child.mkdir()
    headers = {"Authorization": "Bearer secret"}
    with TestClient(create_app(None, "secret", directory=tmp_path)) as client:
        response = client.get("/api/logs/directories", headers=headers)
        missing = client.get(
            "/api/logs/directories",
            params={"path": str(tmp_path / "missing")},
            headers=headers,
        )

    assert response.status_code == 200
    assert response.json()["path"] == str(tmp_path.resolve())
    assert response.json()["directories"] == [
        {"name": "child", "path": str(child.resolve())}
    ]
    assert missing.status_code == 400


def test_create_app_rejects_empty_token(tmp_path: Path):
    pytest.importorskip("fastapi")
    from glitchylogger.viewer import create_app

    with pytest.raises(ValueError, match="token"):
        create_app(tmp_path / "app.jsonl", "")


def test_create_app_rejects_nonpositive_tail(tmp_path: Path):
    pytest.importorskip("fastapi")
    from glitchylogger.viewer import create_app

    with pytest.raises(ValueError, match="tail"):
        create_app(tmp_path / "app.jsonl", "secret", tail=0)


def test_resolve_secret_prefers_explicit_value(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TEST_VIEWER_TOKEN", "environment-secret")

    value = _resolve_secret(
        "explicit-secret",
        "TEST_VIEWER_TOKEN",
        "viewer-token",
        lambda *_: pytest.fail("credential store should not be read"),
    )

    assert value == "explicit-secret"


def test_resolve_secret_prefers_environment_over_credential_store(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("TEST_VIEWER_TOKEN", "environment-secret")

    value = _resolve_secret(
        None,
        "TEST_VIEWER_TOKEN",
        "viewer-token",
        lambda *_: pytest.fail("credential store should not be read"),
    )

    assert value == "environment-secret"


def test_resolve_secret_uses_system_credential_store(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("TEST_VIEWER_TOKEN", raising=False)
    calls: list[tuple[str, str]] = []

    def read_credential(service: str, name: str) -> str:
        calls.append((service, name))
        return "stored-secret"

    value = _resolve_secret(
        None, "TEST_VIEWER_TOKEN", "viewer-token", read_credential
    )

    assert value == "stored-secret"
    assert calls == [("glitchylogger", "viewer-token")]


def test_resolve_secret_returns_none_when_no_credential(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("TEST_VIEWER_TOKEN", raising=False)

    value = _resolve_secret(None, "TEST_VIEWER_TOKEN", "viewer-token", lambda *_: None)

    assert value is None


def test_resolve_secret_sanitizes_credential_store_failure(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("TEST_VIEWER_TOKEN", raising=False)

    def fail_read(*_: str) -> str:
        raise OSError("backend details")

    with pytest.raises(RuntimeError, match="could not read viewer-token") as error:
        _resolve_secret(None, "TEST_VIEWER_TOKEN", "viewer-token", fail_read)

    assert "backend details" not in str(error.value)


def test_store_credentials_writes_distinct_tokens():
    answers = iter(["viewer-secret", "admin-secret"])
    writes: list[tuple[str, str, str]] = []

    _store_credentials(lambda _: next(answers), lambda *args: writes.append(args))

    assert writes == [
        ("glitchylogger", "viewer-token", "viewer-secret"),
        ("glitchylogger", "admin-token", "admin-secret"),
    ]


@pytest.mark.parametrize("answers", [("", "admin-secret"), ("same", "same")])
def test_store_credentials_rejects_invalid_tokens(answers: tuple[str, str]):
    values = iter(answers)

    with pytest.raises(ValueError):
        _store_credentials(
            lambda _: next(values),
            lambda *_: pytest.fail("invalid credentials must not be stored"),
        )


def test_store_credentials_does_not_expose_token_on_backend_failure(
    monkeypatch: pytest.MonkeyPatch,
):
    keyring = pytest.importorskip("keyring")
    answers = iter(["viewer-secret", "admin-secret"])
    monkeypatch.setattr(getpass, "getpass", lambda _: next(answers))

    def fail_write(*_: str) -> None:
        raise OSError("backend rejected viewer-secret")

    monkeypatch.setattr(keyring, "set_password", fail_write)

    with pytest.raises(SystemExit) as error:
        store_credentials()

    assert "viewer-secret" not in str(error.value)
    assert "system store" in str(error.value)