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

def _key(device_id: str, conversation_id: str) -> str:
    return f"{device_id}::{conversation_id}"

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

@llm_router.get("/:device_id/conversations", auth_required=True)
async def list_conversations(request: Request):
    device_id = request.path_params["device_id"]
    if _llm_device_or_none(device_id) is None:
        return Response(status_code=404, description="llm device not found", headers={})

    return jsonify({"conversations": conversations.list_conversations(device_id)})

@llm_router.post("/:device_id/conversations", auth_required=True)
async def create_conversation(request: Request):
    device_id = request.path_params["device_id"]
    if _llm_device_or_none(device_id) is None:
        return Response(status_code=404, description="llm device not found", headers={})

    body = request.json() or {}
    entry = conversations.create_conversation(device_id, body.get("title"))

    return jsonify(entry)

@llm_router.delete("/:device_id/conversations/:conversation_id", auth_required=True)
async def delete_conversation(request: Request):
    device_id = request.path_params["device_id"]
    conversation_id = request.path_params["conversation_id"]
    if _llm_device_or_none(device_id) is None:
        return Response(status_code=404, description="llm device not found", headers={})

    key = _key(device_id, conversation_id)
    gen = _generations.get(key)
    if gen is not None and not gen.done:
        return Response(status_code=409, description="a generation is currently in progress in this chat", headers={})

    conversations.delete_conversation(device_id, conversation_id)
    _generations.pop(key, None)
    _queues.pop(key, None)

    return jsonify({"deleted": True})

@llm_router.patch("/:device_id/conversations/:conversation_id", auth_required=True)
async def rename_conversation(request: Request):
    device_id = request.path_params["device_id"]
    conversation_id = request.path_params["conversation_id"]
    if _llm_device_or_none(device_id) is None:
        return Response(status_code=404, description="llm device not found", headers={})
    if not conversations.conversation_exists(device_id, conversation_id):
        return Response(status_code=404, description="conversation not found", headers={})

    body = request.json() or {}
    title = (body.get("title") or "").strip()[:80]
    if not title:
        return Response(status_code=400, description="title can't be blank", headers={})

    entry = conversations.set_title(device_id, conversation_id, title)

    return jsonify(entry)

@llm_router.get("/:device_id/conversations/:conversation_id/files", auth_required=True)
async def files(request: Request):
    device_id = request.path_params["device_id"]
    conversation_id = request.path_params["conversation_id"]
    if _llm_device_or_none(device_id) is None:
        return Response(status_code=404, description="llm device not found", headers={})
    if not conversations.conversation_exists(device_id, conversation_id):
        return Response(status_code=404, description="conversation not found", headers={})

    items = []
    for i, message in enumerate(conversations.load_messages(device_id, conversation_id)):
        for image in message.get("images") or []:
            items.append({"message_index": i, "role": message.get("role"), "image": image})

    return jsonify({"files": items})

@llm_router.get("/:device_id/conversations/:conversation_id/history", auth_required=True)
async def history(request: Request):
    device_id = request.path_params["device_id"]
    conversation_id = request.path_params["conversation_id"]
    if _llm_device_or_none(device_id) is None:
        return Response(status_code=404, description="llm device not found", headers={})

    if not conversations.conversation_exists(device_id, conversation_id):
        return Response(status_code=404, description="conversation not found", headers={})

    key = _key(device_id, conversation_id)
    gen = _generations.get(key)
    queue = _queues.get(key)
    return jsonify(
        {
            "messages": conversations.load_messages(device_id, conversation_id),
            "generating": gen is not None and not gen.done,
            "queued": len(queue) if queue else 0,
        }
    )

@llm_router.delete("/:device_id/conversations/:conversation_id/history", auth_required=True)
async def clear_history(request: Request):
    device_id = request.path_params["device_id"]
    conversation_id = request.path_params["conversation_id"]
    if _llm_device_or_none(device_id) is None:
        return Response(status_code=404, description="llm device not found", headers={})
    
    if not conversations.conversation_exists(device_id, conversation_id):
        return Response(status_code=404, description="conversation not found", headers={})
    
    conversations.clear(device_id, conversation_id)
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

_AUTO_TITLE_PLACEHOLDERS = (None, "", "New chat", "Previous chat")

async def _maybe_autotitle(device: dict, device_id: str, conversation_id: str, model: str) -> None:
    """After a chat's first exchange completes, asks the model for a short
    topic title and renames the chat to it"""
    try:
        entry = conversations.get_conversation(device_id, conversation_id)
        if entry is None or entry.get("title") not in _AUTO_TITLE_PLACEHOLDERS:
            return

        messages = conversations.load_messages(device_id, conversation_id)
        if len(messages) < 2:
            return

        title_request = [
            {
                "role": "system",
                "content": (
                    "Reply with only a short 3 to 6 word title summarizing the topic "
                    "of the conversation below. No punctuation at the end, no quotes, "
                    "no commentary, just the title text."
                ),
            },
            *_for_api(messages),
        ]
        data = await llm_client.chat(device, model, title_request)
        title = data.get("message", {}).get("content", "").strip().strip('"').strip()
        title = title.splitlines()[0][:60].strip() if title else ""
        if title:
            conversations.set_title(device_id, conversation_id, title)
    except Exception:
        pass

async def _run_generation(device: dict, model: str, device_id: str, conversation_id: str, user_message: dict, gen: "_Generation") -> None:
    conversations.append_message(device_id, conversation_id, user_message)
    try:
        messages = _for_api(conversations.load_messages(device_id, conversation_id))
        async for line in llm_client.stream_chat(device, model, messages):
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
            conversations.append_message(device_id, conversation_id, assistant_message)

            if not gen.cancelled and not gen.error:
                asyncio.create_task(_maybe_autotitle(device, device_id, conversation_id, model))

async def _chat_worker(device: dict, device_id: str, conversation_id: str, key: str) -> None:
    queue = _queues.setdefault(key, deque())
    try:
        while queue:
            job = queue.popleft()
            _generations[key] = job.gen
            await _run_generation(device, job.model, device_id, conversation_id, job.user_message, job.gen)
    finally:
        _workers.pop(key, None)

def _enqueue(device: dict, device_id: str, conversation_id: str, model: str, user_message: dict) -> "_Generation":
    key = _key(device_id, conversation_id)
    gen = _Generation()
    queue = _queues.setdefault(key, deque())
    queue.append(_Job(model, user_message, gen))

    existing = _workers.get(key)
    if existing is None or existing.done():
        _workers[key] = asyncio.create_task(_chat_worker(device, device_id, conversation_id, key))

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

@llm_router.post("/:device_id/conversations/:conversation_id/chat", auth_required=True)
async def chat(request: Request):
    device_id = request.path_params["device_id"]
    conversation_id = request.path_params["conversation_id"]
    device = _llm_device_or_none(device_id)
    if device is None:
        return Response(status_code=404, description="llm device not found", headers={})
    if not conversations.conversation_exists(device_id, conversation_id):
        return Response(status_code=404, description="conversation not found", headers={})

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
        conversations.append_message(device_id, conversation_id, user_message)
        try:
            messages = _for_api(conversations.load_messages(device_id, conversation_id))
            data = await llm_client.chat(device, model, messages)
        except httpx.HTTPError as exc:
            return Response(status_code=502, description=f"llm unreachable: {exc}", headers={})

        reply = data.get("message", {}).get("content", "")
        if reply:
            conversations.append_message(device_id, conversation_id, {"role": "assistant", "content": reply})

        return jsonify(data)

    gen = _enqueue(device, device_id, conversation_id, model, user_message)

    return SSEResponse(_tail_generation(gen))

@llm_router.post("/:device_id/conversations/:conversation_id/chat/interrupt", auth_required=True)
async def interrupt(request: Request):
    """Stops whatever generation is currently running in this chat"""
    device_id = request.path_params["device_id"]
    conversation_id = request.path_params["conversation_id"]
    if _llm_device_or_none(device_id) is None:
        return Response(status_code=404, description="llm device not found", headers={})

    gen = _generations.get(_key(device_id, conversation_id))
    if gen is None or gen.done:
        return jsonify({"interrupted": False})

    gen.cancelled = True
    return jsonify({"interrupted": True})

@llm_router.post("/:device_id/conversations/:conversation_id/compact", auth_required=True)
async def compact(request: Request):
    """Asks the model to summarize this chat so far, then replaces the
    stored history with just that summary, shrinking how much context gets
    sent (and re-processed) on every future turn"""
    device_id = request.path_params["device_id"]
    conversation_id = request.path_params["conversation_id"]
    device = _llm_device_or_none(device_id)
    if device is None:
        return Response(status_code=404, description="llm device not found", headers={})
    if not conversations.conversation_exists(device_id, conversation_id):
        return Response(status_code=404, description="conversation not found", headers={})

    gen = _generations.get(_key(device_id, conversation_id))
    if gen is not None and not gen.done:
        return Response(status_code=409, description="a generation is currently in progress", headers={})

    body = request.json()
    model = body.get("model")
    if not model:
        return Response(status_code=400, description="missing 'model'", headers={})

    messages = conversations.load_messages(device_id, conversation_id)
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
        conversation_id,
        [{"role": "system", "content": summary_text, "compacted": True}],
    )

    return jsonify({"compacted": True, "summary": summary_text})

@llm_router.get("/:device_id/conversations/:conversation_id/chat/tail", auth_required=True)
async def tail(request: Request):
    """Reconnects to whatever generation is currently in flight (running or
    still queued) for this chat"""
    device_id = request.path_params["device_id"]
    conversation_id = request.path_params["conversation_id"]
    if _llm_device_or_none(device_id) is None:
        return Response(status_code=404, description="llm device not found", headers={})

    gen = _generations.get(_key(device_id, conversation_id))
    if gen is None or gen.done:
        return SSEResponse(_empty_stream())

    return SSEResponse(_tail_generation(gen))