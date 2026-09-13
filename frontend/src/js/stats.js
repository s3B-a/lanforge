function statPercentBar(percent) {
  const cls = percent > 85 ? "bad" : percent > 60 ? "warn" : "";
  const clamped = Math.max(0, Math.min(100, percent));

  return `<div class="bar"><div class="bar-fill ${cls}" style="width:${clamped}%"></div></div>`;
}

function remoteStatsHtml(remoteStats) {
  if (!remoteStats) {
    return '<div class="empty-state">no stats available</div>';
  }

  const memPct = remoteStats.memory_total ? (remoteStats.memory_used / remoteStats.memory_total) * 100 : 0;
  const diskPct = remoteStats.disk_total ? (remoteStats.disk_used / remoteStats.disk_total) * 100 : 0;
  const gpuPct = remoteStats.gpu ? remoteStats.gpu.percent : null;

  return `
    <div class="stat-row"><span>CPU</span><b>${(remoteStats.cpu_percent || 0).toFixed(1)}%</b></div>
    ${statPercentBar(remoteStats.cpu_percent || 0)}
    <div class="stat-row"><span>Memory</span><b>${memPct.toFixed(1)}%</b></div>
    ${statPercentBar(memPct)}
    <div class="stat-row"><span>Disk</span><b>${diskPct.toFixed(1)}%</b></div>
    ${statPercentBar(diskPct)}
    <div class="stat-row"><span>GPU</span><b>${gpuPct === null ? "n/a" : gpuPct.toFixed(0) + "%"}</b></div>
    ${gpuPct === null ? "" : statPercentBar(gpuPct)}
  `;
}