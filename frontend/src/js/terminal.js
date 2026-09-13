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

  // Forward every keystroke immediately, the way a real terminal does,
  // instead of buffering a line locally and sending it whole on Enter.
  // This is what makes the remote shell's own tab-completion, command
  // history (up/down), and Ctrl+C work: those all depend on the shell
  // seeing each key as it's pressed, not a finished line after the fact.
  // The input box itself stays empty, whatever you're typing shows up
  // from the remote's own echo in the terminal output above it.
  const KEY_SEQUENCES = {
    Enter: "\r\n",
    Backspace: "\x7f",
    Tab: "\t",
    ArrowUp: "\x1b[A",
    ArrowDown: "\x1b[B",
    ArrowRight: "\x1b[C",
    ArrowLeft: "\x1b[D",
    Escape: "\x1b",
  };

  cmdInput.addEventListener("keydown", (e) => {
    let toSend = KEY_SEQUENCES[e.key];

    if (toSend === undefined) {
      if (e.ctrlKey && e.key.length === 1) {
        // Ctrl+<letter> -> its control byte (Ctrl+C -> 0x03, etc.)
        const code = e.key.toUpperCase().charCodeAt(0) - 64;
        if (code >= 0 && code < 32) toSend = String.fromCharCode(code);
      } else if (e.key.length === 1) {
        toSend = e.key;
      }
    }

    if (toSend === undefined) return;
    e.preventDefault();
    cmdInput.value = "";

    if (ws.readyState !== WebSocket.OPEN) {
      appendTerminal(`\n[can't send, connection isn't open (state ${ws.readyState})]\n`);
      return;
    }

    ws.send(toSend);
  });
})();