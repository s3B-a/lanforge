import asyncio
import json

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
_STDERR_TAIL_LIMIT = 4096

class _StreamEnded(Exception):
    """Raised when the remote ffmpeg process exits before ever producing a single frame"""
    def __init__(self, stderr_tail: str):
        self.stderr_tail = stderr_tail
        super().__init__(stderr_tail)

async def _read_frames(channel):
    """Yields complete JPEG frames out of a raw MJPEG byte stream, as produced by ffmpeg via
    ssh_client.open_screen_stream. Frame boundaries are found by scanning
    for the standard JPEG start-of-image/end-of-image markers."""
    buffer = bytearray()
    stderr_tail = bytearray()
    frames_sent = 0

    while True:
        drained = False
        if channel.recv_ready():
            buffer += channel.recv(65536)
            drained = True
        if channel.recv_stderr_ready():
            stderr_tail += channel.recv_stderr(65536)
            if len(stderr_tail) > _STDERR_TAIL_LIMIT:
                del stderr_tail[: len(stderr_tail) - _STDERR_TAIL_LIMIT]
            drained = True
        
        if not drained:
            if channel.closed or channel.exit_status_ready():
                if frames_sent == 0:
                    raise _StreamEnded(stderr_tail.decode(errors="replace").strip())
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
            frames_sent += 1
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

    @app.websocket("/ws/screen")
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
        except _StreamEnded as exc:
            message = exc.stderr_tail or "ffmpeg exited without producing any frames (is it installed and on PATH on that device?)"
            try:
                await websocket.send_text(json.dumps({"error": message}))
            except Exception:
                pass
        except Exception:
            pass
        finally:
            channel.close()
            client.close()
            await _safe_close(websocket)

        return ""

    return screen_session