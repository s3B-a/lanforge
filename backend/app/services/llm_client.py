from typing import AsyncIterator
import httpx

from app.core.devices_store import target_host

def _base_url(device: dict) -> str:
    return f"http://{target_host(device)}:{device.get('ollama_port', 11434)}"

async def list_models(device: dict) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{_base_url(device)}/api/tags")
        resp.raise_for_status()

        return resp.json()

async def chat(device: dict, model: str, messages: list[dict], think: bool = False) -> dict:
    payload = {"model": model, "messages": messages, "stream": False, "keep_alive": -1}
    if think:
        payload["think"] = True
    
    async with httpx.AsyncClient(timeout=None) as client:
        resp = await client.post(f"{_base_url(device)}/api/chat", json=payload)
        if think and resp.status_code == 400:
            return await chat(device, model, messages, think=False)
        resp.raise_for_status()

        return resp.json()

async def stream_chat(device: dict, model: str, messages: list[dict], think: bool = True) -> AsyncIterator[str]:
    """Yields raw NDJSON lines exactly as Ollama emits them, so the caller
    can pass each token straight through. If the model/server doesn't
    understand the "think" field it responds with a 400 before streaming anything"""
    base_payload = {"model": model, "messages": messages, "stream": True, "keep_alive": -1}
    async with httpx.AsyncClient(timeout=None) as client:
        payload = dict(base_payload, think=True) if think else dict(base_payload)
        retry_without_think = False
        async with client.stream("POST", f"{_base_url(device)}/api/chat", json=payload) as resp:
            if think and resp.status_code == 400:
                retry_without_think = True
            else:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line:
                        yield line

        if retry_without_think:
            async with client.stream("POST", f"{_base_url(device)}/api/chat", json=base_payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line:
                        yield line