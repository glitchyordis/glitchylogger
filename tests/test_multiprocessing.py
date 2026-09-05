from __future__ import annotations

import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import workers
from conftest import messages

from glitchylogger import configure_worker, flush_logs, get_logger, get_logging_handle

PER_PROC = 100


def test_processes_share_one_file(logging_setup, log_file: Path, start_method: str):
    handle = get_logging_handle()
    ctx = multiprocessing.get_context(start_method)
    procs = [
        ctx.Process(target=workers.log_burst, args=(handle, f"p{i}", PER_PROC))
        for i in range(4)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(60)
        assert p.exitcode == 0
    assert flush_logs(timeout=30)

    msgs = messages(log_file)
    assert len(msgs) == 4 * PER_PROC
    for i in range(4):
        assert sum(1 for m in msgs if m.startswith(f"p{i}-")) == PER_PROC


def test_threads_inside_processes(logging_setup, log_file: Path, start_method: str):
    handle = get_logging_handle()
    ctx = multiprocessing.get_context(start_method)
    procs = [
        ctx.Process(target=workers.log_burst_threaded, args=(handle, f"p{i}", 4, 50))
        for i in range(3)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(60)
        assert p.exitcode == 0
    assert flush_logs(timeout=30)

    assert len(messages(log_file)) == 3 * 4 * 50


def test_process_pool_executor_initializer(logging_setup, log_file: Path):
    handle = get_logging_handle()
    with ProcessPoolExecutor(
        max_workers=3, initializer=configure_worker, initargs=(handle,)
    ) as pool:
        results = list(pool.map(workers.pool_task, [(f"task{i}", 40) for i in range(6)]))
    assert results == [40] * 6
    assert flush_logs(timeout=30)

    assert len(messages(log_file)) == 6 * 40


def test_records_identify_their_process(logging_setup, log_file: Path, start_method: str):
    from conftest import read_jsonl

    handle = get_logging_handle()
    ctx = multiprocessing.get_context(start_method)
    proc = ctx.Process(target=workers.log_burst, args=(handle, "child", 5))
    proc.start()
    proc.join(60)
    get_logger("test.parent").info("parent-record")
    assert flush_logs(timeout=30)

    records = [r for r in read_jsonl(log_file) if "event" not in r]
    pids = {r["pid"] for r in records}
    assert len(pids) == 2
