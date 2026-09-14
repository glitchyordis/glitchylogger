from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from glitchylogger.logkit.formatters import HumanFormatter, JsonLinesFormatter


def make_record(**kwargs) -> logging.LogRecord:
    defaults = dict(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=42,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    defaults.update(kwargs)
    return logging.LogRecord(**defaults)


def test_json_has_required_keys():
    record = make_record()
    payload = json.loads(JsonLinesFormatter().format(record))
    for key in (
        "ts", "level", "logger", "msg", "pid", "process", "thread", "module",
        "pathname", "func", "line",
    ):
        assert key in payload
    assert payload["msg"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["pathname"] == record.pathname
    assert payload["func"] == record.funcName
    assert "funcName" not in payload


def test_json_shortens_pathname_relative_to_selected_base(tmp_path):
    pathname = tmp_path / "src" / "package" / "service.py"
    record = make_record(pathname=str(pathname))
    payload = json.loads(
        JsonLinesFormatter(source_path_base=tmp_path).format(record)
    )
    assert payload["pathname"] == str(Path("src") / "package" / "service.py")


def test_json_keeps_pathname_outside_selected_base(tmp_path):
    pathname = tmp_path / "dependency" / "service.py"
    base = tmp_path / "application"
    record = make_record(pathname=str(pathname))
    payload = json.loads(JsonLinesFormatter(source_path_base=base).format(record))
    assert payload["pathname"] == str(pathname)


def test_json_includes_extras():
    record = make_record()
    record.request_id = "abc-123"
    record.user = {"id": 7}
    payload = json.loads(JsonLinesFormatter().format(record))
    assert payload["request_id"] == "abc-123"
    assert payload["user"] == {"id": 7}


def test_json_survives_unserialisable_extra():
    record = make_record()
    record.thing = object()
    payload = json.loads(JsonLinesFormatter().format(record))
    assert "object at" in payload["thing"]


def test_json_renders_exception():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = make_record(exc_info=sys.exc_info())
    payload = json.loads(JsonLinesFormatter().format(record))
    assert "ValueError: boom" in payload["exc"]


def test_json_is_single_line():
    record = make_record(msg="line1\nline2", args=None)
    assert "\n" not in JsonLinesFormatter().format(record)


def test_human_formatter_plain():
    record = make_record()
    line = HumanFormatter(color=False).format(record)
    assert "INFO" in line
    assert "hello world" in line
    assert record.pathname in line
    assert f"->{record.funcName}():42" in line
    assert "\033[" not in line


def test_human_formatter_shortens_pathname_relative_to_selected_base(tmp_path):
    pathname = tmp_path / "src" / "package" / "service.py"
    record = make_record(pathname=str(pathname))
    line = HumanFormatter(color=False, source_path_base=tmp_path).format(record)
    assert f"src{os.sep}package{os.sep}service.py->{record.funcName}():42" in line
    assert str(tmp_path) not in line


def test_human_formatter_colored():
    assert "\033[" in HumanFormatter(color=True).format(make_record())


def test_human_formatter_shows_request_id():
    record = make_record()
    record.request_id = "req-9"
    assert "req=req-9" in HumanFormatter(color=False).format(record)
