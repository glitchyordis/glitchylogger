"""Module-level worker functions. Windows spawn requires these to be importable."""

from __future__ import annotations

import threading

from glitchylogger import configure_worker, get_logger


def log_burst(handle, tag: str, count: int) -> None:
    configure_worker(handle)
    log = get_logger(f"worker.{tag}")
    for i in range(count):
        log.info("%s-%d", tag, i)


def log_burst_threaded(handle, tag: str, threads: int, count: int) -> None:
    configure_worker(handle)
    log = get_logger(f"worker.{tag}")

    def run(thread_id: int) -> None:
        for i in range(count):
            log.info("%s-t%d-%d", tag, thread_id, i)

    workers = [threading.Thread(target=run, args=(t,)) for t in range(threads)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()


def pool_task(args: tuple[str, int]) -> int:
    tag, count = args
    log = get_logger("worker.pool")
    for i in range(count):
        log.info("%s-%d", tag, i)
    return count


def log_until(handle, tag: str, count: int, barrier=None) -> None:
    """Log steadily; used to keep the queue busy while the target is switched."""
    configure_worker(handle)
    log = get_logger(f"worker.{tag}")
    if barrier is not None:
        barrier.wait()
    for i in range(count):
        log.info("%s-%d", tag, i)
