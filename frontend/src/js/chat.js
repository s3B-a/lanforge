injectNav("chat");

const deviceSelect = document.getElementById("device-select");
const modelSelect = document.getElementById("model-select");
const deviceStatsEl = document.getElementById("device-stats");
const newChatBtn = document.getElementById("new-chat-btn");
const conversationListEl = document.getElementById("conversation-list");
const conversationTitleEl = document.getElementById("conversation-title");
const compactBtn = document.getElementById("compact-btn");
const clearBtn = document.getElementById("clear-btn");
const stopBtn = document.getElementById("stop-btn");
const messagesEl = document.getElementById("messages");
const inputEl = document.getElementById("chat-input");
const sendBtn = document.getElementById("send-btn");
const uploadBtn = document.getElementById("upload-btn");
const fileInput = document.getElementById("file-input");
const previewRow = document.getElementById("image-preview-row");
const statusEl = document.getElementById("chat-status");
const filesDialogOverlay = document.getElementById("files-dialog-overlay");
const filesDialogBody = document.getElementById("files-dialog-body");
const filesDialogClose = document.getElementById("files-dialog-close");

const CAT_ASCII = String.raw`
        /\_/\
       ( o.o )
        > ^ <
  no uploaded files`;

let pendingImages = []; // { dataUrl, base64 }
let viewEpoch = 0;
let statsEpoch = 0;
let pendingCount = 0;
let conversationId = null;
let conversationsCache = [];
let statsIntervalId = null;
let statsLoadInFlight = false;

function apiBase() {
  return `/llm/${encodeURIComponent(deviceSelect.value)}/conversations/${encodeURIComponent(conversationId)}`;
}

function clearEmptyState() {
  if (messagesEl.children.length === 1 && messagesEl.children[0].classList.contains("empty-state")) {
    messagesEl.innerHTML = "";
  }
}

function imageDataUrl(base64) {
  return `data:image/png;base64,${base64}`;
}

function updateStopVisibility() {
  stopBtn.hidden = pendingCount <= 0;
}

function addMessage(role, text, images = []) {
  clearEmptyState();
  const el = document.createElement("div");
  el.className = `msg ${role}`;
  el.textContent = text;
  for (const src of images) {
    const img = document.createElement("img");
    img.src = src;
    el.appendChild(img);
  }

  messagesEl.appendChild(el);
  messagesEl.scrollTop = messagesEl.scrollHeight;

  return el;
}

function buildAssistantBubble() {
  const el = document.createElement("div");
  el.className = "msg assistant";
  el.innerHTML =
    '<details class="thinking" hidden><summary>Thinking...</summary><div class="thinking-body"></div></details>' +
    '<div class="msg-content"><span class="msg-status">queued...</span></div>' +
    '<div class="msg-footer" hidden></div>';
  el._startedAt = Date.now();

  return el;
}

function addAssistantMessage() {
  clearEmptyState();
  const el = buildAssistantBubble();
  messagesEl.appendChild(el);
  messagesEl.scrollTop = messagesEl.scrollHeight;

  return el;
}

function setAssistantStatus(el, text) {
  el.querySelector(".msg-content").innerHTML = `<span class="msg-status">${text}</span>`;
}

function setAssistantContent(el, text) {
  el.querySelector(".msg-content").innerHTML = text ? renderMarkdown(text) : "";
}

function setThinking(el, text) {
  if (!text) return;
  const details = el.querySelector(".thinking");
  details.hidden = false;
  details.querySelector(".thinking-body").textContent = text;
}

function formatDuration(ns) {
  if (!ns) return null;
  const s = ns / 1e9;

  return s >= 10 ? `${s.toFixed(1)}s` : `${s.toFixed(2)}s`;
}

function statsFooterText(stats, elapsedMs) {
  if (!stats && elapsedMs == null) return "";
  const parts = [];
  const dur = (stats && formatDuration(stats.total_duration)) || (elapsedMs != null ? `${(elapsedMs / 1000).toFixed(1)}s` : null);
  if (dur) parts.push(`responded in ${dur}`);
  if (stats && stats.eval_count) parts.push(`${stats.eval_count} tokens`);

  return parts.join(" · ");
}

function setFooter(el, text) {
  const footer = el.querySelector(".msg-footer");
  if (!text) {
    footer.hidden = true;
    return;
  }

  footer.hidden = false;
  footer.textContent = text;
}

function renderPreviews() {
  previewRow.innerHTML = "";
  pendingImages.forEach((image, i) => {
    const wrap = document.createElement("div");
    wrap.className = "image-preview";
    wrap.innerHTML = `<img src="${image.dataUrl}"><button type="button">x</button>`;
    wrap.querySelector("button").addEventListener("click", () => {
      pendingImages.splice(i, 1);
      renderPreviews();
    });

    previewRow.appendChild(wrap);
  });
}

uploadBtn.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => {
  for (const file of fileInput.files) {
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = reader.result;
      const base64 = dataUrl.split(",")[1];
      pendingImages.push({ dataUrl, base64 });
      renderPreviews();
    };
    reader.readAsDataURL(file);
  }

  fileInput.value = "";
});

function renderHistory(historyMessages) {
  messagesEl.innerHTML = "";
  if (historyMessages.length === 0) {
    messagesEl.innerHTML = '<div class="empty-state">Say hello.</div>';
    return;
  }

  for (const m of historyMessages) {
    if (m.role === "assistant") {
      const el = addAssistantMessage();
      setAssistantContent(el, m.content);
      setThinking(el, m.thinking);
      const stats = statsFooterText(m.stats, null);
      const footerText = m.interrupted ? `interrupted${stats ? " · " + stats : ""}` : stats;
      setFooter(el, footerText);
    } else if (m.role === "system") {
      clearEmptyState();
      const el = document.createElement("div");
      el.className = "msg system";
      el.textContent = (m.compacted ? "Compacted summary: " : "") + m.content;
      messagesEl.appendChild(el);
    } else {
      const images = (m.images || []).map(imageDataUrl);
      addMessage(m.role, m.content, images);
    }
  }

  messagesEl.scrollTop = messagesEl.scrollHeight;
}

async function loadDeviceStats(deviceId, epoch) {
  if (statsLoadInFlight) return;
  statsLoadInFlight = true;
  try {
    const stats = await apiGet(`/devices/${encodeURIComponent(deviceId)}/stats`);
    if (epoch === statsEpoch) deviceStatsEl.innerHTML = remoteStatsHtml(stats);
  } catch (e) {
    if (epoch === statsEpoch) deviceStatsEl.innerHTML = `<div class="empty-state">${e.message}</div>`;
  } finally {
    statsLoadInFlight = false;
  }
}

function startStatsPolling(deviceId, epoch) {
  if (statsIntervalId) clearInterval(statsIntervalId);
  deviceStatsEl.innerHTML = '<div class="empty-state">loading...</div>';
  loadDeviceStats(deviceId, epoch);
  statsIntervalId = setInterval(() => loadDeviceStats(deviceId, epoch), 3000);
}

let openConvMenu = null;

function closeAllConvMenus() {
  if (openConvMenu) {
    openConvMenu.remove();
    openConvMenu = null;
  }
}

document.addEventListener("click", closeAllConvMenus);
window.addEventListener("resize", closeAllConvMenus);
conversationListEl.addEventListener("scroll", closeAllConvMenus);

function renderConversationList() {
  conversationListEl.innerHTML = "";
  for (const conv of conversationsCache) {
    const el = document.createElement("div");
    el.className = "conversation-item" + (conv.id === conversationId ? " active" : "");
    el.dataset.id = conv.id;
    el.innerHTML =
      `<span class="conv-title">${conv.title || "New chat"}</span>` +
      '<button class="conv-menu-btn" type="button" title="chat options">&#8942;</button>';

    el.querySelector(".conv-title").addEventListener("click", () => selectConversation(conv.id));
    el.querySelector(".conv-menu-btn").addEventListener("click", (e) => {
      e.stopPropagation();
      toggleConvMenu(e.currentTarget, el, conv);
    });

    conversationListEl.appendChild(el);
  }
}

function toggleConvMenu(btnEl, itemEl, conv) {
  const wasOpenForThis = openConvMenu && openConvMenu.dataset.forId === conv.id;
  closeAllConvMenus();
  if (wasOpenForThis) return;

  const menu = document.createElement("div");
  menu.className = "conv-menu";
  menu.dataset.forId = conv.id;
  menu.innerHTML =
    '<button type="button" data-action="rename">Rename</button>' +
    '<button type="button" data-action="files">Files</button>' +
    '<button type="button" class="danger" data-action="delete">Delete</button>';

  menu.addEventListener("click", (e) => e.stopPropagation());
  menu.querySelector('[data-action="rename"]').addEventListener("click", () => {
    closeAllConvMenus();
    startRename(itemEl, conv);
  });
  menu.querySelector('[data-action="files"]').addEventListener("click", () => {
    closeAllConvMenus();
    openFilesDialog(conv.id);
  });
  menu.querySelector('[data-action="delete"]').addEventListener("click", () => {
    closeAllConvMenus();
    deleteConversation(conv.id);
  });

  document.body.appendChild(menu);
  openConvMenu = menu;

  const rect = btnEl.getBoundingClientRect();
  const menuRect = menu.getBoundingClientRect();
  let left = rect.right - menuRect.width;
  left = Math.max(4, Math.min(left, window.innerWidth - menuRect.width - 4));
  let top = rect.bottom + 4;
  if (top + menuRect.height > window.innerHeight - 4) {
    top = rect.top - menuRect.height - 4;
  }

  menu.style.left = `${left}px`;
  menu.style.top = `${top}px`;
}

function startRename(itemEl, conv) {
  const titleEl = itemEl.querySelector(".conv-title");
  const input = document.createElement("input");
  input.type = "text";
  input.className = "conv-title-input";
  input.value = conv.title || "";
  titleEl.replaceWith(input);
  input.focus();
  input.select();

  let settled = false;
  const finish = async (save) => {
    if (settled) return;
    settled = true;
    const value = input.value.trim();
    if (save && value) {
      try {
        const updated = await apiFetch(`/llm/${encodeURIComponent(deviceSelect.value)}/conversations/${encodeURIComponent(conv.id)}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title: value }),
        }).then((r) => r.json());
        Object.assign(conv, updated);
        if (conv.id === conversationId) conversationTitleEl.textContent = conv.title;
      } catch (e) {
        statusEl.textContent = `rename failed: ${e.message}`;
      }
    }
    renderConversationList();
  };

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") finish(true);
    if (e.key === "Escape") finish(false);
  });
  input.addEventListener("blur", () => finish(true));
}

async function openFilesDialog(id) {
  const deviceId = deviceSelect.value;
  if (!deviceId) return;
  filesDialogOverlay.hidden = false;
  filesDialogBody.innerHTML = '<div class="empty-state">loading...</div>';

  try {
    const data = await apiGet(`/llm/${encodeURIComponent(deviceId)}/conversations/${encodeURIComponent(id)}/files`);
    const files = data.files || [];
    if (files.length === 0) {
      filesDialogBody.innerHTML = `<div class="modal-empty"><pre>${CAT_ASCII}</pre></div>`;
      return;
    }

    filesDialogBody.innerHTML = '<div class="files-grid"></div>';
    const grid = filesDialogBody.querySelector(".files-grid");
    for (const f of files) {
      const item = document.createElement("div");
      item.className = "file-item";
      item.innerHTML = `<img src="${imageDataUrl(f.image)}"><span class="file-role">${f.role}</span>`;
      grid.appendChild(item);
    }
  } catch (e) {
    filesDialogBody.innerHTML = `<div class="empty-state">${e.message}</div>`;
  }
}

function closeFilesDialog() {
  filesDialogOverlay.hidden = true;
}

filesDialogClose.addEventListener("click", closeFilesDialog);
filesDialogOverlay.addEventListener("click", (e) => {
  if (e.target === filesDialogOverlay) closeFilesDialog();
});

async function loadConversations(deviceId) {
  const data = await apiGet(`/llm/${encodeURIComponent(deviceId)}/conversations`);
  conversationsCache = data.conversations || [];
}

async function selectConversation(id) {
  viewEpoch++;
  const epoch = viewEpoch;
  conversationId = id;
  pendingCount = 0;
  updateStopVisibility();
  renderConversationList();

  const conv = conversationsCache.find((c) => c.id === id);
  conversationTitleEl.textContent = conv ? conv.title || "New chat" : "";
  messagesEl.innerHTML = '<div class="empty-state">loading...</div>';

  const data = await apiGet(`${apiBase()}/history`);
  if (epoch !== viewEpoch) return;
  renderHistory(data.messages);

  if (data.generating || data.queued > 0) {
    statusEl.textContent = data.queued > 0 ? `resuming, ${data.queued} more queued...` : "resuming...";
    const assistantEl = addAssistantMessage();
    pendingCount++;
    updateStopVisibility();
    await readStream(`${apiBase()}/chat/tail`, "GET", null, assistantEl, epoch);
    if (epoch === viewEpoch) statusEl.textContent = "";
  }
}

function findEmptyConversation() {
  return conversationsCache.find((c) => !c.title || c.title === "New chat");
}

async function getOrCreateEmptyConversation(deviceId) {
  const existing = findEmptyConversation();
  if (existing) return existing;

  const entry = await apiPost(`/llm/${encodeURIComponent(deviceId)}/conversations`, {});
  conversationsCache.unshift(entry);
  return entry;
}

newChatBtn.addEventListener("click", async () => {
  const deviceId = deviceSelect.value;
  if (!deviceId) return;
  const entry = await getOrCreateEmptyConversation(deviceId);
  await selectConversation(entry.id);
});

async function deleteConversation(id) {
  const deviceId = deviceSelect.value;
  if (!deviceId) return;
  if (!confirm("Delete this chat? This can't be undone.")) return;

  try {
    await apiFetch(`/llm/${encodeURIComponent(deviceId)}/conversations/${encodeURIComponent(id)}`, { method: "DELETE" });
  } catch (e) {
    statusEl.textContent = `could not delete: ${e.message}`;
    return;
  }

  conversationsCache = conversationsCache.filter((c) => c.id !== id);

  const entry = await getOrCreateEmptyConversation(deviceId);
  await selectConversation(entry.id);
}

async function loadDevices() {
  const { devices } = await apiGet("/devices");
  const llmDevices = devices.filter((d) => d.kind === "ssh" && d.ollama_port);
  deviceSelect.innerHTML = llmDevices
    .map((d) => `<option value="${d.id}">${d.name || d.id}</option>`)
    .join("");
  if (llmDevices.length) {
    await onDeviceChange();
  } else {
    statusEl.textContent = "no llm devices registered";
  }
}

async function loadModels() {
  const deviceId = deviceSelect.value;
  if (!deviceId) return;
  try {
    const data = await apiGet(`/llm/${encodeURIComponent(deviceId)}/models`);
    const models = data.models || [];
    modelSelect.innerHTML = models
      .map((m) => `<option value="${m.name || m.model}">${m.name || m.model}</option>`)
      .join("");
    statusEl.textContent = "";
  } catch (e) {
    statusEl.textContent = `could not list models: ${e.message}`;
  }
}

async function onDeviceChange() {
  viewEpoch++;
  statsEpoch++;
  const epoch = viewEpoch;
  const statEpoch = statsEpoch;
  pendingCount = 0;
  updateStopVisibility();
  conversationId = null;

  const deviceId = deviceSelect.value;
  if (!deviceId) {
    if (statsIntervalId) clearInterval(statsIntervalId);
    deviceStatsEl.innerHTML = '<div class="empty-state">select a device</div>';
    return;
  }

  startStatsPolling(deviceId, statEpoch);
  await Promise.all([loadModels(), loadConversations(deviceId)]);
  if (epoch !== viewEpoch) return;
  renderConversationList();

  if (conversationsCache.length) {
    await selectConversation(conversationsCache[0].id);
  }
}

deviceSelect.addEventListener("change", onDeviceChange);

clearBtn.addEventListener("click", async () => {
  if (!deviceSelect.value || !conversationId) return;
  await apiFetch(`${apiBase()}/history`, { method: "DELETE" });
  renderHistory([]);
});

compactBtn.addEventListener("click", async () => {
  const model = modelSelect.value;
  if (!deviceSelect.value || !conversationId || !model) return;
  if (pendingCount > 0) {
    statusEl.textContent = "wait for the current response to finish before compacting";

    return;
  }

  statusEl.textContent = "compacting...";
  try {
    const result = await apiPost(`${apiBase()}/compact`, { model });
    if (result.compacted) {
      const data = await apiGet(`${apiBase()}/history`);
      renderHistory(data.messages);
      statusEl.textContent = "history compacted";
    } else {
      statusEl.textContent = result.reason || "nothing to compact";
    }
  } catch (e) {
    statusEl.textContent = `compact failed: ${e.message}`;
  }
});

stopBtn.addEventListener("click", async () => {
  if (!deviceSelect.value || !conversationId) return;
  try {
    await apiFetch(`${apiBase()}/chat/interrupt`, { method: "POST" });
  } catch (e) {
    // ignore
  }
});

async function readStream(path, method, body, assistantEl, epoch) {
  const headers = { Authorization: `Bearer ${getToken()}` };
  if (body) headers["Content-Type"] = "application/json";

  let resp;
  try {
    resp = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  } catch (e) {
    if (epoch === viewEpoch) setAssistantStatus(assistantEl, `[error: ${e.message}]`);
    pendingCount = Math.max(0, pendingCount - 1);
    updateStopVisibility();

    return;
  }

  if (!resp.ok || !resp.body) {
    if (epoch === viewEpoch) setAssistantStatus(assistantEl, `[error: hub returned ${resp.status}]`);
    pendingCount = Math.max(0, pendingCount - 1);
    updateStopVisibility();

    return;
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let full = "";
  let thinking = "";
  let done = false;

  while (!done) {
    let chunkResult;
    try {
      chunkResult = await reader.read();
    } catch (e) {
      break;
    }
    done = chunkResult.done;
    if (chunkResult.value) buffer += decoder.decode(chunkResult.value, { stream: true });

    let idx;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const chunk = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      if (!chunk.startsWith("data: ")) continue;

      let payload;
      try {
        payload = JSON.parse(chunk.slice(6));
      } catch (e) {
        continue;
      }

      if (epoch !== viewEpoch) continue;

      if (payload.queued) {
        if (full === "") setAssistantStatus(assistantEl, "queued...");
        continue;
      }

      if (payload.error) {
        setAssistantStatus(assistantEl, `[error: ${payload.error}]`);
        done = true;
        break;
      }

      const message = payload.message || {};
      if (message.thinking) {
        thinking += message.thinking;
        setThinking(assistantEl, thinking);
      }
      if (message.content) {
        full += message.content;
        setAssistantContent(assistantEl, full);
        messagesEl.scrollTop = messagesEl.scrollHeight;
      }

      if (payload.done) {
        const elapsedMs = Date.now() - assistantEl._startedAt;
        const footerText = payload.interrupted
          ? `interrupted after ${(elapsedMs / 1000).toFixed(1)}s`
          : statsFooterText(payload, elapsedMs);
        setFooter(assistantEl, footerText);
        done = true;
        break;
      }
    }
  }

  if (epoch === viewEpoch) {
    pendingCount = Math.max(0, pendingCount - 1);
    updateStopVisibility();
  }
}

async function send() {
  const model = modelSelect.value;
  const text = inputEl.value.trim();
  if (!deviceSelect.value || !conversationId || !model || (!text && pendingImages.length === 0)) return;

  const images = pendingImages.map((i) => i.dataUrl);
  addMessage("user", text, images);

  const payload = { model, message: text, stream: true };
  if (pendingImages.length) payload.images = pendingImages.map((i) => i.base64);
  pendingImages = [];
  renderPreviews();
  inputEl.value = "";

  const assistantEl = addAssistantMessage();
  const epoch = viewEpoch;
  pendingCount++;
  updateStopVisibility();

  await readStream(`${apiBase()}/chat`, "POST", payload, assistantEl, epoch);
  if (epoch === viewEpoch && deviceSelect.value) {
    await loadConversations(deviceSelect.value);
    if (epoch === viewEpoch) {
      renderConversationList();
      const conv = conversationsCache.find((c) => c.id === conversationId);
      if (conv) conversationTitleEl.textContent = conv.title || "New chat";
    }
  }
}

sendBtn.addEventListener("click", send);
inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
});

loadDevices();