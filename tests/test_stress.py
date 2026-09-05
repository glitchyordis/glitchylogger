from __future__ import annotations

import multiprocessing
import time
from pathlib import Path

import pytest
import workers
from conftest import messages

from glitchylogger import flush_logs, get_logging_handle, set_log_file

pytestmark = pytest.mark.slow

PROCS = 4
THREADS = 4
PER_THREAD = 400


def test_soak_with_repeated_switches(logging_setup, tmp_path: Path, log_file: Path):
    handle = get_logging_handle()
    ctx = multiprocessing.get_context()
    procs = [
        ctx.Process(target=workers.log_burst_threaded, args=(handle, f"p{i}", THREADS, PER_THREAD))
        for i in range(PROCS)
    ]
    for p in procs:
        p.start()

    targets = [log_file] + [tmp_path / f"log{n}.log" for n in range(1, 4)]
    for target in targets[1:]:
        time.sleep(0.3)
        assert set_log_file(target)

    for p in procs:
        p.join(300)
        assert p.exitcode == 0
    assert flush_logs(timeout=60)

    all_messages: list[str] = []
    for target in targets:
        all_messages.extend(messages(target))

    expected = PROCS * THREADS * PER_THREAD
    assert len(all_messages) == expected
    assert len(set(all_messages)) == expected
