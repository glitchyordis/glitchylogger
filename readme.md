# GlitchyLogger

Process-safe and thread-safe Python logging with JSON Lines output and a log file
that can be switched while the application is running.

GlitchyLogger uses one listener thread and one file handle. Threads and child
processes send records through a shared queue, avoiding competing writes to the
same file.

An optional authenticated [browser log viewer](docs/log-viewer.md) provides
live JSONL updates, filtering, source selection, and an admin session dashboard.

<p align="center">
	<img src="docs/images/log-viewer.png" alt="GlitchyLogger browser viewer showing live JSONL records" width="780">
</p>

## Requirements

- Python 3.11 or newer
- No runtime dependencies

## Install

Install a tagged release directly from GitHub:

```bash
python -m pip install "glitchylogger @ git+https://github.com/glitchyordis/glitchylogger.git@main"
```

In another project's `pyproject.toml`, pin the same tag for reproducible builds:

```toml
[project]
dependencies = [
	"glitchylogger @ git+https://github.com/glitchyordis/glitchylogger.git@main",
]
```

To upgrade later, change the tag and reinstall the consuming project. Pin a tag
or commit in deployed applications; tracking `main` makes builds non-reproducible.

For local development across two repositories:

```bash
python -m pip install --editable ../glitchylogger
```

## Basic usage

```python
from glitchylogger import LoggerConfig, configure_logging, get_logger, shutdown_logging

configure_logging(LoggerConfig(file_path="logs/app.jsonl", level="INFO"))
log = get_logger(__name__)

try:
	log.info("application started")
finally:
	shutdown_logging()
```

Applications configure and shut down logging. Library modules should only call
`get_logger(__name__)`.

To shorten source paths in JSON output, select the application root:

```python
configure_logging(
	LoggerConfig(file_path="logs/app.jsonl", source_path_base=".")
)
```

Files below that directory are shown relative to it. Files outside it retain
their absolute path. The same option can be set with
`GLITCHYLOGGER_LOG_SOURCE_PATH_BASE`.

Call `configure_logging()` without arguments to load these environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `GLITCHYLOGGER_LOG_FILE` | `logs/app.log` | Output file |
| `GLITCHYLOGGER_LOG_LEVEL` | `INFO` | Root logger level |
| `GLITCHYLOGGER_LOG_CONSOLE` | `1` | Set to `0` or `false` to disable console output |
| `GLITCHYLOGGER_LOG_OVERFLOW` | `discard` | Queue overflow policy |
| `GLITCHYLOGGER_LOG_QUEUE_SIZE` | `10000` | Maximum queued records |
| `GLITCHYLOGGER_LOG_ALLOWED_ROOT` | unset | Restrict log targets to this directory |
| `GLITCHYLOGGER_LOG_SOURCE_PATH_BASE` | unset | Make source pathnames relative to this directory |

JSONL records include `module`, `pathname`, `func`, and `line` source fields.
Without `source_path_base`, `pathname` remains the original path supplied by
Python's logging record. `HumanFormatter` currently displays only
`record.filename`; `source_path_base` is reserved for possible future console
path formatting.

`JsonLinesFormatter` stores `ts` as an ISO 8601 UTC timestamp with an explicit
`+00:00` offset. `HumanFormatter` displays the same instant in the logging
server's local time without an offset, for compact console output. The browser
viewer parses the JSON timestamp and displays it in the browser's local time.

### Custom formatters

`LoggerConfig` accepts any `logging.Formatter` instance for file and console
output. Standard format strings work without subclassing:

```python
import logging

from glitchylogger import LoggerConfig, configure_logging

configure_logging(
	LoggerConfig(
		file_path="logs/app.log",
		file_formatter=logging.Formatter(
			"%(asctime)s %(levelname)s %(name)s %(message)s"
		),
		console_formatter=logging.Formatter("%(levelname)s | %(message)s"),
	)
)
```

For structured output, subclass the exported defaults and override `format()`:

```python
import json
import logging

from glitchylogger import JsonLinesFormatter, LoggerConfig, configure_logging


class ApplicationJsonFormatter(JsonLinesFormatter):
	def format(self, record: logging.LogRecord) -> str:
		return json.dumps(
			{
				"severity": record.levelname,
				"logger": record.name,
				"msg": record.getMessage(),
			},
			ensure_ascii=False,
		)


configure_logging(
	LoggerConfig(
		file_path="logs/app.jsonl",
		file_formatter=ApplicationJsonFormatter(),
	)
)
```

This formatter replaces the complete JSON object and <mark>is not compatible</mark> with the standard viewer columns because it omits `ts` and renames `level`. Delegate to the parent formatter when built-in fields and behavior should be retained.

To customize both destinations while retaining the built-in JSON path
shortening plus console color, exception, and viewer behavior, delegate to each parent formatter before adjusting its output:

```python
import json
import logging
from pathlib import Path

from glitchylogger import (
	HumanFormatter,
	JsonLinesFormatter,
	LoggerConfig,
	configure_logging,
)

PROJECT_ROOT = Path(__file__).resolve().parent


class ApplicationJsonFormatter(JsonLinesFormatter):
	def format(self, record: logging.LogRecord) -> str:
		payload = json.loads(super().format(record))
		payload["application"] = "billing"
		return json.dumps(payload, ensure_ascii=False, default=str)


class ApplicationConsoleFormatter(HumanFormatter):
	def format(self, record: logging.LogRecord) -> str:
		return f"[billing] {super().format(record)}"


configure_logging(
	LoggerConfig(
		file_path="logs/app.jsonl",
		file_formatter=ApplicationJsonFormatter(
			source_path_base=PROJECT_ROOT,
		),
		console_formatter=ApplicationConsoleFormatter(
			color=True,
		),
	)
)
```

The subclasses inherit their constructors. Calling `super().format(record)` on
the JSON formatter applies `source_path_base`; delegating in either formatter
keeps its standard fields and features before the custom output is added.

Formatting runs in the listener thread in the owner process, so workers require
no additional setup. A custom file formatter used with the browser viewer must
emit exactly one JSON object per line. Keep `ts`, `level`, `logger`, and `msg`
for the standard viewer columns; additional JSON fields remain available in
record details.

Providing `file_formatter` or `console_formatter` bypasses creation of that
built-in formatter, so `LoggerConfig.color` and `LoggerConfig.source_path_base`
are not injected automatically. Pass `color` directly to a `HumanFormatter`
subclass and `source_path_base` directly to a `JsonLinesFormatter` subclass, as
above. A formatter that does not delegate to `super().format(record)` is
responsible for implementing any desired color, source-path, timestamp,
exception, and extra-field behavior itself.

## Child processes

Pass the logging handle to processes created by your application:

```python
from concurrent.futures import ProcessPoolExecutor

from glitchylogger import configure_worker, get_logging_handle

handle = get_logging_handle()
with ProcessPoolExecutor(
	initializer=configure_worker,
	initargs=(handle,),
) as pool:
	...
```

See `examples/multiprocessing_demo.py` and `examples/fastapi_app.py` for complete
examples, including runtime file switching and request context.

## Live browser viewer

The optional viewer presents the existing JSON Lines file as readable columns
with live updates, text search, level and logger filters, and expandable record
details. It only reads the file; the logging format and writer are unchanged.

See the [Log Viewer Guide](docs/log-viewer.md) for complete launch, LAN access,
usage, security, and troubleshooting instructions.

Install the viewer dependencies on the computer running the application:

```bash
python -m pip install --editable ".[viewer]"
```

On Windows, securely prompt for the viewer and admin tokens once. They are
stored in Windows Credential Manager for the current Windows account:

```powershell
glitchylogger-store-viewer-secrets
```

Enter the shared viewer password at `Viewer token:` and a different privileged
password at `Admin token:`. Input is hidden. If the setup command is not
recognized after updating the source, reinstall the editable package with the
viewer extra using the command above, or run:

```powershell
python -c "from glitchylogger.viewer import store_credentials; store_credentials()"
```

Then start the viewer on the log directory. Binding to `0.0.0.0` makes it
reachable from other computers on the LAN:

```powershell
glitchylogger-viewer --directory C:\ProgramData\MyApp\logs --host 0.0.0.0
```

Show optional source columns when a browser has no saved column preference:

```powershell
glitchylogger-viewer --directory C:\ProgramData\MyApp\logs --columns module func
```

Valid optional columns are `module` and `func`. Invalid names stop startup with
a message listing the valid choices. Set the same default with the comma-separated
`GLITCHYLOGGER_VIEWER_COLUMNS` environment variable. A selection made in the
browser is saved locally and takes precedence over the startup default.

Environment variables override stored credentials, and explicit token options
override both. On the other computer, open `http://LOGGER-PC:8765` and enter
the same viewer token; administrators still enter the separate admin token at
`http://LOGGER-PC:8765/admin`. The tokens are shared role credentials rather
than individual user accounts.
By default, the viewer loads up to the latest 1,000 complete records and then
displays new records as they are appended. It renders the newest 250 matches
first; scroll upward to load older retained rows in batches of 250. The counter
reports when still older records exist on disk outside the browser's searchable
history window.

`Latest file (auto)` follows the most recently modified `.log` or `.jsonl`
file, including files created by `set_log_file()`. The file selector can instead
pin the stream to any listed file in that directory.
The folder button can browse and switch directories on the logging host while
the viewer is running. A browser-native folder picker would browse the remote
user's computer instead of the logging host.
Directory and file choices are independent per browser tab, so multiple users
can follow the same or different files concurrently and all receive live
updates for their selected file.
Closing a tab cancels its server stream and releases its follower and request
state. Log files are opened only during reads rather than held open per user.
For abrupt network loss, an SSE heartbeat sent about every 15 seconds helps the
server detect and remove stale connections.

Administrators can open `http://LOGGER-PC:8765/admin` and authenticate with the
separate admin token. The dashboard shows connection and interaction-idle
durations, client/source details, and a control to disconnect an individual
viewer stream or all active streams. The viewer and admin tokens must not match.
Bulk disconnect stops live updates but does not revoke the shared viewer token;
users who retain it can reload and reconnect.

Running the setup command again replaces both stored tokens. Stop every old
viewer process and restart the server afterward because each running process
keeps the tokens it loaded at startup. Launch without `--token` or
`--admin-token` when you intend to use the stored values.

Run `python -m pytest tests/test_viewer.py -q` to validate viewer tailing,
reconnects, concurrent streams, authentication, activity tracking, and admin
disconnect controls.

For a single fixed file with no selector, use `--file` instead of `--directory`.

Allow TCP port 8765 only on the Windows Private network. The bearer token is
sent over plain HTTP, so this setup is intended for a trusted LAN. Use HTTPS or
a VPN on an untrusted network or across the internet.

Uvicorn's `--workers N` processes are created outside the application, so they
cannot share this in-process queue. Use one Uvicorn worker, or assign each worker
its own log file.

### Forking on POSIX

`configure_logging()` starts a listener thread and a `multiprocessing.Manager`
process, so the configuring process is multi-threaded from then on. Python 3.12
and newer raise a `DeprecationWarning` when such a process calls `fork()`, and
because `capture_warnings` is on by default that warning is written to the log
file like any other record. Prefer the `spawn` or `forkserver` start method, fork
your workers before configuring logging, or set `capture_warnings=False` if the
noise is unwanted.

## Development and releases

Development dependencies are defined in `pyproject.toml`; there is no separate
requirements file. The `test` extra installs the test suite dependencies, while
`dev` adds the build, publishing, release, and example-server tools. Install both
for a complete contributor environment:

```bash
python -m pip install --editable ".[test,dev]"
python -m pytest
python -m build
python -m twine check dist/*
```

Work on a branch and record every user-visible change under `## [Unreleased]` in
`CHANGELOG.md`, in the same commit as the code. Release from `main` once the
changes are merged:

```bash
bump-my-version bump patch      # or minor / major / --new-version X.Y.Z
git push --follow-tags
```

That single command rewrites the version in `pyproject.toml`, promotes the
`Unreleased` section of `CHANGELOG.md` to the new version, commits, and creates
the matching `vX.Y.Z` tag. Add `--dry-run --verbose` to preview it first.

The package can also be uploaded to PyPI from the generated files in `dist/`.

## License

MIT
