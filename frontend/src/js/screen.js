(() => {
  const params = new URLSearchParams(location.search);
  const deviceId = params.get("id");
  const img = document.getElementById("screen-img");
  if (!deviceId) {
    img.alt = "no ?id= given in the URL";
    return;
  }

  let currentUrl = null;
  const ws = new WebSocket(wsUrl(`/devices/${encodeURIComponent(deviceId)}/screen`));
  ws.binaryType = "arraybuffer";

  ws.onmessage = (event) => {
    const blob = new Blob([event.data], { type: "image/jpeg" });
    const url = URL.createObjectURL(blob);
    img.src = url;
    if (currentUrl) URL.revokeObjectURL(currentUrl);
    currentUrl = url;
  };

  ws.onerror = () => {
    img.alt = "screen stream error";
  };
  
  ws.onclose = () => {
    img.alt = "screen stream closed";
  };
})();