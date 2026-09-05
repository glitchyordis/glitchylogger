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

## Development and releases

Development dependencies are defined in `pyproject.toml`; there is no separate
requirements file. The `test` extra installs the test suite dependencies, while
`dev` adds the build, publishing, and example-server tools. Install both for a
complete contributor environment:

```bash
python -m pip install --editable ".[test,dev]"
python -m pytest
python -m build
python -m twine check dist/*
```

Create immutable releases so consuming repositories can upgrade deliberately:

```bash
git tag v0.1.0
git push origin main v0.1.0
```

The package can also be uploaded to PyPI from the generated files in `dist/`.

## License

MIT
