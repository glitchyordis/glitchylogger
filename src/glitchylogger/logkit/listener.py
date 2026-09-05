from __future__ import annotations

import logging
import queue as _queue
import sys
import threading
import traceback
from pathlib import Path
from typing import Any

from .control import Flush, Reopen, SetLogFile, Stop, make_event_record
from .handlers import SwitchableFileHandler


class LogListener(threading.Thread):
    """The single consumer. Owns the only file handle in the whole application."""

    def __init__(
        self,
        queue: Any,
        shared: Any,
        file_handler: SwitchableFileHandler,
        console_handler: logging.Handler | None,
    ) -> None:
        super().__init__(name="mpmt-log-listener", daemon=True)
        self.queue = queue
        self.shared = shared
        self.file_handler = file_handler
        self.console_handler = console_handler

    def run(self) -> None:
        while True:
            try:
                item = self.queue.get()
            except (EOFError, OSError, BrokenPipeError):
                break
            try:
                if isinstance(item, Stop):
                    self._drain()
                    self._close(item.seq)
                    break
                self._dispatch(item)
            except Exception:  # a listener that dies takes the whole app's logs with it
                traceback.print_exc(file=sys.stderr)

    def _drain(self) -> None:
        while True:
            try:
                item = self.queue.get_nowait()
            except (_queue.Empty, EOFError, OSError):
                return
            if isinstance(item, Stop):
                continue
            try:
                self._dispatch(item)
            except Exception:
                traceback.print_exc(file=sys.stderr)

    def _dispatch(self, item: Any) -> None:
        if isinstance(item, SetLogFile):
            ok = self.file_handler.switch_to(Path(item.path), item.mode, item.migrate, item.seq)
            self._notify_console(
                "log_switch",
                f"log file -> {self.file_handler.path}" if ok else f"log file switch FAILED -> {item.path}",
                seq=item.seq,
                ok=ok,
            )
            self._applied(item.seq)
        elif isinstance(item, Reopen):
            self.file_handler.reopen()
            self._applied(item.seq)
        elif isinstance(item, Flush):
            self.file_handler.flush()
            self._applied(item.seq)
        elif isinstance(item, logging.LogRecord):
            self._emit(item)

    def _emit(self, record: logging.LogRecord) -> None:
        if self.console_handler is not None and record.levelno >= self.console_handler.level:
            self.console_handler.handle(record)
        if record.levelno >= self.file_handler.level:
            self.file_handler.handle(record)

    def _notify_console(self, event: str, message: str, **fields: Any) -> None:
        if self.console_handler is not None:
            self.console_handler.handle(make_event_record(event, message, **fields))

    def _applied(self, seq: int) -> None:
        try:
            self.shared["file_path"] = str(self.file_handler.path)
            self.shared["applied_seq"] = seq
        except (EOFError, OSError, BrokenPipeError):
            pass

    def _close(self, seq: int) -> None:
        self.file_handler.write_event("log_close", "logging shut down", seq=seq)
        self._applied(seq)
        self.file_handler.close()
        if self.console_handler is not None:
            self.console_handler.flush()
