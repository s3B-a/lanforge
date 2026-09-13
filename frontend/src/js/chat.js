injectNav("chat");

const deviceSelect = document.getElementById("device-select");
const modelSelect = document.getElementById("model-select");
const clearBtn = document.getElementById("clear-btn");
const messagesEl = document.getElementById("messages");
const inputEl = document.getElementById("chat-input");
const sendBtn = document.getElementById("send-btn");
const uploadBtn = document.getElementById("upload-btn");
const fileInput = document.getElementById("file-input");
const previewRow = document.getElementById("image-preview-row");
const statusEl = document.getElementById("chat-status");

let pendingImages = []; // { dataUrl, base64 }
let activeReader = null;

function clearEmptyState() {
  if (messagesEl.children.length === 1 && messagesEl.children[0].classList.contains("empty-state")) {
    messagesEl.innerHTML = "";
  }
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

function imageDataUrl(base64) {
  return `data:image/png;base64,${base64}`;
}

function renderHistory(historyMessages) {
  messagesEl.innerHTML = "";
  if (historyMessages.length === 0) {
    messagesEl.innerHTML = '<div class="empty-state">Pick a device and model, then say hello.</div>';
    return;
  }

  for (const m of historyMessages) {
    const images = (m.images || []).map(imageDataUrl);
    addMessage(m.role, m.content, images);
  }
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
  activeReader = null;
  await loadModels();
  const deviceId = deviceSelect.value;
  if (!deviceId) return;

  const data = await apiGet(`/llm/${encodeURIComponent(deviceId)}/history`);
  renderHistory(data.messages);

  if (data.generating) {
    statusEl.textContent = "still generating, resuming...";
    const assistantEl = addMessage("assistant", "");
    await readStream(`/llm/${encodeURIComponent(deviceId)}/chat/tail`, "GET", null, assistantEl);
    statusEl.textContent = "";
  }
}

deviceSelect.addEventListener("change", onDeviceChange);

clearBtn.addEventListener("click", async () => {
  const deviceId = deviceSelect.value;
  if (!deviceId) return;
  await apiFetch(`/llm/${encodeURIComponent(deviceId)}/history`, { method: "DELETE" });
  renderHistory([]);
});

async function readStream(path, method, body, assistantEl) {
  const myReaderToken = {};
  activeReader = myReaderToken;

  const headers = { Authorization: `Bearer ${getToken()}` };
  if (body) headers["Content-Type"] = "application/json";

  const resp = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  if (!resp.ok || !resp.body) {
    if (activeReader === myReaderToken) assistantEl.textContent = `[error: hub returned ${resp.status}]`;
    return;
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let full = "";
  let done = false;

  while (!done) {
    const chunkResult = await reader.read();
    done = chunkResult.done;
    if (chunkResult.value) buffer += decoder.decode(chunkResult.value, { stream: true });

    let idx;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const chunk = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      if (!chunk.startsWith("data: ")) continue;
      const payload = JSON.parse(chunk.slice(6));
      if (activeReader !== myReaderToken) {
        continue;
      }

      if (payload.error) {
        assistantEl.textContent = `[error: ${payload.error}]`;
        done = true;
        break;
      }

      const content = payload.message && payload.message.content;
      if (content) {
        full += content;
        assistantEl.textContent = full;
        messagesEl.scrollTop = messagesEl.scrollHeight;
      }

      if (payload.done) {
        done = true;
        break;
      }
    }
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
  sendBtn.disabled = true;

  const assistantEl = addMessage("assistant", "");
  try {
    await readStream(`/llm/${encodeURIComponent(deviceId)}/chat`, "POST", payload, assistantEl);
  } catch (e) {
    assistantEl.textContent = `[error: ${e.message}]`;
  } finally {
    sendBtn.disabled = false;
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