from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

request_id_var: ContextVar[str | None] = ContextVar("mpmt_request_id", default=None)
correlation_id_var: ContextVar[str | None] = ContextVar("mpmt_correlation_id", default=None)
extra_context_var: ContextVar[dict[str, Any]] = ContextVar("mpmt_extra_context", default={})


def set_request_id(value: str | None) -> None:
    request_id_var.set(value)


def get_request_id() -> str | None:
    return request_id_var.get()


@contextmanager
def bind_context(
    *,
    request_id: str | None = None,
    correlation_id: str | None = None,
    **fields: Any,
) -> Iterator[None]:
    tokens = []
    if request_id is not None:
        tokens.append((request_id_var, request_id_var.set(request_id)))
    if correlation_id is not None:
        tokens.append((correlation_id_var, correlation_id_var.set(correlation_id)))
    if fields:
        merged = {**extra_context_var.get(), **fields}
        tokens.append((extra_context_var, extra_context_var.set(merged)))
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


class ContextFilter(logging.Filter):
    """Stamps contextvars onto records on the producer side.

    Context does not cross process boundaries, so this must run before the
    record is handed to the queue.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        record.correlation_id = correlation_id_var.get()
        for key, value in extra_context_var.get().items():
            if not hasattr(record, key):
                setattr(record, key, value)
        return True
