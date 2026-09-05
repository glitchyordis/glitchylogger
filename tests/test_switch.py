from __future__ import annotations

import multiprocessing
import time
from pathlib import Path

import pytest
import workers
from conftest import messages, read_jsonl

from glitchylogger import (
    flush_logs,
    get_log_file,
    get_logger,
    get_logging_handle,
    reopen_log_file,
    set_log_directory,
    set_log_file,
)

PER_PROC = 300


def test_switch_under_multiprocess_load_loses_nothing(
    logging_setup, log_file: Path, alt_file: Path, start_method: str
):
    handle = get_logging_handle()
    ctx = multiprocessing.get_context(start_method)
    procs = [
        ctx.Process(target=workers.log_burst, args=(handle, f"p{i}", PER_PROC))
        for i in range(4)
    ]
    for p in procs:
        p.start()
    time.sleep(0.15)
    assert set_log_file(alt_file)
    for p in procs:
        p.join(60)
        assert p.exitcode == 0
    assert flush_logs(timeout=30)

    old = messages(log_file)
    new = messages(alt_file)
    assert len(old) + len(new) == 4 * PER_PROC
    assert len(set(old) | set(new)) == 4 * PER_PROC
    assert new, "the switch happened too late to be meaningful"


def test_breadcrumbs_are_first_and_last_lines_under_load(
    logging_setup, log_file: Path, alt_file: Path
):
    import threading

    log = get_logger("test.switch")
    stop = threading.Event()

    def spam() -> None:
        while not stop.is_set():
            log.info("noise")

    threads = [threading.Thread(target=spam) for _ in range(8)]
    for t in threads:
        t.start()
    time.sleep(0.1)
    assert set_log_file(alt_file)
    time.sleep(0.1)
    stop.set()
    for t in threads:
        t.join()
    assert flush_logs(timeout=30)

    old = read_jsonl(log_file)
    new = read_jsonl(alt_file)
    assert old[-1]["event"] == "log_switch_out"
    assert new[0]["event"] == "log_switch_in"
    assert old[-1]["seq"] == new[0]["seq"]
    assert not any("event" in r for r in old[:-1])
    assert not any("event" in r for r in new[1:])


def test_process_started_after_switch_uses_new_file(
    logging_setup, log_file: Path, alt_file: Path, start_method: str
):
    assert set_log_file(alt_file)
    handle = get_logging_handle()
    ctx = multiprocessing.get_context(start_method)
    proc = ctx.Process(target=workers.log_burst, args=(handle, "late", 20))
    proc.start()
    proc.join(60)
    assert proc.exitcode == 0
    assert flush_logs(timeout=30)

    assert len(messages(alt_file)) == 20
    assert not messages(log_file)


def test_switch_from_child_process_affects_everyone(
    logging_setup, log_file: Path, alt_file: Path, start_method: str
):
    handle = get_logging_handle()
    ctx = multiprocessing.get_context(start_method)
    proc = ctx.Process(target=_switch_in_child, args=(handle, str(alt_file)))
    proc.start()
    proc.join(60)
    assert proc.exitcode == 0

    get_logger("test.parent").info("after-child-switch")
    assert flush_logs(timeout=30)
    assert get_log_file() == alt_file
    assert "after-child-switch" in messages(alt_file)


def _switch_in_child(handle, target: str) -> None:
    from glitchylogger import configure_worker
    from glitchylogger import set_log_file as child_set

    configure_worker(handle)
    assert child_set(target)


def test_wait_blocks_until_old_file_is_closed(logging_setup, log_file: Path, alt_file: Path):
    log = get_logger("test.wait")
    for i in range(200):
        log.info("pre-%d", i)
    assert set_log_file(alt_file, wait=True)
    # Everything enqueued before the switch is already on disk.
    assert len(messages(log_file)) == 200


def test_switch_to_current_file_is_noop(logging_setup, log_file: Path):
    get_logger("t").info("one")
    assert set_log_file(log_file)
    assert flush_logs(timeout=10)
    assert not [r for r in read_jsonl(log_file) if "event" in r]


def test_reopen_refreshes_same_path(logging_setup, log_file: Path):
    log = get_logger("t")
    log.info("before")
    assert flush_logs(timeout=10)
    assert reopen_log_file()
    log.info("after")
    assert flush_logs(timeout=10)
    assert get_log_file() == log_file
    assert messages(log_file) == ["before", "after"]


def test_set_log_directory_keeps_filename(logging_setup, tmp_path: Path, log_file: Path):
    target_dir = tmp_path / "archive"
    assert set_log_directory(target_dir)
    assert get_log_file() == target_dir / log_file.name


def test_switch_appends_to_existing_target(logging_setup, log_file: Path, alt_file: Path):
    log = get_logger("t")
    log.info("first-visit")
    assert set_log_file(alt_file)
    log.info("in-b")
    assert set_log_file(log_file)
    log.info("back-in-a")
    assert flush_logs(timeout=10)

    assert messages(log_file) == ["first-visit", "back-in-a"]


def test_migrate_moves_the_old_file(logging_setup, log_file: Path, tmp_path: Path):
    log = get_logger("t")
    log.info("before")
    target = tmp_path / "archive" / "logB.log"
    assert set_log_file(target, migrate=True)
    log.info("after")
    assert flush_logs(timeout=10)

    assert not log_file.exists()
    assert messages(target) == ["before", "after"]


def test_failed_switch_keeps_logging(logging_setup, log_file: Path, tmp_path: Path):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")

    assert set_log_file(blocker / "logB.log") is False
    get_logger("t").info("still alive")
    assert flush_logs(timeout=10)

    assert get_log_file() == log_file
    assert "still alive" in messages(log_file)


def test_switch_outside_allowed_root_is_rejected(tmp_path: Path):
    from glitchylogger import LoggerConfig, configure_logging

    root = tmp_path / "allowed"
    root.mkdir()
    configure_logging(LoggerConfig(file_path=root / "logA.log", console=False, allowed_root=root))

    with pytest.raises(ValueError):
        set_log_file(tmp_path / "escape.log")
    with pytest.raises(ValueError):
        set_log_file(root / ".." / "escape.log")

    get_logger("t").info("safe")
    assert flush_logs(timeout=10)
    assert messages(root / "logA.log") == ["safe"]
