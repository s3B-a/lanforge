injectNav("chat");

const deviceSelect = document.getElementById("device-select");
const modelSelect = document.getElementById("model-select");
const messagesEl = document.getElementById("messages");
const inputEl = document.getElementById("chat-input");
const sendBtn = document.getElementById("send-btn");
const uploadBtn = document.getElementById("upload-btn");
const fileInput = document.getElementById("file-input");
const previewRow = document.getElementById("image-preview-row");
const statusEl = document.getElementById("chat-status");

let history = [];
let pendingImages = []; // { dataUrl, base64 }

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

async function loadDevices() {
  const { devices } = await apiGet("/devices");
  const llmDevices = devices.filter((d) => d.kind === "ssh" && d.ollama_port);
  deviceSelect.innerHTML = llmDevices
    .map((d) => `<option value="${d.id}">${d.name || d.id}</option>`)
    .join("");
  if (llmDevices.length) {
    await loadModels();
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

deviceSelect.addEventListener("change", loadModels);

async function send() {
  const deviceId = deviceSelect.value;
  const model = modelSelect.value;
  const text = inputEl.value.trim();
  if (!deviceId || !model || (!text && pendingImages.length === 0)) return;

  const images = pendingImages.map((i) => i.dataUrl);
  addMessage("user", text, images);

  const message = { role: "user", content: text };
  if (pendingImages.length) message.images = pendingImages.map((i) => i.base64);
  history.push(message);
  pendingImages = [];
  renderPreviews();
  inputEl.value = "";
  sendBtn.disabled = true;

  const assistantEl = addMessage("assistant", "");
  let full = "";

  try {
    const resp = await fetch(`/llm/${encodeURIComponent(deviceId)}/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${getToken()}`,
      },
      body: JSON.stringify({ model, messages: history, stream: true }),
    });

    if (!resp.ok || !resp.body) {
      throw new Error(`hub returned ${resp.status}`);
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let done = false;

    while (!done) {
      const chunkResult = await reader.read();
      done = chunkResult.done;
      if (chunkResult.value) {
        buffer += decoder.decode(chunkResult.value, { stream: true });
      }

      let idx;
      while ((idx = buffer.indexOf("\n\n")) !== -1) {
        const chunk = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        if (!chunk.startsWith("data: ")) continue;
        const payload = JSON.parse(chunk.slice(6));
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

    if (full) history.push({ role: "assistant", content: full });
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