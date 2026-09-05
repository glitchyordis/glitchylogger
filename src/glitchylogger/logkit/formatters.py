from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import sys
from typing import IO, Any

_RESERVED = {
    "args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName",
    "levelname", "levelno", "lineno", "module", "msecs", "message", "msg", "name",
    "pathname", "process", "processName", "relativeCreated", "stack_info",
    "taskName", "thread", "threadName",
}

_COLORS = {
    "DEBUG": "\033[36m",
    "INFO": "\033[32m",
    "WARNING": "\033[33m",
    "ERROR": "\033[31m",
    "CRITICAL": "\033[1;31m",
}
_RESET = "\033[0m"


def _iso(created: float) -> str:
    return _dt.datetime.fromtimestamp(created, tz=_dt.UTC).isoformat(
        timespec="milliseconds"
    )


def _extras(record: logging.LogRecord) -> dict[str, Any]:
    """
    Collects custom fields attached to the log record, excluding standard logging fields.
    """
    return {
        k: v
        for k, v in record.__dict__.items()
        if k not in _RESERVED and not k.startswith("_")
    }


def supports_color(stream: IO[str] | None) -> bool:
    if os.environ.get("NO_COLOR") is not None:
        return False
    if stream is None or not hasattr(stream, "isatty") or not stream.isatty():
        return False
    if sys.platform != "win32":
        return True
    try:  # enable VT sequences on the Windows console
        import ctypes

        handle = ctypes.windll.kernel32.GetStdHandle(-12)  # STD_ERROR_HANDLE
        mode = ctypes.c_uint32()
        if not ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(ctypes.windll.kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


class JsonLinesFormatter(logging.Formatter):
    """One compact JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": _iso(record.created),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "pid": record.process,
            "process": record.processName,
            "thread": record.threadName,
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        elif record.exc_text:
            payload["exc"] = record.exc_text
        if record.stack_info:
            payload["stack"] = record.stack_info
        payload.update(_extras(record))
        return json.dumps(payload, ensure_ascii=False, default=str)


class HumanFormatter(logging.Formatter):
    """Aligned, optionally coloured console output."""

    def __init__(self, color: bool = False) -> None:
        super().__init__()
        self.color = color

    def format(self, record: logging.LogRecord) -> str:
        extras = _extras(record)
        request_id = extras.pop("request_id", None)
        extras.pop("correlation_id", None)

        level = record.levelname
        if self.color:
            level = f"{_COLORS.get(record.levelname, '')}{record.levelname:<8}{_RESET}"
        else:
            level = f"{record.levelname:<8}"

        parts = [
            _iso(record.created),
            level,
            f"pid:{record.process} {record.threadName}",
            f"{record.name}:{record.lineno}",
        ]
        if request_id:
            parts.append(f"req={request_id}")
        line = " | ".join(parts) + " | " + record.getMessage()

        if extras:
            line += " | " + " ".join(f"{k}={v}" for k, v in extras.items())
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        elif record.exc_text:
            line += "\n" + record.exc_text
        return line
