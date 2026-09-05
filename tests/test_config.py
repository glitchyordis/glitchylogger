from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

from glitchylogger.logkit.config import LoggerConfig, confine, resolve_target


def test_levels_are_normalised(tmp_path: Path):
    config = LoggerConfig(file_path=tmp_path / "a.log", level="debug", console_level="WARNING")
    assert config.level == logging.DEBUG
    assert config.console_level == logging.WARNING


def test_unknown_level_rejected(tmp_path: Path):
    with pytest.raises(ValueError):
        LoggerConfig(file_path=tmp_path / "a.log", level="LOUD")


def test_invalid_queue_size_rejected(tmp_path: Path):
    with pytest.raises(ValueError):
        LoggerConfig(file_path=tmp_path / "a.log", queue_size=0)


def test_unknown_overflow_rejected(tmp_path: Path):
    with pytest.raises(ValueError):
        LoggerConfig(file_path=tmp_path / "a.log", overflow="panic")


def test_confine_allows_paths_inside_root(tmp_path: Path):
    assert confine(tmp_path / "sub" / "a.log", tmp_path) == (tmp_path / "sub" / "a.log").resolve()


def test_confine_rejects_traversal(tmp_path: Path):
    root = tmp_path / "logs"
    root.mkdir()
    with pytest.raises(ValueError):
        confine(root / ".." / "etc" / "passwd", root)


def test_confine_rejects_absolute_escape(tmp_path: Path):
    root = tmp_path / "logs"
    root.mkdir()
    outside = tmp_path / "outside.log"
    with pytest.raises(ValueError):
        confine(outside, root)


@pytest.mark.skipif(os.name != "nt", reason="Windows path casing")
def test_confine_is_case_insensitive_on_windows(tmp_path: Path):
    root = tmp_path / "Logs"
    root.mkdir()
    assert confine(Path(str(root).upper()) / "a.log", root)


def test_resolve_target_uses_current_directory_for_bare_names(tmp_path: Path):
    assert resolve_target("logB.log", tmp_path, None) == (tmp_path / "logB.log").resolve()


def test_resolve_target_keeps_absolute_paths(tmp_path: Path):
    other = tmp_path / "other" / "logB.log"
    assert resolve_target(other, tmp_path, None) == other.resolve()


def test_config_rejects_file_outside_allowed_root(tmp_path: Path):
    root = tmp_path / "allowed"
    root.mkdir()
    with pytest.raises(ValueError):
        LoggerConfig(file_path=tmp_path / "elsewhere.log", allowed_root=root)


def test_from_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MPMT_LOG_FILE", str(tmp_path / "env.log"))
    monkeypatch.setenv("MPMT_LOG_LEVEL", "WARNING")
    monkeypatch.setenv("MPMT_LOG_CONSOLE", "0")
    config = LoggerConfig.from_env()
    assert config.file_path == (tmp_path / "env.log").resolve()
    assert config.level == logging.WARNING
    assert config.console is False
