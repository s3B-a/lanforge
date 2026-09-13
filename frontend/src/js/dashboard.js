injectNav("dashboard");

const cardElements = new Map();

function statPercentBar(percent) {
  const cls = percent > 85 ? "bad" : percent > 60 ? "warn" : "";
  const clamped = Math.max(0, Math.min(100, percent));

  return `<div class="bar"><div class="bar-fill ${cls}" style="width:${clamped}%"></div></div>`;
}

function renderHub(stats) {
  const gpu = stats.gpu
    ? `${stats.gpu.percent.toFixed(0)}% (${stats.gpu.memory_used_mb.toFixed(0)}MB / ${stats.gpu.memory_total_mb.toFixed(0)}MB)`
    : "n/a";
  document.getElementById("hub-card").innerHTML = `
    <h3>${stats.hostname}</h3>
    <div class="stat-row"><span>CPU</span><b>${stats.cpu.percent.toFixed(1)}%</b></div>
    ${statPercentBar(stats.cpu.percent)}
    <div class="stat-row"><span>Memory</span><b>${stats.memory.percent.toFixed(1)}% (${formatBytes(stats.memory.used)} / ${formatBytes(stats.memory.total)})</b></div>
    ${statPercentBar(stats.memory.percent)}
    <div class="stat-row"><span>Disk</span><b>${stats.disk.percent.toFixed(1)}% (${formatBytes(stats.disk.used)} / ${formatBytes(stats.disk.total)})</b></div>
    ${statPercentBar(stats.disk.percent)}
    <div class="stat-row"><span>Network</span><b>sent ${formatBytes(stats.network.bytes_sent)} / recv ${formatBytes(stats.network.bytes_recv)}</b></div>
    <div class="stat-row"><span>GPU</span><b>${gpu}</b></div>
  `;
}

function deviceCardHtml(device, remoteStats) {
  const badge = device.online
    ? '<span class="badge online">online</span>'
    : '<span class="badge offline">offline</span>';

  let body = `
    <div class="stat-row"><span>kind</span><b>${device.kind}</b></div>
    <div class="stat-row"><span>host</span><b>${device.last_ip || device.host || ""}</b></div>
  `;

  if (remoteStats) {
    const gpu = remoteStats.gpu ? `${remoteStats.gpu.percent.toFixed(0)}%` : "n/a";
    const memPct = remoteStats.memory_total ? (remoteStats.memory_used / remoteStats.memory_total) * 100 : 0;
    const diskPct = remoteStats.disk_total ? (remoteStats.disk_used / remoteStats.disk_total) * 100 : 0;
    body += `
      <div class="stat-row"><span>CPU</span><b>${(remoteStats.cpu_percent || 0).toFixed(1)}%</b></div>
      ${statPercentBar(remoteStats.cpu_percent || 0)}
      <div class="stat-row"><span>Memory</span><b>${memPct.toFixed(1)}%</b></div>
      ${statPercentBar(memPct)}
      <div class="stat-row"><span>Disk</span><b>${diskPct.toFixed(1)}%</b></div>
      ${statPercentBar(diskPct)}
      <div class="stat-row"><span>GPU</span><b>${gpu}</b></div>
    `;
  }

  return `<h3>${device.name || device.id} ${badge}</h3>${body}`;
}

function getOrCreateCard(container, device) {
  let el = cardElements.get(device.id);
  if (el) return el;

  el = document.createElement("div");
  el.className = "card device-card";
  if (device.kind === "ssh") {
    el.addEventListener("click", () => {
      location.href = `/app/device.html?id=${encodeURIComponent(device.id)}`;
    });
  }

  container.appendChild(el);
  cardElements.set(device.id, el);
  return el;
}

async function load() {
  try {
    const stats = await apiGet("/system/stats");
    renderHub(stats);

    const { devices } = await apiGet("/devices");
    const container = document.getElementById("devices");

    if (devices.length === 0) {
      if (cardElements.size > 0) {
        container.innerHTML = "";
        cardElements.clear();
      }

      if (!container.querySelector(".empty-state")) {
        container.innerHTML = '<div class="empty-state">No devices registered yet.</div>';
      }

      return;
    }

    const emptyState = container.querySelector(".empty-state");
    if (emptyState) emptyState.remove();

    const seenIds = new Set();
    for (const device of devices) {
      seenIds.add(device.id);

      let remoteStats = null;
      if (device.kind === "ssh" && device.online) {
        try {
          remoteStats = await apiGet(`/devices/${encodeURIComponent(device.id)}/stats`);
        } catch (e) {
          remoteStats = null;
        }
      }

      const el = getOrCreateCard(container, device);
      el.innerHTML = deviceCardHtml(device, remoteStats);
    }

    for (const [id, el] of cardElements) {
      if (!seenIds.has(id)) {
        el.remove();
        cardElements.delete(id);
      }
    }
  } catch (e) {
    const err = document.getElementById("error");
    err.textContent = e.message;
    err.hidden = false;
  }
}

load();
setInterval(load, 15000);
