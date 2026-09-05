from __future__ import annotations

import copy
import logging
import logging.handlers
import os
import pickle
import queue as _queue
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from .control import make_event_record
from .formatters import JsonLinesFormatter

_SIMPLE = (str, int, float, bool, type(None), list, tuple, dict, set)


def _fsync(stream: Any) -> None:
    try:
        stream.flush()
        os.fsync(stream.fileno())
    except (OSError, ValueError):
        pass


class SwitchableFileHandler(logging.Handler):
    """A file handler whose target can be swapped at runtime.

    Only the listener thread ever touches this handler, so the file is never
    open in more than one process and the swap needs no cross-process locking.
    """

    def __init__(self, path: Path, mode: str = "a", level: int = logging.NOTSET) -> None:
        super().__init__(level)
        self.setFormatter(JsonLinesFormatter())
        self._swap_lock = threading.RLock()
        self._path = Path(path)
        self._stream = self._open(self._path, mode)

    @property
    def path(self) -> Path:
        return self._path

    @staticmethod
    def _open(path: Path, mode: str) -> Any:
        path.parent.mkdir(parents=True, exist_ok=True)
        return open(path, mode, encoding="utf-8", newline="")

    def emit(self, record: logging.LogRecord) -> None:
        try:
            with self._swap_lock:
                self._write(record)
        except Exception:
            self.handleError(record)

    def _write(self, record: logging.LogRecord) -> None:
        self._stream.write(self.format(record) + "\n")
        self._stream.flush()

    def flush(self) -> None:
        with self._swap_lock:
            if not self._stream.closed:
                self._stream.flush()

    def close(self) -> None:
        with self._swap_lock:
            if not self._stream.closed:
                _fsync(self._stream)
                self._stream.close()
        super().close()

    def write_event(self, event: str, message: str, **fields: Any) -> None:
        with self._swap_lock:
            if not self._stream.closed:
                self._write(make_event_record(event, message, **fields))

    def reopen(self) -> bool:
        """Close and reopen the same path (SIGHUP-style refresh)."""
        with self._swap_lock:
            try:
                if not self._stream.closed:
                    _fsync(self._stream)
                    self._stream.close()
                self._stream = self._open(self._path, "a")
                return True
            except OSError:
                return False

    def switch_to(self, path: Path, mode: str = "a", migrate: bool = False, seq: int = 0) -> bool:
        """Retarget the handler. Returns False and keeps logging on failure."""
        with self._swap_lock:
            new_path = Path(path)
            if new_path == self._path and not migrate:
                return True

            old_path = self._path
            try:
                new_path.parent.mkdir(parents=True, exist_ok=True)
            except OSError:
                return False

            self.write_event(
                "log_switch_out",
                f"log continues in {new_path}",
                seq=seq,
                from_file=str(old_path),
                to_file=str(new_path),
            )
            if not self._stream.closed:
                _fsync(self._stream)
                self._stream.close()

            if migrate and old_path.exists():
                if not self._move(old_path, new_path):
                    self._stream = self._open(old_path, "a")
                    return False

            try:
                self._stream = self._open(new_path, mode)
            except OSError:
                self._stream = self._open(old_path, "a")
                return False

            self._path = new_path
            self.write_event(
                "log_switch_in",
                f"log continued from {old_path}",
                seq=seq,
                from_file=str(old_path),
                to_file=str(new_path),
            )
            return True

    @staticmethod
    def _move(src: Path, dst: Path) -> bool:
        for attempt in range(4):  # Windows AV/indexers hold handles briefly
            try:
                os.replace(src, dst)
                return True
            except OSError:
                try:
                    shutil.move(str(src), str(dst))
                    return True
                except OSError:
                    if attempt == 3:
                        return False
                    time.sleep(0.1)
        return False


class SafeQueueHandler(logging.handlers.QueueHandler):
    """Producer-side handler: prepares picklable records and applies backpressure."""

    def __init__(
        self,
        queue: Any,
        overflow: str = "discard",
        block_timeout: float = 1.0,
    ) -> None:
        super().__init__(queue)
        self.overflow = overflow
        self.block_timeout = block_timeout
        self.dropped = 0

    def prepare(self, record: logging.LogRecord) -> logging.LogRecord:
        record = copy.copy(record)
        record.msg = record.getMessage()
        record.args = None
        if record.exc_info:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
            record.exc_info = None
        try:
            pickle.dumps(record)
        except Exception:
            self._sanitize(record)
        return record

    @staticmethod
    def _sanitize(record: logging.LogRecord) -> None:
        for key, value in list(record.__dict__.items()):
            if isinstance(value, _SIMPLE):
                continue
            try:
                pickle.dumps(value)
            except Exception:
                record.__dict__[key] = repr(value)
                
    def enqueue(self, record: logging.LogRecord) -> None:
        if self.overflow == "block":
            self.queue.put(record)
            return
        
        try:
            self.queue.put_nowait(record)
            return
        except _queue.Full:
            pass
        
        if self.overflow == "discard" and record.levelno >= logging.WARNING:
            try:
                self.queue.put(record, timeout=self.block_timeout)
                return
            except _queue.Full:
                pass
        self.dropped += 1
