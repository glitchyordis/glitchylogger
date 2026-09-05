from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest
from conftest import read_jsonl

from glitchylogger.logkit.handlers import SwitchableFileHandler


def record(msg: str) -> logging.LogRecord:
    return logging.LogRecord("t", logging.INFO, __file__, 1, msg, None, None)


@pytest.fixture
def handler(tmp_path: Path):
    h = SwitchableFileHandler(tmp_path / "logA.log")
    yield h
    h.close()


def test_writes_jsonl(handler: SwitchableFileHandler):
    handler.handle(record("one"))
    handler.handle(record("two"))
    handler.flush()
    assert [r["msg"] for r in read_jsonl(handler.path)] == ["one", "two"]


def test_creates_missing_directories(tmp_path: Path):
    handler = SwitchableFileHandler(tmp_path / "deep" / "nested" / "logA.log")
    handler.handle(record("one"))
    handler.close()
    assert (tmp_path / "deep" / "nested" / "logA.log").exists()


def test_switch_moves_new_records_to_new_file(handler: SwitchableFileHandler, tmp_path: Path):
    target = tmp_path / "logB.log"
    handler.handle(record("before"))
    assert handler.switch_to(target, seq=1)
    handler.handle(record("after"))
    handler.flush()

    assert [r["msg"] for r in read_jsonl(tmp_path / "logA.log") if "event" not in r] == ["before"]
    assert [r["msg"] for r in read_jsonl(target) if "event" not in r] == ["after"]


def test_breadcrumbs_bracket_the_switch(handler: SwitchableFileHandler, tmp_path: Path):
    target = tmp_path / "logB.log"
    handler.handle(record("before"))
    handler.switch_to(target, seq=7)
    handler.handle(record("after"))
    handler.flush()

    old = read_jsonl(tmp_path / "logA.log")
    new = read_jsonl(target)
    assert old[-1]["event"] == "log_switch_out"
    assert old[-1]["to_file"] == str(target)
    assert new[0]["event"] == "log_switch_in"
    assert new[0]["from_file"] == str(tmp_path / "logA.log")
    assert old[-1]["seq"] == new[0]["seq"] == 7


def test_switch_appends_to_existing_target(handler: SwitchableFileHandler, tmp_path: Path):
    target = tmp_path / "logB.log"
    target.write_text('{"msg": "pre-existing"}\n', encoding="utf-8")
    handler.switch_to(target, seq=1)
    handler.handle(record("after"))
    handler.flush()

    msgs = [r["msg"] for r in read_jsonl(target)]
    assert msgs[0] == "pre-existing"
    assert "after" in msgs


def test_switch_with_write_mode_truncates(handler: SwitchableFileHandler, tmp_path: Path):
    target = tmp_path / "logB.log"
    target.write_text('{"msg": "pre-existing"}\n', encoding="utf-8")
    handler.switch_to(target, mode="w", seq=1)
    handler.handle(record("after"))
    handler.flush()

    assert "pre-existing" not in [r.get("msg") for r in read_jsonl(target)]


def test_switch_to_same_path_is_noop(handler: SwitchableFileHandler, tmp_path: Path):
    handler.handle(record("one"))
    assert handler.switch_to(tmp_path / "logA.log", seq=1)
    handler.flush()
    assert not [r for r in read_jsonl(handler.path) if "event" in r]


def test_migrate_moves_old_file(handler: SwitchableFileHandler, tmp_path: Path):
    target = tmp_path / "moved" / "logB.log"
    handler.handle(record("before"))
    assert handler.switch_to(target, migrate=True, seq=1)
    handler.handle(record("after"))
    handler.flush()

    assert not (tmp_path / "logA.log").exists()
    msgs = [r["msg"] for r in read_jsonl(target) if "event" not in r]
    assert msgs == ["before", "after"]


def test_failed_switch_keeps_logging(handler: SwitchableFileHandler, tmp_path: Path):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")

    assert handler.switch_to(blocker / "logB.log", seq=1) is False
    handler.handle(record("still here"))
    handler.flush()

    assert handler.path == tmp_path / "logA.log"
    assert "still here" in [r["msg"] for r in read_jsonl(handler.path) if "event" not in r]


def test_reopen_keeps_same_path(handler: SwitchableFileHandler, tmp_path: Path):
    handler.handle(record("one"))
    assert handler.reopen()
    handler.handle(record("two"))
    handler.flush()
    assert handler.path == tmp_path / "logA.log"
    assert [r["msg"] for r in read_jsonl(handler.path)] == ["one", "two"]


def test_utf8_roundtrip(handler: SwitchableFileHandler):
    handler.handle(record("héllo wörld 日本語 🚀"))
    handler.flush()
    assert read_jsonl(handler.path)[0]["msg"] == "héllo wörld 日本語 🚀"


@pytest.mark.skipif(sys.platform != "win32", reason="line-ending translation is Windows-specific")
def test_line_endings_are_lf_only(handler: SwitchableFileHandler):
    handler.handle(record("one"))
    handler.flush()
    assert b"\r\n" not in handler.path.read_bytes()
