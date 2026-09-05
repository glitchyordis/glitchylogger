from __future__ import annotations

import atexit
import logging
import multiprocessing
import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import LoggerConfig, resolve_target
from .context import ContextFilter
from .control import Flush, LoggingHandle, Reopen, SetLogFile, Stop
from .formatters import HumanFormatter, supports_color
from .handlers import SafeQueueHandler, SwitchableFileHandler
from .listener import LogListener


@dataclass
class _Runtime:
    queue: Any
    shared: Any
    lock: Any
    handler: SafeQueueHandler
    config: LoggerConfig | None
    listener: LogListener | None
    manager: Any
    owner_pid: int | None


_RUNTIME: _Runtime | None = None
_LOCK = threading.RLock()


def _require() -> _Runtime:
    if _RUNTIME is None:
        raise RuntimeError("logging is not configured; call configure_logging() first")
    return _RUNTIME


def _is_owner(runtime: _Runtime) -> bool:
    return runtime.owner_pid == os.getpid()


def _install_root_handler(handler: SafeQueueHandler, level: int) -> None:
    root = logging.getLogger()
    for existing in list(root.handlers):
        if isinstance(existing, SafeQueueHandler):
            root.removeHandler(existing)
    handler.setLevel(logging.NOTSET)
    handler.addFilter(ContextFilter())
    root.addHandler(handler)
    root.setLevel(level)


def configure_logging(config: LoggerConfig | None = None, **overrides: Any) -> LoggingHandle:
    """Start the logging pipeline. Idempotent; safe to call from a child process."""
    global _RUNTIME
    with _LOCK:
        if _RUNTIME is not None:
            if not _is_owner(_RUNTIME):
                # A child must never start a second listener.
                _install_root_handler(_RUNTIME.handler, _RUNTIME.handler.level)
            return get_logging_handle()

        if config is None:
            config = LoggerConfig(**overrides) if overrides else LoggerConfig.from_env()
        elif overrides:
            raise TypeError("pass either a LoggerConfig or keyword overrides, not both")

        manager = multiprocessing.Manager()
        queue = manager.Queue(maxsize=config.queue_size)
        shared = manager.dict(
            {"file_path": str(config.file_path), "seq": 0, "applied_seq": 0}
        )
        lock = manager.Lock()

        file_handler = SwitchableFileHandler(config.file_path, level=int(config.file_level))
        console_handler: logging.Handler | None = None
        if config.console:
            console_handler = logging.StreamHandler(sys.stderr)
            console_handler.setLevel(int(config.console_level))
            color = supports_color(sys.stderr) if config.color is None else config.color
            console_handler.setFormatter(HumanFormatter(color=color))

        listener = LogListener(queue, shared, file_handler, console_handler)
        listener.start()

        handler = SafeQueueHandler(queue, config.overflow, config.block_timeout)
        _install_root_handler(handler, int(config.level))
        if config.capture_warnings:
            # captureWarnings only rebinds showwarning when it is currently off.
            logging.captureWarnings(False)
            logging.captureWarnings(True)

        _RUNTIME = _Runtime(
            queue=queue,
            shared=shared,
            lock=lock,
            handler=handler,
            config=config,
            listener=listener,
            manager=manager,
            owner_pid=os.getpid(),
        )
        atexit.register(shutdown_logging)
        return get_logging_handle()


def get_logging_handle() -> LoggingHandle:
    runtime = _require()
    return LoggingHandle(
        queue=runtime.queue,
        shared=runtime.shared,
        lock=runtime.lock,
        level=logging.getLogger().level,
        overflow=runtime.handler.overflow,
        block_timeout=runtime.handler.block_timeout,
    )


def configure_worker(handle: LoggingHandle) -> None:
    """Bootstrap logging in a child process. Usable as a pool initializer."""
    global _RUNTIME
    with _LOCK:
        handler = SafeQueueHandler(handle.queue, handle.overflow, handle.block_timeout)
        _install_root_handler(handler, handle.level)
        _RUNTIME = _Runtime(
            queue=handle.queue,
            shared=handle.shared,
            lock=handle.lock,
            handler=handler,
            config=None,
            listener=None,
            manager=None,
            owner_pid=None,
        )


def get_logger(name: str | None = None) -> logging.Logger:
    return logging.getLogger(name)


def _next_seq(runtime: _Runtime) -> int:
    with runtime.lock:
        seq = int(runtime.shared["seq"]) + 1
        runtime.shared["seq"] = seq
    return seq


def _wait_applied(runtime: _Runtime, seq: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if int(runtime.shared["applied_seq"]) >= seq:
            return True
        time.sleep(0.005)
    return int(runtime.shared["applied_seq"]) >= seq


def set_log_file(
    path: str | os.PathLike[str],
    *,
    mode: str = "a",
    migrate: bool = False,
    wait: bool = True,
    timeout: float = 5.0,
) -> bool:
    """Retarget the active log file. Callable from any process or thread."""
    runtime = _require()
    allowed_root = runtime.config.allowed_root if runtime.config else None
    current = Path(str(runtime.shared["file_path"]))
    target = resolve_target(path, current.parent, allowed_root)
    seq = _next_seq(runtime)
    runtime.queue.put(SetLogFile(seq=seq, path=str(target), mode=mode, migrate=migrate))
    if not wait:
        return True
    if not _wait_applied(runtime, seq, timeout):
        return False
    return Path(str(runtime.shared["file_path"])) == target


def set_log_directory(directory: str | os.PathLike[str], **kwargs: Any) -> bool:
    runtime = _require()
    current = Path(str(runtime.shared["file_path"]))
    return set_log_file(Path(directory) / current.name, **kwargs)


def reopen_log_file(*, wait: bool = True, timeout: float = 5.0) -> bool:
    """Close and reopen the same path (SIGHUP-style refresh)."""
    runtime = _require()
    seq = _next_seq(runtime)
    runtime.queue.put(Reopen(seq=seq))
    return _wait_applied(runtime, seq, timeout) if wait else True


def get_log_file() -> Path:
    return Path(str(_require().shared["file_path"]))


def get_dropped_count() -> int:
    """Records dropped by this process under the overflow policy."""
    return _require().handler.dropped


def flush_logs(timeout: float = 5.0) -> bool:
    """Block until everything this process has enqueued is on disk."""
    runtime = _require()
    seq = _next_seq(runtime)
    runtime.queue.put(Flush(seq=seq))
    return _wait_applied(runtime, seq, timeout)


def shutdown_logging(timeout: float = 5.0) -> None:
    global _RUNTIME
    with _LOCK:
        runtime = _RUNTIME
        if runtime is None:
            return
        root = logging.getLogger()
        root.removeHandler(runtime.handler)
        if not _is_owner(runtime):
            _RUNTIME = None
            return
        if runtime.config is not None and runtime.config.capture_warnings:
            logging.captureWarnings(False)
        try:
            seq = _next_seq(runtime)
            runtime.queue.put(Stop(seq=seq))
            if runtime.listener is not None:
                runtime.listener.join(timeout)
        except Exception:
            pass
        finally:
            try:
                if runtime.manager is not None:
                    runtime.manager.shutdown()
            except Exception:
                pass
            _RUNTIME = None
