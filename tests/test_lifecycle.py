from __future__ import annotations

import logging
import multiprocessing
from pathlib import Path

import pytest
from conftest import messages, read_jsonl

from glitchylogger import (
    LoggerConfig,
    configure_logging,
    flush_logs,
    get_logger,
    get_logging_handle,
    shutdown_logging,
)
from glitchylogger.logkit.handlers import SafeQueueHandler


def test_configure_is_idempotent(log_file: Path):
    first = configure_logging(LoggerConfig(file_path=log_file, console=False))
    second = configure_logging(LoggerConfig(file_path=log_file, console=False))
    assert first.queue is second.queue

    root = logging.getLogger()
    assert sum(isinstance(h, SafeQueueHandler) for h in root.handlers) == 1


def test_shutdown_is_idempotent(log_file: Path):
    configure_logging(LoggerConfig(file_path=log_file, console=False))
    shutdown_logging(timeout=10)
    shutdown_logging(timeout=10)


def test_shutdown_flushes_and_writes_close_breadcrumb(log_file: Path):
    configure_logging(LoggerConfig(file_path=log_file, console=False))
    log = get_logger("test.shutdown")
    for i in range(100):
        log.info("bye-%d", i)
    shutdown_logging(timeout=10)

    records = read_jsonl(log_file)
    assert len([r for r in records if "event" not in r]) == 100
    assert records[-1]["event"] == "log_close"


def test_api_requires_configuration():
    with pytest.raises(RuntimeError):
        flush_logs()


def test_root_handler_is_removed_on_shutdown(log_file: Path):
    configure_logging(LoggerConfig(file_path=log_file, console=False))
    shutdown_logging(timeout=10)
    assert not any(isinstance(h, SafeQueueHandler) for h in logging.getLogger().handlers)


def test_child_configure_does_not_start_second_listener(logging_setup, log_file: Path, start_method: str):
    handle = get_logging_handle()
    ctx = multiprocessing.get_context(start_method)
    proc = ctx.Process(target=_child_configures, args=(handle, str(log_file)))
    proc.start()
    proc.join(60)
    assert proc.exitcode == 0
    assert flush_logs(timeout=30)

    assert messages(log_file) == ["from-child"]


def _child_configures(handle, path: str) -> None:
    from glitchylogger import configure_logging as child_configure
    from glitchylogger import configure_worker

    configure_worker(handle)
    # A module that defensively configures logging must not hijack the pipeline.
    child_configure(LoggerConfig(file_path=path, console=False))
    get_logger("child").info("from-child")
    root_handlers = [h for h in logging.getLogger().handlers if isinstance(h, SafeQueueHandler)]
    assert len(root_handlers) == 1


def test_modules_can_get_loggers_before_configuration(log_file: Path):
    module_logger = get_logger("some.module")
    configure_logging(LoggerConfig(file_path=log_file, console=False))
    module_logger.warning("late binding works")
    assert flush_logs(timeout=10)
    assert messages(log_file) == ["late binding works"]


def test_warnings_are_captured(log_file: Path):
    import warnings

    configure_logging(LoggerConfig(file_path=log_file, console=False, level="DEBUG"))
    with warnings.catch_warnings():
        warnings.simplefilter("always")
        warnings.warn("deprecated thing", UserWarning)
    assert flush_logs(timeout=10)
    assert any("deprecated thing" in m for m in messages(log_file))
