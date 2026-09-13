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

  function stripAnsi(text) {
    return text
      .replace(/\x1b\][^\x07\x1b]*(\x07|\x1b\\)/g, "")
      .replace(/\x1b\[[0-9;?]*[a-zA-Z]/g, "")
      .replace(/\x1b[()][0-9A-Za-z]/g, "")
      .replace(/\r\n/g, "\n")
      .replace(/[\r\x00-\x08\x0b\x0c\x0e-\x1f]/g, "");
  }

  if (!deviceId) {
    appendTerminal("no ?id= given in the URL\n");
    return;
  }

  const ws = new WebSocket(wsUrl(`/ws/shell?device_id=${encodeURIComponent(deviceId)}`));

  ws.onopen = () => appendTerminal(`connected to ${deviceId}\n`);
  ws.onmessage = (event) => appendTerminal(stripAnsi(event.data));
  ws.onclose = () => appendTerminal("\n[connection closed]\n");
  ws.onerror = () => appendTerminal("\n[connection error]\n");

  cmdInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && cmdInput.value.trim() && ws.readyState === WebSocket.OPEN) {
      ws.send(cmdInput.value + "\n");
      cmdInput.value = "";
    }
  });
})();