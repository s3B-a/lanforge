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
})();
