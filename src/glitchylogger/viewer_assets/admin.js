const state = {
  token: sessionStorage.getItem("glitchylogger-admin-token"),
  refreshTimer: null,
  disconnectingAll: false,
};

const elements = {
  status: document.querySelector("#adminStatus"),
  dot: document.querySelector("#adminDot"),
  count: document.querySelector("#sessionCount"),
  rows: document.querySelector("#sessionRows"),
  empty: document.querySelector("#emptySessions"),
  refresh: document.querySelector("#refreshButton"),
  disconnectAll: document.querySelector("#disconnectAllButton"),
  dialog: document.querySelector("#adminTokenDialog"),
  form: document.querySelector("#adminTokenForm"),
  input: document.querySelector("#adminTokenInput"),
  error: document.querySelector("#adminTokenError"),
};

function setStatus(text, connected = false) {
  elements.status.textContent = text;
  elements.dot.classList.toggle("offline", !connected);
}

function formatDuration(seconds) {
  const value = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  const remainder = value % 60;
  if (hours) return `${hours}h ${minutes}m`;
  if (minutes) return `${minutes}m ${remainder}s`;
  return `${remainder}s`;
}

function formatStarted(value) {
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? value : parsed.toLocaleString();
}

function cell(className, primary, secondary = "") {
  const item = document.createElement("span");
  item.className = className;
  const main = document.createElement("strong");
  main.textContent = primary;
  item.append(main);
  if (secondary) {
    const detail = document.createElement("small");
    detail.textContent = secondary;
    detail.title = secondary;
    item.append(detail);
  }
  return item;
}

function renderSessions(sessions) {
  const rows = sessions.map((session) => {
    const row = document.createElement("div");
    row.className = "session-row";
    row.role = "row";

    const client = cell(
      "session-client",
      `${session.remote_host || "Unknown client"} · ${session.id.slice(0, 8)}`,
      session.user_agent || "User agent unavailable",
    );
    client.role = "cell";

    const source = cell(
      "session-source",
      session.active_file || "Waiting for file",
      session.directory || "Fixed file mode",
    );
    source.role = "cell";

    const connected = cell("session-duration", formatDuration(session.connected_seconds));
    connected.role = "cell";

    const idle = cell("session-idle", formatDuration(session.idle_seconds));
    idle.role = "cell";
    if (session.idle_seconds >= 300) idle.classList.add("stale");

    const started = cell("session-started", formatStarted(session.connected_at));
    started.role = "cell";

    const action = document.createElement("span");
    action.className = "session-action";
    action.role = "cell";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "disconnect-button";
    button.dataset.sessionId = session.id;
    button.textContent = session.disconnecting ? "Disconnecting" : "Disconnect";
    button.disabled = session.disconnecting;
    button.setAttribute(
      "aria-label",
      `Disconnect viewer ${session.id.slice(0, 8)} at ${session.remote_host || "unknown client"}`,
    );
    action.append(button);

    row.append(client, source, connected, idle, started, action);
    return row;
  });

  elements.rows.replaceChildren(...rows);
  elements.empty.hidden = sessions.length > 0;
  elements.count.textContent = `${sessions.length} connected`;
  const disableAll = sessions.length === 0 || state.disconnectingAll;
  if (elements.disconnectAll.disabled !== disableAll) {
    elements.disconnectAll.disabled = disableAll;
  }
}

async function refreshSessions() {
  window.clearTimeout(state.refreshTimer);
  if (!state.token) {
    elements.dialog.showModal();
    return;
  }
  try {
    const response = await fetch("/api/admin/sessions", {
      headers: { Authorization: `Bearer ${state.token}` },
      cache: "no-store",
    });
    if (response.status === 401) throw new Error("The admin token was not accepted.");
    if (!response.ok) throw new Error(`Session request failed (${response.status}).`);
    const payload = await response.json();
    renderSessions(payload.sessions);
    setStatus("Session monitor connected", true);
    sessionStorage.setItem("glitchylogger-admin-token", state.token);
    elements.dialog.close();
  } catch (error) {
    setStatus(error.message);
    if (String(error.message).includes("token")) {
      sessionStorage.removeItem("glitchylogger-admin-token");
      state.token = null;
      elements.error.textContent = error.message;
      elements.dialog.showModal();
      return;
    }
  }
  state.refreshTimer = window.setTimeout(refreshSessions, 2_000);
}

async function disconnectSession(sessionId) {
  const response = await fetch(`/api/admin/sessions/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${state.token}` },
  });
  if (!response.ok && response.status !== 404) {
    throw new Error(`Disconnect failed (${response.status}).`);
  }
  await refreshSessions();
}

async function disconnectAllSessions() {
  if (!window.confirm("Disconnect all active viewers?")) return;
  window.clearTimeout(state.refreshTimer);
  state.disconnectingAll = true;
  elements.disconnectAll.disabled = true;
  try {
    const response = await fetch("/api/admin/sessions", {
      method: "DELETE",
      headers: { Authorization: `Bearer ${state.token}` },
    });
    if (!response.ok) throw new Error(`Disconnect all failed (${response.status}).`);
    const payload = await response.json();
    setStatus(`Disconnected ${payload.disconnected} viewer${payload.disconnected === 1 ? "" : "s"}`, true);
  } finally {
    state.disconnectingAll = false;
  }
  window.setTimeout(refreshSessions, 150);
}

elements.form.addEventListener("submit", (event) => {
  event.preventDefault();
  elements.error.textContent = "";
  state.token = elements.input.value;
  refreshSessions();
});

elements.refresh.addEventListener("click", refreshSessions);
elements.disconnectAll.addEventListener("click", async () => {
  try {
    await disconnectAllSessions();
  } catch (error) {
    setStatus(error.message);
    elements.disconnectAll.disabled = false;
  }
});
elements.rows.addEventListener("click", async (event) => {
  const button = event.target.closest(".disconnect-button");
  if (!button) return;
  button.disabled = true;
  try {
    await disconnectSession(button.dataset.sessionId);
  } catch (error) {
    setStatus(error.message);
    button.disabled = false;
  }
});

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refreshSessions();
});

if (state.token) refreshSessions();
else elements.dialog.showModal();
