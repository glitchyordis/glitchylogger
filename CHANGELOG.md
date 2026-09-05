# Changelog

## [Unreleased]

### Fixed

- `test_switch_under_multiprocess_load_loses_nothing` no longer relies on a fixed
  sleep to land the file switch mid-burst; workers now synchronise on a barrier so
  the switch point is deterministic on slow CI runners.

### Changed

- CI runs on pushes to any branch and can be triggered manually; superseded runs
  for the same ref are cancelled.

## [0.1.0] - 2026-09-05

### Added

- Initial release: process-safe and thread-safe logging through a single listener
  thread and one file handle.
- Hot-swappable log file target via `set_log_file`, `set_log_directory`, and
  `reopen_log_file`.
- JSON Lines and human-readable formatters.
- Context propagation helpers and overflow policies for the shared queue.