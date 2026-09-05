from __future__ import annotations

import asyncio
import logging
import threading

from glitchylogger.logkit.context import (
    ContextFilter,
    bind_context,
    get_request_id,
    set_request_id,
)


def make_record() -> logging.LogRecord:
    return logging.LogRecord("t", logging.INFO, __file__, 1, "m", None, None)


def test_filter_stamps_context():
    with bind_context(request_id="r1", correlation_id="c1", tenant="acme"):
        record = make_record()
        ContextFilter().filter(record)
    assert record.request_id == "r1"
    assert record.correlation_id == "c1"
    assert record.tenant == "acme"


def test_context_is_reset_on_exit():
    with bind_context(request_id="r1"):
        assert get_request_id() == "r1"
    assert get_request_id() is None


def test_nested_context_restores_outer():
    with bind_context(request_id="outer"):
        with bind_context(request_id="inner"):
            assert get_request_id() == "inner"
        assert get_request_id() == "outer"


def test_threads_do_not_share_context():
    seen: dict[str, str | None] = {}

    def worker(name: str) -> None:
        set_request_id(name)
        seen[name] = get_request_id()

    threads = [threading.Thread(target=worker, args=(f"t{i}",)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert seen == {f"t{i}": f"t{i}" for i in range(8)}
    assert get_request_id() is None


def test_async_tasks_do_not_share_context():
    async def task(name: str) -> str | None:
        with bind_context(request_id=name):
            await asyncio.sleep(0)
            return get_request_id()

    async def main() -> list[str | None]:
        return await asyncio.gather(*(task(f"a{i}") for i in range(8)))

    assert asyncio.run(main()) == [f"a{i}" for i in range(8)]
