from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Overflow = Literal["discard", "block", "drop"]

_LEVELS = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}


def to_level(value: int | str) -> int:
    if isinstance(value, int):
        return value
    name = str(value).upper()
    if name not in _LEVELS:
        raise ValueError(f"unknown log level: {value!r}")
    return int(getattr(logging, name))


def confine(path: Path, allowed_root: Path | None) -> Path:
    """Resolve *path* and reject anything escaping *allowed_root*."""
    resolved = Path(path).expanduser().resolve()
    if allowed_root is None:
        return resolved
    root = Path(allowed_root).expanduser().resolve()
    # normcase makes the comparison case-insensitive on Windows.
    target_s = os.path.normcase(str(resolved))
    root_s = os.path.normcase(str(root))
    if target_s != root_s and not target_s.startswith(root_s + os.sep):
        raise ValueError(f"log path {resolved} escapes allowed root {root}")
    return resolved


def resolve_target(path: str | os.PathLike[str], base: Path, allowed_root: Path | None) -> Path:
    """Turn a user-supplied target into an absolute file path.

    A bare filename (``logB.log``) is resolved against the directory of the
    currently active log file.
    """
    candidate = Path(path).expanduser()
    if not candidate.is_absolute() and candidate.parent == Path("."):
        candidate = base / candidate.name
    return confine(candidate, allowed_root)


@dataclass(frozen=True)
class LoggerConfig:
    file_path: Path
    level: int | str = logging.INFO
    console_level: int | str = logging.INFO
    file_level: int | str = logging.DEBUG
    console: bool = True
    queue_size: int = 10_000
    overflow: Overflow = "discard"
    block_timeout: float = 1.0
    allowed_root: Path | None = None
    capture_warnings: bool = True
    color: bool | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "level", to_level(self.level))
        object.__setattr__(self, "console_level", to_level(self.console_level))
        object.__setattr__(self, "file_level", to_level(self.file_level))
        root = None if self.allowed_root is None else Path(self.allowed_root).expanduser().resolve()
        object.__setattr__(self, "allowed_root", root)
        object.__setattr__(self, "file_path", confine(Path(self.file_path), root))
        if self.queue_size <= 0:
            raise ValueError("queue_size must be positive")
        if self.overflow not in ("discard", "block", "drop"):
            raise ValueError(f"unknown overflow policy: {self.overflow!r}")
        if self.block_timeout < 0:
            raise ValueError("block_timeout must be >= 0")

    @classmethod
    def from_env(cls, **overrides: object) -> LoggerConfig:
        env = os.environ
        kwargs: dict[str, object] = {
            "file_path": env.get("MPMT_LOG_FILE", "logs/app.log"),
            "level": env.get("MPMT_LOG_LEVEL", "INFO"),
            "console": env.get("MPMT_LOG_CONSOLE", "1") not in ("0", "false", "False"),
            "overflow": env.get("MPMT_LOG_OVERFLOW", "discard"),
        }
        if "MPMT_LOG_QUEUE_SIZE" in env:
            kwargs["queue_size"] = int(env["MPMT_LOG_QUEUE_SIZE"])
        if "MPMT_LOG_ALLOWED_ROOT" in env:
            kwargs["allowed_root"] = Path(env["MPMT_LOG_ALLOWED_ROOT"])
        kwargs.update(overrides)
        return cls(**kwargs)  # type: ignore[arg-type]
