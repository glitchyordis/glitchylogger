# GlitchyLogger

Process-safe and thread-safe Python logging with JSON Lines output and a log file
that can be switched while the application is running.

GlitchyLogger uses one listener thread and one file handle. Threads and child
processes send records through a shared queue, avoiding competing writes to the
same file.

## Requirements

- Python 3.11 or newer
- No runtime dependencies

## Install

Install a tagged release directly from GitHub:

```bash
python -m pip install "glitchylogger @ git+https://github.com/glitchyordis/glitchylogger.git@v0.1.0"
```

In another project's `pyproject.toml`, pin the same tag for reproducible builds:

```toml
[project]
dependencies = [
	"glitchylogger @ git+https://github.com/glitchyordis/glitchylogger.git@v0.1.0",
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
