from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SetLogFile:
    seq: int 
    path: str
    mode: str = "a"
    migrate: bool = False


@dataclass(frozen=True)
class Reopen:
    seq: int


@dataclass(frozen=True)
class Flush:
    seq: int


@dataclass(frozen=True)
class Stop:
    seq: int


CONTROL = (SetLogFile, Reopen, Flush, Stop)


@dataclass(frozen=True)
class LoggingHandle:
    """Everything a child process needs to join the logging pipeline."""

    queue: Any
    shared: Any
    lock: Any
    level: int
    overflow: str
    block_timeout: float


def make_event_record(event: str, message: str, **fields: Any) -> logging.LogRecord:
    record = logging.LogRecord(
        name="core.logkit",
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg=message,
        args=None,
        exc_info=None,
    )
    record.event = event
    for key, value in fields.items():
        setattr(record, key, value)
    return record
