"""Multiprocessing + multithreading demo with a mid-run log file switch.

python examples/multiprocessing_demo.py
"""

from __future__ import annotations

import multiprocessing
import sys
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from glitchylogger import (  # noqa: E402
    LoggerConfig,
    configure_logging,
    configure_worker,
    flush_logs,
    get_log_file,
    get_logger,
    get_logging_handle,
    set_log_file,
    shutdown_logging,
)

LOG_DIR = Path(__file__).resolve().parent / "demo-logs"


def worker(tag: str, count: int) -> str:
    """Runs in a pool process; logging is already wired by the initializer."""
    log = get_logger(f"demo.{tag}")

    def thread_body(thread_id: int) -> None:
        for i in range(count):
            log.info("work item %d", i, extra={"thread_id": thread_id, "tag": tag})
            time.sleep(0.002)

    threads = [threading.Thread(target=thread_body, args=(t,)) for t in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return tag


def main() -> None:
    # use datetime to set logname
    from datetime import datetime
    configure_logging(
        LoggerConfig(
            file_path=LOG_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.log", level="DEBUG", allowed_root=LOG_DIR
        )
    )
    log = get_logger("demo.main")
    log.info("starting, writing to %s", get_log_file())

    handle = get_logging_handle()
    with ProcessPoolExecutor(
        max_workers=4, initializer=configure_worker, initargs=(handle,)
    ) as pool:
        futures = [pool.submit(worker, f"proc{i}", 200) for i in range(4)]
        time.sleep(0.2)

        log.warning("switching log target while workers are running")
        set_log_file("logB.log")
        log.info("now writing to %s", get_log_file())

        for future in futures:
            future.result()

    flush_logs()
    log.info("done")
    shutdown_logging()

    for path in sorted(LOG_DIR.glob("*.log")):
        print(f"{path}: {sum(1 for _ in path.open(encoding='utf-8'))} lines")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
