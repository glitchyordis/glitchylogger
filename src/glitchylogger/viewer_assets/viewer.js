const MAX_RECORDS = 1000;
const MAX_RENDERED = 250;
const RENDER_BATCH = 250;
const LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "PARSE_ERROR"];
const state = {
  records: [],
  enabledLevels: new Set(LEVELS),
  paused: false,
  pending: [],
  renderScheduled: false,
  renderLimit: MAX_RENDERED,
  filteredCount: 0,
  preserveScroll: null,
  historyTruncated: false,
  nextRecordIndex: 0,
  loggerNames: new Set(),
  selectedLogger: "",
  loggerQuery: "",
  loggerSuggestions: [],
  loggerSuggestionIndex: -1,
  controller: null,
  lastOffset: null,
  activeFile: null,
  selectedFile: "",
  availableFiles: [],
  latestFile: null,
  currentDirectory: null,
  fileMode: "directory",
  fileSuggestions: [],
  fileSuggestionIndex: -1,
  fileQuery: "",
  token: null,
  sessionId: null,
  lastActivityReport: 0,
  disconnectedByAdmin: false,
};

const elements = {
  rows: document.querySelector("#logRows"),
  empty: document.querySelector("#emptyState"),
  search: document.querySelector("#searchInput"),
  fileSearch: document.querySelector("#fileSearch"),
  fileSuggestions: document.querySelector("#fileSuggestions"),
  directoryButton: document.querySelector("#directoryButton"),
  directoryDialog: document.querySelector("#directoryDialog"),
  directoryForm: document.querySelector("#directoryForm"),
  directoryInput: document.querySelector("#directoryInput"),
  directoryError: document.querySelector("#directoryError"),
  directoryCancel: document.querySelector("#directoryCancel"),
  directoryUp: document.querySelector("#directoryUp"),
  directoryChoices: document.querySelector("#directoryChoices"),
  directoryBrowseStatus: document.querySelector("#directoryBrowseStatus"),
  logger: document.querySelector("#loggerFilter"),
  loggerSuggestions: document.querySelector("#loggerSuggestions"),
  levels: document.querySelector("#levelFilters"),
  pause: document.querySelector("#pauseButton"),
  autoScroll: document.querySelector("#autoScroll"),
  clear: document.querySelector("#clearButton"),
  count: document.querySelector("#recordCount"),
  connectionText: document.querySelector("#connectionText"),
  connectionDot: document.querySelector("#connectionDot"),
  dialog: document.querySelector("#tokenDialog"),
  tokenForm: document.querySelector("#tokenForm"),
  tokenInput: document.querySelector("#tokenInput"),
  tokenError: document.querySelector("#tokenError"),
};

function setConnection(text, connected = false) {
  elements.connectionText.textContent = text;
  elements.connectionDot.classList.toggle("offline", !connected);
}

function reportActivity() {
  if (!state.token || !state.sessionId) return;
  const now = Date.now();
  if (now - state.lastActivityReport < 5_000) return;
  state.lastActivityReport = now;
  void fetch(`/api/viewer/sessions/${encodeURIComponent(state.sessionId)}/activity`, {
    method: "POST",
    headers: { Authorization: `Bearer ${state.token}` },
    keepalive: true,
  }).catch(() => {});
}

function displayTime(value) {
  if (!value) return "No timestamp";
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf())
    ? String(value)
    : parsed.toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      fractionalSecondDigits: 3,
      hour12: false,
    });
}

function createText(className, text) {
  const span = document.createElement("span");
  span.className = className;
  span.textContent = text;
  return span;
}

async function copyText(text) {
  const activeElement = document.activeElement;
  const input = document.createElement("textarea");
  input.value = text;
  input.setAttribute("aria-hidden", "true");
  input.style.position = "fixed";
  input.style.left = "-9999px";
  input.style.opacity = "0";
  document.body.append(input);
  input.focus();
  input.select();
  input.setSelectionRange(0, input.value.length);
  let copied = false;
  try {
    copied = document.execCommand("copy");
  } finally {
    input.remove();
    activeElement?.focus({ preventScroll: true });
  }
  if (copied) return;
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }
  throw new Error("Clipboard access is unavailable");
}

function createCopyButton(label, value, iconName) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "copy-button";
  const actionLabel = `Copy ${label.toLowerCase()}`;
  button.dataset.tooltip = actionLabel;
  button.setAttribute("aria-label", actionLabel);
  const icon = document.createElement("span");
  icon.className = `copy-target-icon ${iconName}-icon`;
  icon.setAttribute("aria-hidden", "true");
  const status = document.createElement("span");
  status.className = "sr-only";
  status.setAttribute("aria-live", "polite");
  button.append(icon, status);
  button.addEventListener("click", async (event) => {
    event.preventDefault();
    event.stopPropagation();
    try {
      await copyText(value);
      status.textContent = `${label} copied`;
      button.dataset.tooltip = `${label} copied`;
      button.classList.add("copied");
    } catch {
      status.textContent = `Failed to copy ${label.toLowerCase()}`;
      button.dataset.tooltip = "Copy failed";
      button.classList.add("failed");
    }
    window.setTimeout(() => {
      status.textContent = "";
      button.dataset.tooltip = actionLabel;
      button.classList.remove("copied", "failed");
    }, 1_200);
  });
  return button;
}

function render() {
  state.renderScheduled = false;
  const preservedScroll = state.preserveScroll;
  state.preserveScroll = null;
  const query = elements.search.value.trim().toLocaleLowerCase();
  const logger = state.selectedLogger;
  const filtered = state.records.filter((item) => {
    const record = item.record;
    const level = String(record.level || "INFO").toUpperCase();
    return state.enabledLevels.has(level)
      && (!logger || record.logger === logger)
      && (!query || item.search.includes(query));
  });
  state.filteredCount = filtered.length;
  const visible = filtered.slice(-state.renderLimit);

  const fragment = document.createDocumentFragment();
  for (const item of visible) {
    const record = item.record;
    const level = String(record.level || "INFO").toUpperCase();
    const details = document.createElement("details");
    details.className = "log-entry";
    const summary = document.createElement("summary");
    summary.className = "log-summary";
    const timestamp = createText("timestamp", displayTime(record.ts));
    timestamp.title = String(record.ts || "");
    summary.append(
      createText("row-index", String(item.recordIndex)),
      timestamp,
      createText(`level level-${level.toLowerCase()}`, level),
      createText("logger", String(record.logger || "-")),
      createText("message", String(record.msg || "")),
    );
    const actions = document.createElement("span");
    actions.className = "row-actions";
    actions.append(
      createCopyButton("Timestamp", String(record.ts ?? ""), "timestamp"),
      createCopyButton("Message", String(record.msg || ""), "message"),
      createCopyButton("JSONL", JSON.stringify(record), "json"),
    );
    summary.append(actions);
    const detail = document.createElement("pre");
    detail.className = "record-detail";
    detail.textContent = JSON.stringify(record, null, 2);
    details.append(summary, detail);
    fragment.append(details);
  }
  elements.rows.replaceChildren(fragment);
  elements.empty.textContent = state.records.length ? "No records match the current filters." : "Waiting for log records...";
  elements.empty.classList.toggle("hidden", filtered.length > 0);
  const status = [
    filtered.length > visible.length
      ? `latest ${visible.length} of ${filtered.length} shown`
      : `${visible.length} shown`,
    `${state.records.length} searchable`,
  ];
  if (filtered.length > visible.length) status.push("scroll up for older");
  if (state.historyTruncated) status.push("older records exist on disk");
  elements.count.textContent = status.join(" · ");
  if (preservedScroll) {
    elements.rows.scrollTop = elements.rows.scrollHeight - preservedScroll.height + preservedScroll.top;
  } else if (elements.autoScroll.checked) {
    elements.rows.scrollTop = elements.rows.scrollHeight;
  }
}

function resetRenderWindow() {
  state.renderLimit = MAX_RENDERED;
  state.preserveScroll = null;
}

function scheduleRender() {
  if (state.renderScheduled) return;
  state.renderScheduled = true;
  window.setTimeout(render, 100);
}

function refreshLoggers() {
  if (state.selectedLogger && !state.loggerNames.has(state.selectedLogger)) state.selectedLogger = "";
  renderLoggerSuggestions(!elements.loggerSuggestions.hidden);
}

function closeLoggerSuggestions() {
  state.loggerSuggestionIndex = -1;
  elements.loggerSuggestions.hidden = true;
  elements.logger.setAttribute("aria-expanded", "false");
  elements.logger.removeAttribute("aria-activedescendant");
}

function restoreSelectedLoggerLabel() {
  elements.logger.value = state.selectedLogger || "All loggers";
}

function renderLoggerSuggestions(showSuggestions = false, queryText = state.loggerQuery) {
  const query = queryText.trim().toLocaleLowerCase();
  const names = [...state.loggerNames]
    .sort((left, right) => left.localeCompare(right))
    .filter((name) => name.toLocaleLowerCase().includes(query));
  state.loggerSuggestions = [
    { name: "All loggers", value: "" },
    ...names.map((name) => ({ name, value: name })),
  ];
  const suggestions = state.loggerSuggestions.map((suggestion, index) => {
    const option = document.createElement("li");
    option.id = `logger-suggestion-${index}`;
    option.className = suggestion.value === state.selectedLogger ? "selected" : "";
    option.role = "option";
    option.dataset.value = suggestion.value;
    option.setAttribute("aria-selected", "false");
    option.textContent = suggestion.name;
    return option;
  });
  elements.loggerSuggestions.replaceChildren(...suggestions);
  state.loggerSuggestionIndex = -1;
  elements.logger.removeAttribute("aria-activedescendant");
  elements.loggerSuggestions.hidden = !showSuggestions;
  elements.logger.setAttribute("aria-expanded", String(showSuggestions));
  if (!showSuggestions) restoreSelectedLoggerLabel();
}

function highlightLoggerSuggestion(index) {
  const options = [...elements.loggerSuggestions.children];
  if (!options.length) return;
  state.loggerSuggestionIndex = (index + options.length) % options.length;
  for (const [optionIndex, option] of options.entries()) {
    const active = optionIndex === state.loggerSuggestionIndex;
    option.classList.toggle("active", active);
    option.setAttribute("aria-selected", String(active));
  }
  const activeOption = options[state.loggerSuggestionIndex];
  elements.logger.setAttribute("aria-activedescendant", activeOption.id);
  activeOption.scrollIntoView({ block: "nearest" });
}

function selectLogger(value) {
  state.selectedLogger = value;
  state.loggerQuery = "";
  restoreSelectedLoggerLabel();
  closeLoggerSuggestions();
  resetRenderWindow();
  render();
}

function addRecord(record, offset) {
  state.nextRecordIndex += 1;
  const item = {
    record,
    offset,
    recordIndex: state.nextRecordIndex,
    search: JSON.stringify(record).toLocaleLowerCase(),
  };
  if (state.paused) {
    state.pending.push(item);
    if (state.pending.length > MAX_RECORDS) {
      state.pending.shift();
      state.historyTruncated = true;
    }
    elements.pause.textContent = `Resume (${state.pending.length})`;
    return;
  }
  state.records.push(item);
  if (state.records.length > MAX_RECORDS) {
    state.records.splice(0, state.records.length - MAX_RECORDS);
    state.historyTruncated = true;
  }
  if (record.logger && !state.loggerNames.has(record.logger)) {
    state.loggerNames.add(record.logger);
    refreshLoggers();
  }
  scheduleRender();
}

function closeFileSuggestions() {
  state.fileSuggestionIndex = -1;
  elements.fileSuggestions.hidden = true;
  elements.fileSearch.setAttribute("aria-expanded", "false");
  elements.fileSearch.removeAttribute("aria-activedescendant");
}

function selectedFileLabel() {
  if (state.selectedFile) return state.selectedFile;
  return state.latestFile
    ? `Latest file (auto): ${state.latestFile}`
    : "Latest file (waiting)";
}

function restoreSelectedFileLabel() {
  elements.fileSearch.value = selectedFileLabel();
}

function highlightFileSuggestion(index) {
  const options = [...elements.fileSuggestions.children];
  if (!options.length) return;
  state.fileSuggestionIndex = (index + options.length) % options.length;
  for (const [optionIndex, option] of options.entries()) {
    const active = optionIndex === state.fileSuggestionIndex;
    option.classList.toggle("active", active);
    option.setAttribute("aria-selected", String(active));
  }
  const activeOption = options[state.fileSuggestionIndex];
  elements.fileSearch.setAttribute("aria-activedescendant", activeOption.id);
  activeOption.scrollIntoView({ block: "nearest" });
}

function selectFileSuggestion(value) {
  state.selectedFile = value;
  state.fileQuery = "";
  restoreSelectedFileLabel();
  closeFileSuggestions();
  state.records = [];
  state.pending = [];
  state.loggerNames.clear();
  state.lastOffset = null;
  state.activeFile = null;
  state.historyTruncated = false;
  state.nextRecordIndex = 0;
  resetRenderWindow();
  refreshLoggers();
  scheduleRender();
  if (state.token) {
    state.disconnectedByAdmin = false;
    connect(state.token);
  }
}

function renderFileSuggestions(showSuggestions = false, queryText = state.fileQuery) {
  const query = queryText.trim().toLocaleLowerCase();
  const latestLabel = state.latestFile
    ? `Latest file (auto): ${state.latestFile}`
    : "Latest file (waiting)";
  const matchingFiles = state.availableFiles.filter((file) => file.name.toLocaleLowerCase().includes(query));
  state.fileSuggestions = [
    { name: latestLabel, value: "" },
    ...matchingFiles.slice(0, 8).map((file) => ({ name: file.name, value: file.name })),
  ];
  const suggestions = state.fileSuggestions.map((suggestion, index) => {
    const option = document.createElement("li");
    option.id = `file-suggestion-${index}`;
    option.className = suggestion.value === state.selectedFile ? "selected" : "";
    option.role = "option";
    option.dataset.value = suggestion.value;
    option.setAttribute("aria-selected", "false");
    option.textContent = suggestion.name;
    return option;
  });
  elements.fileSuggestions.replaceChildren(...suggestions);
  state.fileSuggestionIndex = -1;
  elements.fileSearch.removeAttribute("aria-activedescendant");
  elements.fileSuggestions.hidden = !showSuggestions;
  elements.fileSearch.setAttribute("aria-expanded", String(showSuggestions));
  if (!showSuggestions) restoreSelectedFileLabel();
}

async function refreshFiles(token) {
  const query = new URLSearchParams();
  if (state.currentDirectory) query.set("directory", state.currentDirectory);
  const suffix = query.size ? `?${query}` : "";
  const response = await fetch(`/api/logs/files${suffix}`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!response.ok) return;
  const payload = await response.json();
  state.availableFiles = payload.files;
  state.latestFile = payload.latest;
  state.currentDirectory = payload.directory;
  state.fileMode = payload.mode;
  if (!payload.files.some((file) => file.name === state.selectedFile)) state.selectedFile = "";
  renderFileSuggestions(!elements.fileSuggestions.hidden);
  const fixed = payload.mode === "file";
  elements.fileSearch.disabled = fixed;
  elements.directoryButton.hidden = fixed;
  elements.directoryButton.disabled = fixed;
  elements.directoryButton.title = state.currentDirectory
    ? `Change log directory (current: ${state.currentDirectory})`
    : "Change log directory";
}

async function changeDirectory(path) {
  const response = await fetch("/api/logs/directory", {
    method: "PUT",
    headers: {
      Authorization: `Bearer ${state.token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ path }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || `Directory change failed (${response.status}).`);
  state.availableFiles = payload.files;
  state.latestFile = payload.latest;
  state.currentDirectory = payload.directory;
  state.selectedFile = "";
  state.fileQuery = "";
  elements.directoryButton.title = `Change log directory (current: ${state.currentDirectory})`;
  renderFileSuggestions();
  selectFileSuggestion("");
}

async function browseDirectory(path) {
  elements.directoryError.textContent = "";
  elements.directoryBrowseStatus.textContent = "Loading folders...";
  elements.directoryChoices.replaceChildren();
  const query = path ? `?${new URLSearchParams({ path })}` : "";
  const response = await fetch(`/api/logs/directories${query}`, {
    headers: { Authorization: `Bearer ${state.token}` },
    cache: "no-store",
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || `Directory browsing failed (${response.status}).`);
  elements.directoryInput.value = payload.path;
  elements.directoryUp.dataset.path = payload.parent || "";
  elements.directoryUp.disabled = !payload.parent;
  elements.directoryBrowseStatus.textContent = payload.directories.length
    ? `${payload.directories.length} folder${payload.directories.length === 1 ? "" : "s"}`
    : "No subfolders";
  const choices = payload.directories.map((directory) => {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "directory-choice";
    button.dataset.path = directory.path;
    const icon = document.createElement("span");
    icon.className = "folder-icon";
    icon.setAttribute("aria-hidden", "true");
    const name = document.createElement("span");
    name.textContent = directory.name;
    button.append(icon, name);
    item.append(button);
    return item;
  });
  elements.directoryChoices.replaceChildren(...choices);
}

function parseFrame(frame) {
  let event = "message";
  let id = null;
  const data = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("id:")) id = Number(line.slice(3).trim());
    else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  if (!data.length) return;
  if (event === "session") {
    const payload = JSON.parse(data.join("\n"));
    state.sessionId = payload.id;
    state.lastActivityReport = Date.now();
    return;
  }
  if (event === "disconnect") {
    const payload = JSON.parse(data.join("\n"));
    state.disconnectedByAdmin = true;
    state.sessionId = null;
    setConnection(payload.reason || "Disconnected by administrator.");
    state.controller?.abort();
    return;
  }
  if (event === "reset") {
    state.records = [];
    state.pending = [];
    state.loggerNames.clear();
    state.lastOffset = null;
    state.historyTruncated = false;
    state.nextRecordIndex = 0;
    resetRenderWindow();
    refreshLoggers();
    scheduleRender();
    return;
  }
  if (event === "source") {
    const payload = JSON.parse(data.join("\n"));
    if (payload.file !== state.activeFile) {
      state.historyTruncated = false;
      state.nextRecordIndex = 0;
      resetRenderWindow();
    }
    state.activeFile = payload.file;
    setConnection(payload.file ? `Live: ${payload.file}` : "Waiting for a log file...", Boolean(payload.file));
    if (state.token) refreshFiles(state.token);
    return;
  }
  if (event === "history") {
    const payload = JSON.parse(data.join("\n"));
    state.historyTruncated = Boolean(payload.older_records);
    scheduleRender();
    return;
  }
  if (event === "log") {
    const record = JSON.parse(data.join("\n"));
    state.lastOffset = id;
    addRecord(record, id);
  }
}

async function connect(token) {
  state.token = token;
  state.sessionId = null;
  state.controller?.abort();
  state.controller = new AbortController();
  const query = new URLSearchParams();
  if (state.currentDirectory) query.set("directory", state.currentDirectory);
  if (state.selectedFile) query.set("file", state.selectedFile);
  if (state.lastOffset !== null) query.set("offset", state.lastOffset);
  if (state.activeFile) query.set("source", state.activeFile);
  const suffix = query.size ? `?${query}` : "";
  setConnection("Connecting...");
  try {
    const response = await fetch(`/api/logs/stream${suffix}`, {
      headers: { Authorization: `Bearer ${token}` },
      signal: state.controller.signal,
      cache: "no-store",
    });
    if (response.status === 401) throw new Error("The access token was not accepted.");
    if (!response.ok || !response.body) throw new Error(`Connection failed (${response.status}).`);
    sessionStorage.setItem("glitchylogger-token", token);
    elements.dialog.close();
    refreshFiles(token);
    setConnection("Live stream connected", true);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true }).replaceAll("\r\n", "\n");
      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) >= 0) {
        parseFrame(buffer.slice(0, boundary));
        buffer = buffer.slice(boundary + 2);
      }
    }
    throw new Error("Stream disconnected.");
  } catch (error) {
    if (error.name === "AbortError") return;
    setConnection(error.message);
    if (String(error.message).includes("token")) {
      sessionStorage.removeItem("glitchylogger-token");
      elements.tokenError.textContent = error.message;
      elements.dialog.showModal();
      return;
    }
    if (state.disconnectedByAdmin) return;
    window.setTimeout(() => connect(token), 1500);
  }
}

for (const level of LEVELS) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = level === "PARSE_ERROR" ? "PARSE" : level;
  button.className = "active";
  button.setAttribute("aria-pressed", "true");
  button.addEventListener("click", () => {
    if (state.enabledLevels.has(level)) state.enabledLevels.delete(level);
    else state.enabledLevels.add(level);
    button.classList.toggle("active", state.enabledLevels.has(level));
    button.setAttribute("aria-pressed", String(state.enabledLevels.has(level)));
    resetRenderWindow();
    render();
  });
  elements.levels.append(button);
}

elements.search.addEventListener("input", () => {
  resetRenderWindow();
  render();
});
elements.fileSearch.addEventListener("input", () => {
  state.fileQuery = elements.fileSearch.value;
  renderFileSuggestions(true);
});
elements.fileSearch.addEventListener("focus", () => {
  state.fileQuery = "";
  elements.fileSearch.select();
  renderFileSuggestions(true);
});
elements.fileSearch.addEventListener("click", () => {
  if (!elements.fileSuggestions.hidden) return;
  state.fileQuery = "";
  elements.fileSearch.select();
  renderFileSuggestions(true);
});
elements.fileSearch.addEventListener("blur", () => {
  state.fileQuery = "";
  restoreSelectedFileLabel();
  closeFileSuggestions();
});
elements.fileSearch.addEventListener("keydown", (event) => {
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    if (elements.fileSuggestions.hidden) renderFileSuggestions(true, "");
    highlightFileSuggestion(state.fileSuggestionIndex + (event.key === "ArrowDown" ? 1 : -1));
  } else if (event.key === "Enter" && (state.fileSuggestionIndex >= 0 || state.fileQuery)) {
    event.preventDefault();
    const index = state.fileSuggestionIndex >= 0
      ? state.fileSuggestionIndex
      : Math.min(1, state.fileSuggestions.length - 1);
    selectFileSuggestion(state.fileSuggestions[index].value);
  } else if (event.key === "Escape") {
    state.fileQuery = "";
    restoreSelectedFileLabel();
    closeFileSuggestions();
    elements.fileSearch.select();
  }
});
elements.fileSuggestions.addEventListener("pointerdown", (event) => {
  const option = event.target.closest("[role=option]");
  if (!option) return;
  event.preventDefault();
  selectFileSuggestion(option.dataset.value);
});
document.addEventListener("pointerdown", (event) => {
  if (!event.target.closest(".source-search")) {
    state.fileQuery = "";
    restoreSelectedFileLabel();
    closeFileSuggestions();
  }
});
elements.directoryButton.addEventListener("click", async () => {
  elements.directoryError.textContent = "";
  elements.directoryInput.value = state.currentDirectory || "";
  elements.directoryDialog.showModal();
  try {
    await browseDirectory(state.currentDirectory);
  } catch (error) {
    elements.directoryError.textContent = error.message;
  }
});
elements.directoryCancel.addEventListener("click", () => elements.directoryDialog.close());
elements.directoryUp.addEventListener("click", async () => {
  try {
    await browseDirectory(elements.directoryUp.dataset.path);
  } catch (error) {
    elements.directoryError.textContent = error.message;
  }
});
elements.directoryChoices.addEventListener("click", async (event) => {
  const choice = event.target.closest(".directory-choice");
  if (!choice) return;
  try {
    await browseDirectory(choice.dataset.path);
  } catch (error) {
    elements.directoryError.textContent = error.message;
  }
});
elements.directoryForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  elements.directoryError.textContent = "";
  try {
    await changeDirectory(elements.directoryInput.value);
    elements.directoryDialog.close();
  } catch (error) {
    elements.directoryError.textContent = error.message;
  }
});
elements.logger.addEventListener("input", () => {
  state.loggerQuery = elements.logger.value;
  renderLoggerSuggestions(true);
});
elements.logger.addEventListener("focus", () => {
  state.loggerQuery = "";
  elements.logger.select();
  renderLoggerSuggestions(true);
});
elements.logger.addEventListener("click", () => {
  if (!elements.loggerSuggestions.hidden) return;
  state.loggerQuery = "";
  elements.logger.select();
  renderLoggerSuggestions(true);
});
elements.logger.addEventListener("blur", () => {
  state.loggerQuery = "";
  restoreSelectedLoggerLabel();
  closeLoggerSuggestions();
});
elements.logger.addEventListener("keydown", (event) => {
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    if (elements.loggerSuggestions.hidden) renderLoggerSuggestions(true, "");
    highlightLoggerSuggestion(state.loggerSuggestionIndex + (event.key === "ArrowDown" ? 1 : -1));
  } else if (event.key === "Enter" && (state.loggerSuggestionIndex >= 0 || state.loggerQuery)) {
    event.preventDefault();
    const index = state.loggerSuggestionIndex >= 0
      ? state.loggerSuggestionIndex
      : Math.min(1, state.loggerSuggestions.length - 1);
    selectLogger(state.loggerSuggestions[index].value);
  } else if (event.key === "Escape") {
    state.loggerQuery = "";
    restoreSelectedLoggerLabel();
    closeLoggerSuggestions();
    elements.logger.select();
  }
});
elements.loggerSuggestions.addEventListener("pointerdown", (event) => {
  const option = event.target.closest("[role=option]");
  if (!option) return;
  event.preventDefault();
  selectLogger(option.dataset.value);
});
elements.rows.addEventListener("scroll", () => {
  if (elements.rows.scrollTop > 48 || state.renderLimit >= state.filteredCount) return;
  state.preserveScroll = {
    height: elements.rows.scrollHeight,
    top: elements.rows.scrollTop,
  };
  state.renderLimit += RENDER_BATCH;
  render();
});
document.addEventListener("pointerdown", (event) => {
  if (!event.target.closest(".logger-search")) {
    state.loggerQuery = "";
    restoreSelectedLoggerLabel();
    closeLoggerSuggestions();
  }
});
elements.clear.addEventListener("click", () => {
  state.records = [];
  state.pending = [];
  state.loggerNames.clear();
  resetRenderWindow();
  refreshLoggers();
  scheduleRender();
});
elements.pause.addEventListener("click", () => {
  state.paused = !state.paused;
  elements.pause.setAttribute("aria-pressed", String(state.paused));
  elements.pause.textContent = state.paused ? `Resume (${state.pending.length})` : "Pause";
  elements.pause.classList.toggle("active", state.paused);
  if (!state.paused && state.pending.length) {
    state.records.push(...state.pending.splice(0));
    if (state.records.length > MAX_RECORDS) {
      state.records.splice(0, state.records.length - MAX_RECORDS);
      state.historyTruncated = true;
    }
    state.loggerNames = new Set(state.records.map((item) => item.record.logger).filter(Boolean));
    refreshLoggers();
    scheduleRender();
  }
});
elements.tokenForm.addEventListener("submit", (event) => {
  event.preventDefault();
  elements.tokenError.textContent = "";
  state.disconnectedByAdmin = false;
  connect(elements.tokenInput.value);
});

for (const eventName of ["pointerdown", "keydown", "wheel", "touchstart"]) {
  document.addEventListener(eventName, reportActivity, { passive: true });
}

const savedToken = sessionStorage.getItem("glitchylogger-token");
if (savedToken) connect(savedToken);
else elements.dialog.showModal();