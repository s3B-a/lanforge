(() => {
  injectNav(null);

  const params = new URLSearchParams(location.search);
  const deviceId = params.get("id");
  document.getElementById("device-title").textContent = deviceId || "No device selected";

  const termEl = document.getElementById("terminal");
  const cmdInput = document.getElementById("terminal-cmd");

  const MAX_LINES = 2000;
  let lines = [""];
  let cursorRow = 0;
  let cursorCol = 0;

  function render() {
    termEl.textContent = lines.join("\n");
    termEl.scrollTop = termEl.scrollHeight;
  }

  function ensureRow(row) {
    while (lines.length <= row) lines.push("");
  }

  function trimScrollback() {
    if (lines.length > MAX_LINES) {
      const excess = lines.length - MAX_LINES;
      lines.splice(0, excess);
      cursorRow = Math.max(0, cursorRow - excess);
    }
  }

  function putChar(ch) {
    ensureRow(cursorRow);
    let line = lines[cursorRow];
    if (line.length < cursorCol) line += " ".repeat(cursorCol - line.length);
    lines[cursorRow] = line.slice(0, cursorCol) + ch + line.slice(cursorCol + 1);
    cursorCol++;
  }

  function lineFeed() {
    cursorRow++;
    ensureRow(cursorRow);
    trimScrollback();
  }

  function eraseInLine(mode) {
    ensureRow(cursorRow);
    const line = lines[cursorRow];
    if (mode === 1) {
      lines[cursorRow] = " ".repeat(Math.min(cursorCol, line.length)) + line.slice(cursorCol);
    } else if (mode === 2) {
      lines[cursorRow] = "";
    } else {
      lines[cursorRow] = line.slice(0, cursorCol);
    }
  }

  function eraseInDisplay(mode) {
    if (mode === 2 || mode === 3) {
      lines = [""];
      cursorRow = 0;
      cursorCol = 0;
    } else if (mode === 1) {
      eraseInLine(1);
      for (let i = 0; i < cursorRow; i++) lines[i] = "";
    } else {
      eraseInLine(0);
      lines.length = cursorRow + 1;
    }
  }

  function applyCsi(params, finalChar) {
    const n = params.length ? params[0] : 1;
    switch (finalChar) {
      case "A":
        cursorRow = Math.max(0, cursorRow - (n || 1));
        break;
      case "B":
        cursorRow += n || 1;
        ensureRow(cursorRow);
        trimScrollback();
        break;
      case "C":
        cursorCol += n || 1;
        break;
      case "D":
        cursorCol = Math.max(0, cursorCol - (n || 1));
        break;
      case "K":
        eraseInLine(params.length ? params[0] : 0);
        break;
      case "J":
        eraseInDisplay(params.length ? params[0] : 0);
        break;
      case "H":
      case "f": {
        const row = params.length > 0 ? params[0] : 1;
        const col = params.length > 1 ? params[1] : 1;
        cursorRow = Math.max(0, row - 1);
        ensureRow(cursorRow);
        cursorCol = Math.max(0, col - 1);
        break;
      }
      default:
        break;
    }
  }

  function processChunk(text) {
    let i = 0;
    while (i < text.length) {
      const ch = text[i];

      if (ch === "\x1b") {
        const next = text[i + 1];
        if (next === "[") {
          let j = i + 2;
          while (j < text.length && !/[a-zA-Z@]/.test(text[j])) j++;
          if (j >= text.length) break;
          const finalChar = text[j];
          const params = text
            .slice(i + 2, j)
            .split(";")
            .filter((s) => s !== "")
            .map(Number);
          applyCsi(params, finalChar);
          i = j + 1;
          continue;
        }
        if (next === "]") {
          let j = i + 2;
          while (j < text.length && text[j] !== "\x07" && !(text[j] === "\x1b" && text[j + 1] === "\\")) j++;
          i = text[j] === "\x1b" ? j + 2 : j + 1;
          continue;
        }
        if (next === "(" || next === ")") {
          i += 3;
          continue;
        }
        i += 2;
        continue;
      }

      if (ch === "\r") {
        cursorCol = 0;
        i++;
        continue;
      }
      if (ch === "\n") {
        lineFeed();
        i++;
        continue;
      }
      if (ch === "\x08") {
        cursorCol = Math.max(0, cursorCol - 1);
        i++;
        continue;
      }
      if (ch.charCodeAt(0) < 0x20 && ch !== "\t") {
        i++;
        continue;
      }

      putChar(ch);
      i++;
    }
  }

  function appendStatus(text) {
    processChunk(text);
    render();
  }

  if (!deviceId) {
    appendStatus("no ?id= given in the URL\n");
    return;
  }

  const ws = new WebSocket(wsUrl(`/ws/shell?device_id=${encodeURIComponent(deviceId)}`));

  ws.onopen = () => appendStatus(`connected to ${deviceId}\n`);
  ws.onmessage = (event) => {
    processChunk(event.data);
    render();
  };
  ws.onclose = () => appendStatus("\n[connection closed]\n");
  ws.onerror = () => appendStatus("\n[connection error]\n");

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
      appendStatus(`\n[can't send, connection isn't open (state ${ws.readyState})]\n`);
      return;
    }

    ws.send(toSend);
  });
})();