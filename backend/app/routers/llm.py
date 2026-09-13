import asyncio
import json
import httpx
from robyn import Request, Response, SSEResponse, SubRouter, jsonify

from app.core import conversations, devices_store
from app.services import llm_client

llm_router = SubRouter(__file__, prefix="/llm")

def _llm_device_or_none(device_id: str):
    device = devices_store.get_device(device_id)
    if device is None or device["kind"] != "ssh" or "ollama_port" not in device:
        return None
    
    return device

class _Generation:
    def __init__(self):
        self.chunks: list[str] = []
        self.full_text = ""
        self.done = False
        self.error: str | None = None

_generations: dict[str, _Generation] = {}

@llm_router.get("/:device_id/models", auth_required=True)
async def models(request: Request):
    device = _llm_device_or_none(request.path_params["device_id"])
    if device is None:
        return Response(status_code=404, description="llm device not found", headers={})
    
    data = await llm_client.list_models(device)

    return jsonify(data)

@llm_router.get("/:device_id/history", auth_required=True)
async def history(request: Request):
    device_id = request.path_params["device_id"]
    if _llm_device_or_none(device_id) is None:
        return Response(status_code=404, description="llm device not found", headers={})

    gen = _generations.get(device_id)
    return jsonify(
        {
            "messages": conversations.load_messages(device_id),
            "generating": gen is not None and not gen.done,
        }
    )

@llm_router.delete("/:device_id/history", auth_required=True)
async def clear_history(request: Request):
    device_id = request.path_params["device_id"]
    if _llm_device_or_none(device_id) is None:
        return Response(status_code=404, description="llm device not found", headers={})
    
    conversations.clear(device_id)
    return jsonify({"cleared": True})

async def _run_generation(device: dict, model: str, device_id: str, gen: "_Generation") -> None:
    try:
        async for line in llm_client.stream_chat(device, model, conversations.load_messages(device_id)):
            gen.chunks.append(line)
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            content = payload.get("message", {}).get("content", "")
            if content:
                gen.full_text += content
    except httpx.HTTPError as exc:
        gen.error = str(exc)
    finally:
        gen.done = True
        if gen.full_text:
            conversations.append_message(device_id, {"role": "assistant", "content": gen.full_text})

async def _tail_generation(gen: "_Generation"):
    sent = 0
    while True:
        while sent < len(gen.chunks):
            yield f"data: {gen.chunks[sent]}\n\n"
            sent += 1
        if gen.done:
            if gen.error:
                yield f"data: {json.dumps({'error': gen.error, 'done': True})}\n\n"
            return
        await asyncio.sleep(0.05)

async def _empty_stream():
    if False:
        yield ""

@llm_router.post("/:device_id/chat", auth_required=True)
async def chat(request: Request):
    device_id = request.path_params["device_id"]
    device = _llm_device_or_none(device_id)
    if device is None:
        return Response(status_code=404, description="llm device not found", headers={})

    body = request.json()
    model = body.get("model")
    text = body.get("message", "")
    images = body.get("images")
    if not model or (not text and not images):
        return Response(status_code=400, description="missing 'model' or 'message'", headers={})

    user_message = {"role": "user", "content": text}
    if images:
        user_message["images"] = images
    
    conversations.append_message(device_id, user_message)

    if not body.get("stream", True):
        try:
            data = await llm_client.chat(device, model, conversations.load_messages(device_id))
        except httpx.HTTPError as exc:
            return Response(status_code=502, description=f"llm unreachable: {exc}", headers={})
        
        reply = data.get("message", {}).get("content", "")
        if reply:
            conversations.append_message(device_id, {"role": "assistant", "content": reply})

        return jsonify(data)

    gen = _Generation()
    _generations[device_id] = gen
    asyncio.create_task(_run_generation(device, model, device_id, gen))

    return SSEResponse(_tail_generation(gen))

@llm_router.get("/:device_id/chat/tail", auth_required=True)
async def tail(request: Request):
    """Reconnects to whatever generation is currently in flight for this
    device, used when a page loads and finds `generating: true` in
    /history. If nothing is running, just returns an immediately-closed
    stream."""
    device_id = request.path_params["device_id"]
    if _llm_device_or_none(device_id) is None:
        return Response(status_code=404, description="llm device not found", headers={})

    gen = _generations.get(device_id)
    if gen is None or gen.done:
        return SSEResponse(_empty_stream())
    
    return SSEResponse(_tail_generation(gen))