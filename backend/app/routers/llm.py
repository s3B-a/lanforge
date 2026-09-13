import json
import httpx
from robyn import Request, Response, SSEResponse, SubRouter, jsonify

from app.core import devices_store
from app.services import llm_client

llm_router = SubRouter(__file__, prefix="/llm")

def _llm_device_or_none(device_id: str):
    device = devices_store.get_device(device_id)
    if device is None or device["kind"] != "ssh" or "ollama_port" not in device:
        return None
    
    return device

@llm_router.get("/:device_id/models", auth_required=True)
async def models(request: Request):
    device = _llm_device_or_none(request.path_params["device_id"])
    if device is None:
        return Response(status_code=404, description="llm device not found", headers={})
    data = await llm_client.list_models(device)

    return jsonify(data)

@llm_router.post("/:device_id/chat", auth_required=True)
async def chat(request: Request):
    device = _llm_device_or_none(request.path_params["device_id"])
    if device is None:
        return Response(status_code=404, description="llm device not found", headers={})

    body = request.json()
    model = body.get("model")
    messages = body.get("messages", [])
    if not model or not messages:
        return Response(status_code=400, description="missing 'model' or 'messages'", headers={})

    if not body.get("stream", True):
        try:
            data = await llm_client.chat(device, model, messages)
        except httpx.HTTPError as exc:
            return Response(status_code=502, description=f"llm unreachable: {exc}", headers={})
        return jsonify(data)

    async def event_generator():
        try:
            async for line in llm_client.stream_chat(device, model, messages):
                yield f"data: {line}\n\n"
        except httpx.HTTPError as exc:
            yield f"data: {json.dumps({'error': str(exc), 'done': True})}\n\n"

    return SSEResponse(event_generator())