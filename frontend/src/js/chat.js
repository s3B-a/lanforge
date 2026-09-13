injectNav("chat");

const deviceSelect = document.getElementById("device-select");
const modelSelect = document.getElementById("model-select");
const clearBtn = document.getElementById("clear-btn");
const compactBtn = document.getElementById("compact-btn");
const stopBtn = document.getElementById("stop-btn");
const messagesEl = document.getElementById("messages");
const inputEl = document.getElementById("chat-input");
const sendBtn = document.getElementById("send-btn");
const uploadBtn = document.getElementById("upload-btn");
const fileInput = document.getElementById("file-input");
const previewRow = document.getElementById("image-preview-row");
const statusEl = document.getElementById("chat-status");

let pendingImages = []; // { dataUrl, base64 }
let deviceEpoch = 0; // bumped on device switch, so old streams stop touching the DOM
let pendingCount = 0; // in-flight (queued or streaming) generations for the current device

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
    messagesEl.innerHTML = '<div class="empty-state">Pick a device and model, then say hello.</div>';
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
  deviceEpoch++;
  const epoch = deviceEpoch;
  pendingCount = 0;
  updateStopVisibility();

  await loadModels();
  const deviceId = deviceSelect.value;
  if (!deviceId || epoch !== deviceEpoch) return;

  const data = await apiGet(`/llm/${encodeURIComponent(deviceId)}/history`);
  if (epoch !== deviceEpoch) return;
  renderHistory(data.messages);

  if (data.generating || data.queued > 0) {
    statusEl.textContent = data.queued > 0 ? `resuming, ${data.queued} more queued...` : "resuming...";
    const assistantEl = addAssistantMessage();
    pendingCount++;
    updateStopVisibility();
    await readStream(`/llm/${encodeURIComponent(deviceId)}/chat/tail`, "GET", null, assistantEl, epoch);
    if (epoch === deviceEpoch) statusEl.textContent = "";
  }
}

deviceSelect.addEventListener("change", onDeviceChange);

clearBtn.addEventListener("click", async () => {
  const deviceId = deviceSelect.value;
  if (!deviceId) return;
  await apiFetch(`/llm/${encodeURIComponent(deviceId)}/history`, { method: "DELETE" });
  renderHistory([]);
});

compactBtn.addEventListener("click", async () => {
  const deviceId = deviceSelect.value;
  const model = modelSelect.value;
  if (!deviceId || !model) return;
  if (pendingCount > 0) {
    statusEl.textContent = "wait for the current response to finish before compacting";

    return;
  }

  statusEl.textContent = "compacting...";
  try {
    const result = await apiPost(`/llm/${encodeURIComponent(deviceId)}/compact`, { model });
    if (result.compacted) {
      const data = await apiGet(`/llm/${encodeURIComponent(deviceId)}/history`);
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
  const deviceId = deviceSelect.value;
  if (!deviceId) return;
  try {
    await apiFetch(`/llm/${encodeURIComponent(deviceId)}/chat/interrupt`, { method: "POST" });
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
    if (epoch === deviceEpoch) setAssistantStatus(assistantEl, `[error: ${e.message}]`);
    pendingCount = Math.max(0, pendingCount - 1);
    updateStopVisibility();

    return;
  }

  if (!resp.ok || !resp.body) {
    if (epoch === deviceEpoch) setAssistantStatus(assistantEl, `[error: hub returned ${resp.status}]`);
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

      if (epoch !== deviceEpoch) continue;

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

  if (epoch === deviceEpoch) {
    pendingCount = Math.max(0, pendingCount - 1);
    updateStopVisibility();
  }
}

async function send() {
  const deviceId = deviceSelect.value;
  const model = modelSelect.value;
  const text = inputEl.value.trim();
  if (!deviceId || !model || (!text && pendingImages.length === 0)) return;

  const images = pendingImages.map((i) => i.dataUrl);
  addMessage("user", text, images);

  const payload = { model, message: text, stream: true };
  if (pendingImages.length) payload.images = pendingImages.map((i) => i.base64);
  pendingImages = [];
  renderPreviews();
  inputEl.value = "";

  const assistantEl = addAssistantMessage();
  const epoch = deviceEpoch;
  pendingCount++;
  updateStopVisibility();

  await readStream(`/llm/${encodeURIComponent(deviceId)}/chat`, "POST", payload, assistantEl, epoch);
}

sendBtn.addEventListener("click", send);
inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
});

loadDevices();