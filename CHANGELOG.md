# Changelog

## [Unreleased]


## [0.1.0] - 2026-09-05

### Added

- Initial release: process-safe and thread-safe logging through a single listener
  thread and one file handle.
- Hot-swappable log file target via `set_log_file`, `set_log_directory`, and
  `reopen_log_file`.
- JSON Lines and human-readable formatters.
- Context propagation helpers and overflow policies for the shared queue.