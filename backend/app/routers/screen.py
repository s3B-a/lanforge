import asyncio

from app.core import devices_store
from app.core.config import HUB_TOKEN
from app.services import ssh_client

def _ssh_device_or_none(device_id: str):
    device = devices_store.get_device(device_id)
    if device is None or device["kind"] != "ssh":
        return None
    
    return device

_JPEG_SOI = b"\xff\xd8"
_JPEG_EOI = b"\xff\xd9"

async def _read_frames(channel):
    """Yields complete JPEG frames out of a raw MJPEG byte stream, as produced by ffmpeg via
    ssh_client.open_screen_stream. Frame boundaries are found by scanning
    for the standard JPEG start-of-image/end-of-image markers."""
    buffer = bytearray()
    while True:
        if channel.closed:
            return
        if channel.recv_ready():
            buffer += channel.recv(65536)
        else:
            if channel.exit_status_ready():
                return
            await asyncio.sleep(0.01)
            continue

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

def register_websockets(app):
    """Websocket routes are registered directly on the app (SubRouter
    websocket support isn't guaranteed)"""

    @app.websocket("/ws/screen/:device_id")
    async def screen_session(websocket, device_id: str = "", token: str = ""):
        if token != HUB_TOKEN:
            await _safe_close(websocket)
            return ""

        device = _ssh_device_or_none(device_id)
        if device is None:
            await _safe_close(websocket)
            return ""

        client, channel = ssh_client.open_screen_stream(device)
        try:
            async for frame in _read_frames(channel):
                await websocket.send_bytes(frame)
        except Exception:
            pass
        finally:
            channel.close()
            client.close()
        return ""

    return screen_session