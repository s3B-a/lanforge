const TOKEN_KEY = "hub_token";

function getToken() {
  let token = localStorage.getItem(TOKEN_KEY);
  if (!token) {
    token = prompt("Enter your hub token (HUB_TOKEN from cfg/.env):");
    if (token) localStorage.setItem(TOKEN_KEY, token.trim());
  }
  
  return token || "";
}

function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

async function apiFetch(path, options = {}) {
  const token = getToken();
  const headers = Object.assign({}, options.headers, {
    Authorization: `Bearer ${token}`,
  });

  const resp = await fetch(path, Object.assign({}, options, { headers }));
  if (resp.status === 401) {
    clearToken();
    throw new Error("Unauthorized. Token cleared, reload the page to re-enter it.");
  }

  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`${resp.status}: ${text}`);
  }

  return resp;
}

async function apiGet(path) {
  const resp = await apiFetch(path, { method: "GET" });

  return resp.json();
}

async function apiPost(path, body) {
  const resp = await apiFetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  return resp.json();
}

function wsUrl(path) {
  const token = getToken();
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const sep = path.includes("?") ? "&" : "?";

  return `${scheme}://${location.host}${path}${sep}token=${encodeURIComponent(token)}`;
}

function formatBytes(n) {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = n || 0;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i++;
  }

  return `${value.toFixed(1)}${units[i]}`;
}

function injectNav(active) {
  const nav = document.createElement("nav");
  nav.className = "topnav";
  nav.innerHTML = `
    <div class="topnav-brand">Local Hub</div>
    <a href="/app/dashboard.html"${active === "dashboard" ? ' class="active"' : ""}>Dashboard</a>
    <a href="/app/chat.html"${active === "chat" ? ' class="active"' : ""}>Chat</a>
  `;
  document.body.prepend(nav);
}