"""Process-safe, thread-safe logger with a hot-swappable log file target.

Application entry point::

    from glitchylogger import LoggerConfig, configure_logging, get_logger

    configure_logging(LoggerConfig(file_path="logs/logA.log"))
    get_logger(__name__).info("hello")

Library modules stay configuration-free::

    from glitchylogger import get_logger
    log = get_logger(__name__)

Child processes join the same pipeline::

    handle = get_logging_handle()
    ProcessPoolExecutor(initializer=configure_worker, initargs=(handle,))

Switching the target from anywhere (API handler, worker, thread)::

    set_log_file("logB.log")   # blocks until logA.log is closed and fsynced
"""

from .logkit.config import LoggerConfig
from .logkit.context import bind_context, get_request_id, set_request_id
from .logkit.control import LoggingHandle
from .logkit.runtime import (
    configure_logging,
    configure_worker,
    flush_logs,
    get_dropped_count,
    get_log_file,
    get_logger,
    get_logging_handle,
    reopen_log_file,
    set_log_directory,
    set_log_file,
    shutdown_logging,
)

__all__ = [
    "LoggerConfig",
    "LoggingHandle",
    "bind_context",
    "configure_logging",
    "configure_worker",
    "flush_logs",
    "get_dropped_count",
    "get_log_file",
    "get_logger",
    "get_logging_handle",
    "get_request_id",
    "reopen_log_file",
    "set_log_directory",
    "set_log_file",
    "set_request_id",
    "shutdown_logging",
]
