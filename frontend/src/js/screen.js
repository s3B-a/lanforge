(() => {
  const params = new URLSearchParams(location.search);
  const deviceId = params.get("id");
  const img = document.getElementById("screen-img");
  if (!deviceId) {
    img.alt = "no ?id= given in the URL";
    return;
  }

  let currentUrl = null;
  let sawError = false;
  const ws = new WebSocket(wsUrl(`/ws/screen?device_id=${encodeURIComponent(deviceId)}`));
  ws.binaryType = "arraybuffer";

  ws.onmessage = (event) => {
    if (typeof event.data === "string") {
      try {
        const payload = JSON.parse(event.data);
        if (payload.error) {
          img.alt = payload.error;
          sawError = true;
        }
      } catch (e) {
        img.alt = "screen stream error";
        sawError = true;
      }
      return;
    }

    const blob = new Blob([event.data], { type: "image/jpeg" });
    const url = URL.createObjectURL(blob);
    img.src = url;
    if (currentUrl) URL.revokeObjectURL(currentUrl);
    currentUrl = url;
  };

  ws.onerror = () => {
    if (!sawError) img.alt = "screen stream error";
  };

  ws.onclose = () => {
    if (!sawError) img.alt = "screen stream closed";
  };

  img.tabIndex = 0;
  img.draggable = false;
  img.addEventListener("dragstart", (e) => e.preventDefault());
  img.addEventListener("contextmenu", (e) => e.preventDefault());

  function send(payload) {
    if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(payload));
  }

  function fractionalPos(e) {
    const rect = img.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return null;
    const x = (e.clientX - rect.left) / rect.width;
    const y = (e.clientY - rect.top) / rect.height;
    if (x < 0 || x > 1 || y < 0 || y > 1) return null;
    return { x, y };
  }

  function buttonName(e) {
    return e.button === 2 ? "right" : e.button === 1 ? "middle" : "left";
  }

  let lastMoveSent = 0;
  img.addEventListener("mousemove", (e) => {
    const pos = fractionalPos(e);
    if (!pos) return;
    const now = performance.now();
    if (now - lastMoveSent < 30) return;
    lastMoveSent = now;
    send({ type: "mouse_move", x: pos.x, y: pos.y });
  });

  img.addEventListener("mousedown", (e) => {
    e.preventDefault();
    img.focus();
    const pos = fractionalPos(e);
    if (!pos) return;
    send({ type: "mouse_down", x: pos.x, y: pos.y, button: buttonName(e) });
  });

  img.addEventListener("mouseup", (e) => {
    e.preventDefault();
    const pos = fractionalPos(e);
    if (!pos) return;
    send({ type: "mouse_up", x: pos.x, y: pos.y, button: buttonName(e) });
  });

  img.addEventListener("wheel", (e) => {
    e.preventDefault();
    send({ type: "scroll", dy: e.deltaY > 0 ? -120 : 120 });
  });

  const SPECIAL_KEYS = new Set([
    "Enter", "Backspace", "Tab", "Escape", "Delete",
    "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight",
    "Home", "End", "PageUp", "PageDown",
    "Control", "Shift", "Alt", "Meta",
    "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12",
  ]);

  img.addEventListener("keydown", (e) => {
    e.preventDefault();
    if (SPECIAL_KEYS.has(e.key)) {
      send({ type: "key_down", key: e.key });
    } else if (e.key.length === 1) {
      send({ type: "text", text: e.key });
    }
  });

  img.addEventListener("keyup", (e) => {
    e.preventDefault();
    if (SPECIAL_KEYS.has(e.key)) {
      send({ type: "key_up", key: e.key });
    }
  });
})();