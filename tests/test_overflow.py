from __future__ import annotations

import logging
import queue as _queue
from pathlib import Path

from glitchylogger.logkit.handlers import SafeQueueHandler


class TinyQueue:
    """A bounded queue that never drains, to force the overflow path."""

    def __init__(self, maxsize: int) -> None:
        self.items: list = []
        self.maxsize = maxsize

    def put_nowait(self, item) -> None:
        if len(self.items) >= self.maxsize:
            raise _queue.Full
        self.items.append(item)

    def put(self, item, timeout=None) -> None:
        if len(self.items) >= self.maxsize:
            raise _queue.Full
        self.items.append(item)


def record(level: int) -> logging.LogRecord:
    return logging.LogRecord("t", level, __file__, 1, "m", None, None)


def test_discard_drops_info_but_keeps_warnings():
    handler = SafeQueueHandler(TinyQueue(2), overflow="discard", block_timeout=0.01)
    for _ in range(5):
        handler.emit(record(logging.INFO))
    assert handler.dropped == 3

    handler.emit(record(logging.ERROR))
    assert handler.dropped == 4  # queue is genuinely full, but it tried to block first


def test_discard_prefers_warnings_when_space_exists():
    q = TinyQueue(3)
    handler = SafeQueueHandler(q, overflow="discard", block_timeout=0.01)
    handler.emit(record(logging.WARNING))
    handler.emit(record(logging.INFO))
    handler.emit(record(logging.ERROR))
    assert handler.dropped == 0
    assert len(q.items) == 3


def test_drop_policy_never_blocks():
    handler = SafeQueueHandler(TinyQueue(1), overflow="drop", block_timeout=10.0)
    for _ in range(4):
        handler.emit(record(logging.CRITICAL))
    assert handler.dropped == 3


def test_block_policy_never_drops():
    q = TinyQueue(100)
    handler = SafeQueueHandler(q, overflow="block")
    for _ in range(50):
        handler.emit(record(logging.INFO))
    assert handler.dropped == 0
    assert len(q.items) == 50


def test_producer_survives_saturation(log_file: Path):
    from conftest import read_jsonl

    from glitchylogger import (
        LoggerConfig,
        configure_logging,
        flush_logs,
        get_dropped_count,
        get_logger,
    )

    configure_logging(
        LoggerConfig(
            file_path=log_file,
            console=False,
            level="DEBUG",
            queue_size=1,
            overflow="drop",
        )
    )
    log = get_logger("test.saturate")
    for i in range(500):
        log.info("burst-%d", i)
    assert flush_logs(timeout=30)

    written = len([r for r in read_jsonl(log_file) if "event" not in r])
    assert written + get_dropped_count() == 500
