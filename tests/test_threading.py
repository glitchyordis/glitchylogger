from __future__ import annotations

import logging
import threading
from pathlib import Path

from conftest import messages, read_jsonl

from glitchylogger import flush_logs, get_logger, set_log_file

THREADS = 16
PER_THREAD = 200


def test_all_thread_records_arrive(logging_setup, log_file: Path):
    log = get_logger("test.threads")

    def worker(tid: int) -> None:
        for i in range(PER_THREAD):
            log.info("t%d-%d", tid, i)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert flush_logs(timeout=30)

    msgs = messages(log_file)
    assert len(msgs) == THREADS * PER_THREAD
    assert len(set(msgs)) == THREADS * PER_THREAD


def test_threads_switching_file_lose_nothing(logging_setup, log_file: Path, alt_file: Path):
    log = get_logger("test.threads.switch")
    stop = threading.Event()
    counts: dict[int, int] = {}

    def worker(tid: int) -> None:
        sent = 0
        while not stop.is_set():
            log.info("t%d-%d", tid, sent)
            sent += 1
        counts[tid] = sent

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(8)]
    for t in threads:
        t.start()
    threading.Event().wait(0.2)
    assert set_log_file(alt_file)
    threading.Event().wait(0.2)
    stop.set()
    for t in threads:
        t.join()
    assert flush_logs(timeout=30)

    total = sum(counts.values())
    assert len(messages(log_file)) + len(messages(alt_file)) == total


def test_record_carries_thread_and_process_identity(logging_setup, log_file: Path):
    get_logger("test.identity").info("hello")
    assert flush_logs(timeout=10)
    record = [r for r in read_jsonl(log_file) if "event" not in r][0]
    assert record["thread"] == threading.current_thread().name
    assert record["pid"] > 0


def test_exception_is_captured(logging_setup, log_file: Path):
    log = get_logger("test.exc")
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        log.exception("failed")
    assert flush_logs(timeout=10)
    record = [r for r in read_jsonl(log_file) if "event" not in r][0]
    assert "RuntimeError: boom" in record["exc"]


def test_unpicklable_extra_does_not_break_pipeline(logging_setup, log_file: Path):
    log = get_logger("test.extra")
    log.info("with lock", extra={"lock": threading.Lock()})
    assert flush_logs(timeout=10)
    record = [r for r in read_jsonl(log_file) if "event" not in r][0]
    assert record["msg"] == "with lock"
    assert "lock" in record


def test_level_filtering(log_file: Path):
    from glitchylogger import LoggerConfig, configure_logging

    configure_logging(LoggerConfig(file_path=log_file, level="WARNING", console=False))
    log = get_logger("test.levels")
    log.debug("nope")
    log.info("nope")
    log.warning("yes")
    assert flush_logs(timeout=10)
    assert messages(log_file) == ["yes"]
    assert logging.getLogger().level == logging.WARNING
