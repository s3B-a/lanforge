import json

from app.core import devices_store
from app.core.config import HUB_TOKEN
from app.services import screen_client

def _screen_device_or_none(device_id: str):
    device = devices_store.get_device(device_id)
    if device is None or device["kind"] != "ssh" or not device.get("screen_port"):
        return None

    return device

_JPEG_SOI = b"\xff\xd8"
_JPEG_EOI = b"\xff\xd9"

async def _read_frames(reader):
    """Yields complete JPEG frames out of the raw MJPEG byte stream sent by
    scripts/screen_agent.py. Frame boundaries are found by scanning for the
    standard JPEG start-of-image/end-of-image markers."""
    buffer = bytearray()
    while True:
        chunk = await reader.read(65536)
        if not chunk:
            return
        
        buffer += chunk

        while True:
            start = buffer.find(_JPEG_SOI)
            if start == -1:
                if len(buffer) > 2:
                    del buffer[:-1]
                
                break

            end = buffer.find(_JPEG_EOI, start + 2)
            if end == -1:
                if start > 0:
                    del buffer[:start]

                break

            end += len(_JPEG_EOI)
            yield bytes(buffer[start:end])
            del buffer[:end]

async def _safe_close(websocket):
    try:
        await websocket.close()
    except Exception:
        pass

async def _send_error(websocket, message: str):
    try:
        await websocket.send_text(json.dumps({"error": message}))
    except Exception:
        pass

def register_websockets(app):
    """Websocket routes are registered directly on the app (SubRouter
    websocket support isn't guaranteed)"""

    @app.websocket("/ws/screen")
    async def screen_session(websocket, device_id: str = "", token: str = ""):
        if token != HUB_TOKEN:
            await _safe_close(websocket)
            return ""

        device = _screen_device_or_none(device_id)
        if device is None:
            await _send_error(websocket, "this device has no screen_port configured, see README's screen agent setup")
            await _safe_close(websocket)
            return ""

        try:
            reader, writer = await screen_client.open_screen_stream(device, HUB_TOKEN)
        except (OSError, RuntimeError) as exc:
            await _send_error(websocket, str(exc))
            await _safe_close(websocket)
            return ""

        try:
            async for frame in _read_frames(reader):
                await websocket.send_bytes(frame)
        except Exception:
            pass
        finally:
            writer.close()
            await _safe_close(websocket)

        return ""

    return screen_session