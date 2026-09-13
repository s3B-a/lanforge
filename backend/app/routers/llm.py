import asyncio
import json
from collections import deque

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
        self.full_thinking = ""
        self.stats: dict | None = None
        self.done = False
        self.error: str | None = None
        self.cancelled = False

class _Job:
    def __init__(self, model: str, user_message: dict, gen: _Generation):
        self.model = model
        self.user_message = user_message
        self.gen = gen

_generations: dict[str, _Generation] = {}
_queues: dict[str, deque[_Job]] = {}
_workers: dict[str, asyncio.Task] = {}

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
    queue = _queues.get(device_id)
    return jsonify(
        {
            "messages": conversations.load_messages(device_id),
            "generating": gen is not None and not gen.done,
            "queued": len(queue) if queue else 0,
        }
    )

@llm_router.delete("/:device_id/history", auth_required=True)
async def clear_history(request: Request):
    device_id = request.path_params["device_id"]
    if _llm_device_or_none(device_id) is None:
        return Response(status_code=404, description="llm device not found", headers={})
    
    conversations.clear(device_id)
    return jsonify({"cleared": True})

_EMPTY_RESPONSE_TEXT = "(no response was generated for this turn)"
_INTERRUPTED_EMPTY_TEXT = "(interrupted before any response was generated)"

def _for_api(messages: list[dict]) -> list[dict]:
    """Strips our own bookkeeping fields (thinking/stats/interrupted/...)
    before handing history back to Ollama, only role/content/images are
    part of its request schema."""
    cleaned = []
    for m in messages:
        content = m.get("content") or ""
        if m.get("role") == "assistant" and not content and not m.get("images"):
            content = _INTERRUPTED_EMPTY_TEXT if m.get("interrupted") else _EMPTY_RESPONSE_TEXT
        item = {"role": m["role"], "content": content}
        if m.get("images"):
            item["images"] = m["images"]
        cleaned.append(item)

    return cleaned

async def _run_generation(device: dict, model: str, device_id: str, user_message: dict, gen: "_Generation") -> None:
    conversations.append_message(device_id, user_message)
    try:
        async for line in llm_client.stream_chat(device, model, _for_api(conversations.load_messages(device_id))):
            if gen.cancelled:
                break

            gen.chunks.append(line)
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue

            message = payload.get("message", {})
            content = message.get("content", "")
            if content:
                gen.full_text += content
            
            thinking = message.get("thinking", "")
            if thinking:
                gen.full_thinking += thinking
            
            if payload.get("done"):
                gen.stats = {
                    "total_duration": payload.get("total_duration"),
                    "load_duration": payload.get("load_duration"),
                    "prompt_eval_count": payload.get("prompt_eval_count"),
                    "eval_count": payload.get("eval_count"),
                    "eval_duration": payload.get("eval_duration"),
                }
    except Exception as exc:
        gen.error = str(exc) or repr(exc)
    finally:
        if gen.cancelled:
            gen.chunks.append(json.dumps({"done": True, "interrupted": True}))

        gen.done = True
        if gen.full_text or gen.cancelled:
            content = gen.full_text or _INTERRUPTED_EMPTY_TEXT
            assistant_message = {"role": "assistant", "content": content}
            if gen.full_thinking:
                assistant_message["thinking"] = gen.full_thinking
            if gen.stats:
                assistant_message["stats"] = gen.stats
            if gen.cancelled:
                assistant_message["interrupted"] = True
            conversations.append_message(device_id, assistant_message)

async def _device_worker(device: dict, device_id: str) -> None:
    queue = _queues.setdefault(device_id, deque())
    try:
        while queue:
            job = queue.popleft()
            _generations[device_id] = job.gen
            await _run_generation(device, job.model, device_id, job.user_message, job.gen)
    finally:
        _workers.pop(device_id, None)

def _enqueue(device: dict, device_id: str, model: str, user_message: dict) -> "_Generation":
    gen = _Generation()
    queue = _queues.setdefault(device_id, deque())
    queue.append(_Job(model, user_message, gen))

    existing = _workers.get(device_id)
    if existing is None or existing.done():
        _workers[device_id] = asyncio.create_task(_device_worker(device, device_id))

    return gen

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

        if sent == 0:
            yield f"data: {json.dumps({'queued': True})}\n\n"

        await asyncio.sleep(0.2 if sent == 0 else 0.05)

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

    if not body.get("stream", True):
        conversations.append_message(device_id, user_message)
        try:
            data = await llm_client.chat(device, model, _for_api(conversations.load_messages(device_id)))
        except httpx.HTTPError as exc:
            return Response(status_code=502, description=f"llm unreachable: {exc}", headers={})

        reply = data.get("message", {}).get("content", "")
        if reply:
            conversations.append_message(device_id, {"role": "assistant", "content": reply})

        return jsonify(data)

    gen = _enqueue(device, device_id, model, user_message)

    return SSEResponse(_tail_generation(gen))

@llm_router.post("/:device_id/chat/interrupt", auth_required=True)
async def interrupt(request: Request):
    """Stops whatever generation is currently running for this device"""
    device_id = request.path_params["device_id"]
    if _llm_device_or_none(device_id) is None:
        return Response(status_code=404, description="llm device not found", headers={})

    gen = _generations.get(device_id)
    if gen is None or gen.done:
        return jsonify({"interrupted": False})

    gen.cancelled = True
    return jsonify({"interrupted": True})

@llm_router.post("/:device_id/compact", auth_required=True)
async def compact(request: Request):
    """Asks the model to summarize the conversation so far, then replaces
    the stored history with just that summary, shrinking how much context
    gets sent on every future turn"""
    device_id = request.path_params["device_id"]
    device = _llm_device_or_none(device_id)
    if device is None:
        return Response(status_code=404, description="llm device not found", headers={})

    gen = _generations.get(device_id)
    if gen is not None and not gen.done:
        return Response(status_code=409, description="a generation is currently in progress", headers={})

    body = request.json()
    model = body.get("model")
    if not model:
        return Response(status_code=400, description="missing 'model'", headers={})

    messages = conversations.load_messages(device_id)
    if len(messages) < 2:
        return jsonify({"compacted": False, "reason": "not enough history to compact"})

    summary_request = [
        {
            "role": "system",
            "content": (
                "Summarize the conversation so far into a compact context summary "
                "that preserves the important facts, decisions, and open threads, "
                "so it can be used as memory to continue the conversation later. "
                "Reply with only the summary, no commentary."
            ),
        },
        *_for_api(messages),
        {"role": "user", "content": "Summarize our conversation above."},
    ]

    try:
        data = await llm_client.chat(device, model, summary_request)
    except httpx.HTTPError as exc:
        return Response(status_code=502, description=f"llm unreachable: {exc}", headers={})

    summary_text = data.get("message", {}).get("content", "").strip()
    if not summary_text:
        return Response(status_code=502, description="model returned an empty summary", headers={})

    conversations.replace_messages(
        device_id,
        [{"role": "system", "content": summary_text, "compacted": True}],
    )

    return jsonify({"compacted": True, "summary": summary_text})

@llm_router.get("/:device_id/chat/tail", auth_required=True)
async def tail(request: Request):
    """Reconnects to whatever generation is currently in flight (running or
    still queued) for this device, used when a page loads and finds
    `generating: true` in /history"""
    device_id = request.path_params["device_id"]
    if _llm_device_or_none(device_id) is None:
        return Response(status_code=404, description="llm device not found", headers={})

    gen = _generations.get(device_id)
    if gen is None or gen.done:
        return SSEResponse(_empty_stream())
    
    return SSEResponse(_tail_generation(gen))