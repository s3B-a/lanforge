import asyncio
import json

from robyn import Request, SubRouter, jsonify

from app.core.config import HUB_TOKEN
from app.services import monitor

monitor_router = SubRouter(__file__, prefix="/system")

@monitor_router.get("/stats", auth_required=True)
def stats(request: Request):
    return jsonify(monitor.get_local_stats())

def register_websockets(app):
    @app.websocket("/system/stats/stream")
    async def stats_stream(websocket, token: str = ""):
        if token != HUB_TOKEN:
            try:
                await websocket.close()
            except Exception:
                pass
            return ""

        try:
            while True:
                await websocket.send_text(json.dumps(monitor.get_local_stats()))
                await asyncio.sleep(1)
        except Exception:
            pass
        return ""

    return stats_stream