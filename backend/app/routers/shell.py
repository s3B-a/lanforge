from robyn import Request, Response, SubRouter, jsonify

from app.core import devices_store
from app.core.config import HUB_TOKEN
from app.services import ssh_client

shell_router = SubRouter(__file__, prefix="/shell")

def _ssh_device_or_none(device_id: str):
    device = devices_store.get_device(device_id)
    if device is None or device["kind"] != "ssh":
        return None
    
    return device

@shell_router.post("/:device_id/exec", auth_required=True)
def exec_command(request: Request):
    device = _ssh_device_or_none(request.path_params["device_id"])
    if device is None:
        return Response(status_code=404, description="ssh device not found", headers={})

    command = request.json().get("command", "").strip()
    if not command:
        return Response(status_code=400, description="missing 'command'", headers={})

    result = ssh_client.run_command(device, command)

    return jsonify(result)

def register_websockets(app):
    """Websocket routes are registered directly on the app (SubRouter
    websocket support isn't guaranteed), so main.py calls this after including shell_router"""

    @app.websocket("/ws/shell/:device_id")
    async def shell_session(websocket, device_id: str = "", token: str = ""):
        if token != HUB_TOKEN:
            await _safe_close(websocket)
            return ""

        device = _ssh_device_or_none(device_id)
        if device is None:
            await _safe_close(websocket)
            return ""

        client, channel = ssh_client.open_interactive_shell(device)
        try:
            while True:
                data = await websocket.receive_text()
                if data is None:
                    break
                channel.send(data)
                while channel.recv_ready():
                    output = channel.recv(4096).decode(errors="replace")
                    await websocket.send_text(output)
        except Exception:
            pass
        finally:
            client.close()
        return ""

    return shell_session

async def _safe_close(websocket):
    try:
        await websocket.close()
    except Exception:
        pass