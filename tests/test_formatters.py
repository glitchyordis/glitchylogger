from __future__ import annotations

import json
import logging

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
    payload = json.loads(JsonLinesFormatter().format(make_record()))
    for key in ("ts", "level", "logger", "msg", "pid", "process", "thread", "module", "func", "line"):
        assert key in payload
    assert payload["msg"] == "hello world"
    assert payload["level"] == "INFO"


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
    line = HumanFormatter(color=False).format(make_record())
    assert "INFO" in line
    assert "hello world" in line
    assert "\033[" not in line


def test_human_formatter_colored():
    assert "\033[" in HumanFormatter(color=True).format(make_record())


def test_human_formatter_shows_request_id():
    record = make_record()
    record.request_id = "req-9"
    assert "req=req-9" in HumanFormatter(color=False).format(record)
