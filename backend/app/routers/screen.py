import asyncio

from app.core import devices_store
from app.core.config import HUB_TOKEN
from app.services import ssh_client

def _ssh_device_or_none(device_id: str):
    device = devices_store.get_device(device_id)
    if device is None or device["kind"] != "ssh":
        return None
    
    return device

async def _read_frames(channel):
    """Yields complete JPEG frames from a channel emitting
    [4-byte big-endian length][JPEG bytes], as produced by
    ssh_client.open_screen_stream."""
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

        while len(buffer) >= 4:
            frame_len = int.from_bytes(buffer[:4], "big")
            if len(buffer) < 4 + frame_len:
                break
            yield bytes(buffer[4 : 4 + frame_len])
            del buffer[: 4 + frame_len]

async def _safe_close(websocket):
    try:
        await websocket.close()
    except Exception:
        pass

def register_websockets(app):
    """Websocket routes are registered directly on the app (SubRouter
    websocket support isn't guaranteed)"""

    @app.websocket("/devices/:device_id/screen")
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