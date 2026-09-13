(() => {
  injectNav(null);

  const params = new URLSearchParams(location.search);
  const deviceId = params.get("id");
  document.getElementById("device-title").textContent = deviceId || "No device selected";

  const termEl = document.getElementById("terminal");
  const cmdInput = document.getElementById("terminal-cmd");

  function appendTerminal(text) {
    termEl.textContent += text;
    termEl.scrollTop = termEl.scrollHeight;
  }

  if (!deviceId) {
    appendTerminal("no ?id= given in the URL\n");
    return;
  }

  const ws = new WebSocket(wsUrl(`/ws/shell?device_id=${encodeURIComponent(deviceId)}`));

  ws.onopen = () => appendTerminal(`connected to ${deviceId}\n`);
  ws.onmessage = (event) => appendTerminal(event.data);
  ws.onclose = () => appendTerminal("\n[connection closed]\n");
  ws.onerror = () => appendTerminal("\n[connection error]\n");

  cmdInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && cmdInput.value.trim() && ws.readyState === WebSocket.OPEN) {
      const cmd = cmdInput.value;
      appendTerminal(`> ${cmd}\n`);
      ws.send(cmd + "\n");
      cmdInput.value = "";
    }
  });
})();