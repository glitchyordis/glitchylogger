# Changelog

## [Unreleased]

## [0.2.0] - 2026-09-06

### Added

- Optional authenticated browser viewer for searching and following the latest
  JSON Lines records without changing the logging format or runtime pipeline;
  directory mode can automatically follow the newest log or select a specific file.
- Authenticated server-side directory browsing and runtime directory switching
  in the browser viewer.
- Independent per-browser directory and file selection with concurrent live
  updates for users following the same or different log files.
- Separate-token admin dashboard for connection duration, interaction-idle
  time, client/source details, and individual or bulk viewer disconnection.
- Progressive browser rendering loads older retained rows in 250-row batches
  while scrolling upward and reports when older records remain on disk beyond
  the 1,000-record searchable window.
- Windows Credential Manager storage and launch-time fallback for viewer and
  admin tokens, with environment and explicit command-line overrides.

## [0.1.1] - 2026-09-06

### Fixed

- `test_switch_under_multiprocess_load_loses_nothing` no longer relies on a fixed
  sleep to land the file switch mid-burst; workers now synchronise on a barrier so
  the switch point is deterministic on slow CI runners.
- Tests that count log lines no longer fail on Linux, where CPython 3.12+ raises a
  `DeprecationWarning` for `fork()` in a multi-threaded process and warning capture
  wrote it into the log under test.

### Changed

- CI runs on pushes to any branch and can be triggered manually; superseded runs
  for the same ref are cancelled.
- Readme documents the POSIX `fork()` caveat and the changelog-driven release flow.

## [0.1.0] - 2026-09-05

### Added

- Initial release: process-safe and thread-safe logging through a single listener
  thread and one file handle.
- Hot-swappable log file target via `set_log_file`, `set_log_directory`, and
  `reopen_log_file`.
- JSON Lines and human-readable formatters.
- Context propagation helpers and overflow policies for the shared queue.