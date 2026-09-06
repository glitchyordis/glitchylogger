# Log Viewer Guide

GlitchyLogger includes an optional browser viewer for following JSON Lines logs
in real time. The viewer reads existing files without changing, moving, or
deleting them.

## What You Need

- Python 3.11 or newer on the computer that owns the log files.
- The `viewer` optional dependencies installed on that computer.
- A `.log` or `.jsonl` file written as one JSON object per line.
- A modern browser on the same computer or another computer on the LAN.

## Install

From the GlitchyLogger repository, install the package and viewer dependencies:

```powershell
python -m pip install --editable ".[viewer]"
```

Confirm that the command is available:

```powershell
glitchylogger-viewer --help
```

If the command is not on `PATH`, use the module form instead:

```powershell
python -m glitchylogger.viewer --help
```

## Store Tokens on Windows

Run the setup command once under the same Windows account that will launch the
viewer:

```powershell
glitchylogger-store-viewer-secrets
```

It prompts without echoing and stores two entries in Windows Credential
Manager under the `glitchylogger` service: `viewer-token` and `admin-token`.
The values must be nonempty and different. Running the command again replaces
both values.

At the prompts, enter the credentials according to their roles:

```text
Viewer token:  shared password accepted by the main viewer
Admin token:   different privileged password accepted by the admin dashboard
```

If the command is not on `PATH`, use:

```powershell
python -c "from glitchylogger.viewer import store_credentials; store_credentials()"
```

Stored credentials belong to the current Windows account. If Task Scheduler,
a Windows service, or another account launches the viewer, store the entries
while running as that account or supply environment variables to that process.

The server resolves each token in this order:

1. Explicit `--token` or `--admin-token` option.
2. `GLITCHYLOGGER_VIEWER_TOKEN` or `GLITCHYLOGGER_ADMIN_TOKEN` environment
  variable.
3. The corresponding system credential-store entry.

To remove both stored entries without displaying their values:

```powershell
python -c "import keyring; keyring.delete_password('glitchylogger', 'viewer-token'); keyring.delete_password('glitchylogger', 'admin-token')"
```

Credential Manager only supplies secrets when the server starts. Browser users
still enter the viewer token on `/`, while administrators enter the distinct
admin token on `/admin`.

## Choose a Source Mode

The viewer requires either `--directory` or `--file`. They cannot be used
together.

### Directory Mode

Directory mode is recommended when the application switches between log files.
It discovers direct child files ending in `.log` or `.jsonl`.

```powershell
glitchylogger-viewer --directory "C:\ProgramData\MyApp\logs"
```

In the browser, **Latest file (auto)** follows the most recently modified file.
Use the **Log source** selector to pin the viewer to a specific file instead.
If the application creates or updates a newer file, automatic mode changes to
that file and resets the displayed rows.

Use the folder button beside **Log source** to change the directory while the
viewer is running. The selector starts at the current directory and lists
folders on the computer running the viewer. Select a child folder, use **Up**
to open its parent, or enter an absolute or UNC path manually. Choose
**Use directory** to switch and return to automatic latest-file mode.

Directory and file selections belong to the current browser tab. Another user
can independently follow the same file or choose a different directory and
file without changing this view. Every connected stream receives records
appended to its selected file. Reloading a tab restores the default path
supplied through `--directory`.

#### Why the Selector Is Server-Side

Browser-native file and directory pickers browse the computer running the web
browser. They select local files for upload or grant a page temporary access
to local content. Browsers also do not expose the selected folder's absolute
path to a remote server.

When the viewer is opened from another PC, those native pickers would browse
the wrong filesystem. GlitchyLogger therefore provides its own authenticated
selector for directories visible to the viewer process on the logging host.

For the repository's multiprocessing example:

```powershell
glitchylogger-viewer --directory "examples\demo-logs"
```

### Single-File Mode

Use single-file mode when the application always writes to one stable path:

```powershell
glitchylogger-viewer --file "C:\ProgramData\MyApp\logs\app.jsonl"
```

The source selector is disabled in this mode.

## Open the Viewer Locally

The default address is loopback-only, so it is accessible only on the logging
computer:

```text
http://127.0.0.1:8765
```

Enter the viewer token stored at the `Viewer token:` prompt. The browser keeps
the token in session storage, which is cleared when that browser session ends.

Stop the viewer with `Ctrl+C` in its terminal.

## Open the Viewer from Another Computer

Bind the viewer to all network interfaces on the logging computer:

```powershell
glitchylogger-viewer `
  --directory "C:\ProgramData\MyApp\logs" `
  --host 0.0.0.0 `
  --port 8765
```

Find the logging computer's hostname:

```powershell
hostname
```

From the other computer, open:

```text
http://LOGGER-PC:8765
```

If hostname resolution is unavailable, use the logging computer's LAN IP
address instead. Allow inbound TCP port `8765` through Windows Firewall only on
the **Private** network profile.

The built-in server uses plain HTTP. A bearer token prevents casual unauthorized
access, but it does not encrypt traffic. Use this setup only on a trusted LAN.
Use HTTPS through a reverse proxy or connect through a VPN on an untrusted
network. Do not expose the viewer directly to the internet.

## Monitor Viewer Sessions

Open the admin dashboard on the same host and port:

```text
http://LOGGER-PC:8765/admin
```

Enter the password stored at the `Admin token:` prompt, not the viewer token.
The tokens must be different. The dashboard refreshes every two seconds and
shows each active connection's client address, browser user agent, selected
source, connection duration, idle duration, and start time.

Idle time measures browser interaction, including pointer, keyboard, wheel,
and touch input. Reports are throttled to once every five seconds, and incoming
log records do not reset the idle timer. A connection represents a browser tab,
not a verified person; users behind the same proxy may show the same address.

Select **Disconnect** to end a connection. The affected tab displays
**Disconnected by administrator** and does not automatically reconnect. This
does not ban the user: reloading the page or selecting a source can establish a
new connection when the user still has the viewer token.

Select **Disconnect all** to end every active viewer connection after a
confirmation prompt. The button is disabled when no viewers are connected.
Each affected tab stops receiving new records and does not reconnect
automatically. Records already rendered in that tab remain visible until the
user clears, reloads, or closes it.

Disconnecting all viewers does not revoke the viewer token or prevent later
connections. A user who still has the viewer token can reload and reconnect.
Run `glitchylogger-store-viewer-secrets` again and restart the server when
access must be revoked for everyone. This replaces both role tokens. Per-user
revocation requires separate user credentials, which this shared-token viewer
does not provide.

The bulk endpoint is also available to administrative tooling:

```powershell
$headers = @{ Authorization = "Bearer $env:GLITCHYLOGGER_ADMIN_TOKEN" }
Invoke-RestMethod `
  "http://127.0.0.1:8765/api/admin/sessions" `
  -Method Delete `
  -Headers $headers
```

The response reports how many previously connected sessions were signaled:

```json
{"disconnected": 3}
```

## Viewer Controls

### Sources and Filtering

- **Log source** searches file names and selects automatic latest-file mode or
  a specific file. **Latest file (auto)** always remains at the top.
- **Change log directory** opens a server-side folder selector in directory
  mode. Browse into child folders, move up to a parent, or enter a path such as
  a UNC share. The selected folder must exist on the viewer host.
- **Logger** searches known logger names with case-insensitive partial matching.
  Select a result to show only records whose logger exactly matches it, or
  select **All loggers** to remove the logger filter.
- **Search** performs a case-insensitive search across the complete JSON record,
  including messages, request IDs, correlation IDs, and custom fields.
- **DEBUG**, **INFO**, **WARNING**, **ERROR**, **CRITICAL**, and **PARSE** toggle
  individual severity levels.

Anyone with the viewer token can browse and switch to any directory readable
by the viewer process, then inspect its `.log` and `.jsonl` files. Treat the
token as an operator credential, not as a read-only sharing link.

### Live Viewing

- **Pause** keeps receiving logs but temporarily holds them outside the visible
  list. Select **Resume** to add the buffered records.
- **Follow** automatically scrolls to the newest visible row.
- **Clear** removes records from the browser only. It does not modify the file.
- Select a row to expand the complete formatted JSON object.
- **Index** identifies a record's arrival position in the current source
  session. Filtering may leave gaps, and the index restarts when the source
  changes or resets.

The browser retains up to the most recent 1,000 records for searching and
initially renders the newest 250 matching rows to remain responsive during
bursts. Because rows are chronological, scroll upward to load older retained
rows in batches of 250. Scrolling downward continues toward newer records.

The record counter shows how many matching rows are rendered and how many
records are searchable. When the initial file tail or subsequent live traffic
exceeds the 1,000-record browser window, it also displays **older records exist
on disk**. Those older records remain in the log file but are not searchable in
the current browser session.

### Copying Records

Move the pointer over a row to reveal its compact copy icons. Hover or focus an
icon to see its label. The controls remain visible on touch devices.

- **Timestamp** copies the record's raw `ts` value exactly as received, which
  can be searched in the source log file.
- **Message** copies only the `msg` value.
- **JSONL** copies the complete record as one compact JSON line.

The button briefly displays **Copied** after a successful copy. Copying does not
modify the source file.

## Command Options

```text
--directory PATH   Watch selectable .log and .jsonl files in a directory
--file PATH        Follow one fixed log file
--host ADDRESS     Bind address; default: 127.0.0.1
--port PORT        HTTP port; default: 8765
--tail COUNT       Initial number of complete records; default: 1000
--token TOKEN      Access token
--admin-token TOKEN  Separate admin dashboard token
```

Prefer the system credential store described above. Environment variables
override stored credentials; command-line values override both but may be
visible in command history or process listings:

```powershell
$env:GLITCHYLOGGER_VIEWER_TOKEN = "replace-with-a-long-random-token"
$env:GLITCHYLOGGER_ADMIN_TOKEN = "replace-with-a-different-admin-token"
```

## Check Viewer Health

The authenticated health endpoint reports the source mode and active file:

```powershell
$headers = @{ Authorization = "Bearer $env:GLITCHYLOGGER_VIEWER_TOKEN" }
Invoke-RestMethod "http://127.0.0.1:8765/healthz" -Headers $headers
```

An expected response resembles:

```json
{
  "ok": true,
  "mode": "directory",
  "file": "C:\\ProgramData\\MyApp\\logs\\app.jsonl",
  "exists": true
}
```

## Validate the Viewer

Run the focused viewer tests from the repository root:

```powershell
python -m pytest tests/test_viewer.py -q
```

The suite covers JSONL tailing and partial records, malformed input, file
truncation, offset-based reconnects, automatic latest-file switching,
independent same-file and different-file streams, authentication boundaries,
activity timing, individual and bulk disconnection, disabled admin mode, and
packaged browser assets. The full repository suite is available with
`python -m pytest -q`.

## Troubleshooting

### The command is not recognized

Install the viewer extra in the active Python environment, or launch it with
`python -m glitchylogger.viewer`.

If `glitchylogger-store-viewer-secrets` specifically is not recognized after
updating the source, reinstall the editable package so its new console script
is generated:

```powershell
python -m pip install --editable ".[viewer]"
```

The direct equivalent is:

```powershell
python -c "from glitchylogger.viewer import store_credentials; store_credentials()"
```

### The page does not open remotely

Confirm that the viewer was launched with `--host 0.0.0.0`, that the process is
still running, and that the selected port is allowed through the logging
computer's Private-network firewall.

### The token is rejected

Tokens are case-sensitive. Use the viewer token on `/` and the different admin
token on `/admin`. Explicit `--token` and `--admin-token` arguments override
environment variables, which in turn override Credential Manager.

After running `glitchylogger-store-viewer-secrets` again, stop all older viewer
processes and start a new one without explicit token arguments. Each running
process retains the credentials it loaded at startup. Also confirm that another
viewer is not already listening on the same host and port; otherwise the browser
may still reach the older process.

### No log files appear

Directory mode lists only direct child files with `.log` or `.jsonl` suffixes.
Confirm the directory path and file extension. Nested directories are not
searched.

### New records do not appear

Confirm the application is appending complete newline-terminated JSON objects.
In directory mode, select **Latest file (auto)** or choose the current file. Use
the health endpoint to confirm which file the server considers active.

### The page still shows an older interface

Reload without browser cache using `Ctrl+F5`.

### Copy reports a failure

Browser clipboard policies vary. The viewer first uses a selection-based copy
for compatibility with embedded browsers and LAN HTTP, then falls back to the
modern Clipboard API. Keep the viewer tab active and allow clipboard access if
prompted.

## Operational Notes

- Run the viewer on the same computer as the files. Avoid tailing an SMB path if
  local access is available.
- The viewer is read-only and does not control `set_log_file()`.
- File offsets are maintained per browser connection. Reconnecting resumes from
  the last received offset when the source is unchanged.
- Directory selection, file selection, filters, pause state, and retained rows
  are independent per browser tab. One to three users can follow the same or
  different files concurrently, and each live stream receives new records for
  its selected file.
- Closing or navigating away from a viewer tab closes its stream. FastAPI then
  cancels that connection's stream task, and its follower, offset, and request
  state are released. Log files are opened only for individual reads, so the
  viewer does not keep a file handle open for each connected user.
- An abruptly lost network connection may remain until the operating system
  detects the dead socket. The viewer sends an SSE heartbeat approximately
  every 15 seconds so stale connections are detected without log activity.
- The server does not retain a persistent user session or per-user record
  cache after disconnection. Browser records and controls are discarded with
  the tab; reconnecting creates a new stream and resumes only when that tab can
  supply its previous file offset.
- File truncation or replacement resets the displayed records safely.
- This viewer is intended for recent operational inspection, not long-term log
  retention or multi-host aggregation.