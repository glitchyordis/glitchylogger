from __future__ import annotations

import json
import logging
import multiprocessing
import sys
from pathlib import Path

import pytest

from glitchylogger import LoggerConfig, configure_logging, shutdown_logging

START_METHODS = [m for m in ("spawn", "fork", "forkserver") if m in multiprocessing.get_all_start_methods()]


@pytest.fixture(autouse=True)
def clean_logging():
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    yield
    shutdown_logging(timeout=10)
    root.handlers[:] = saved_handlers
    root.setLevel(saved_level)


@pytest.fixture(params=START_METHODS)
def start_method(request):
    return request.param


@pytest.fixture
def log_file(tmp_path: Path) -> Path:
    return tmp_path / "logA.log"


@pytest.fixture
def alt_file(tmp_path: Path) -> Path:
    return tmp_path / "logB.log"


@pytest.fixture
def logging_setup(log_file: Path):
    """Configured pipeline with the console muted so pytest output stays readable.

    Warning capture is off so interpreter warnings (e.g. CPython's fork-in-a-
    multi-threaded-process DeprecationWarning) cannot land in the counted log.
    """
    handle = configure_logging(
        LoggerConfig(
            file_path=log_file, level="DEBUG", console=False, capture_warnings=False
        )
    )
    return handle


def read_jsonl(path: Path) -> list[dict]:
    """Read a log file, asserting every line is a complete JSON object."""
    if not path.exists():
        return []
    records = []
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                pytest.fail(f"torn/invalid JSON at {path}:{lineno}: {line!r} ({exc})")
    return records


def messages(path: Path) -> list[str]:
    return [r["msg"] for r in read_jsonl(path) if "event" not in r]


requires_posix = pytest.mark.skipif(sys.platform == "win32", reason="POSIX only")
