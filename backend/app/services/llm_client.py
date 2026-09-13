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

async def chat(device: dict, model: str, messages: list[dict]) -> dict:
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{_base_url(device)}/api/chat",
            json={"model": model, "messages": messages, "stream": False, "keep_alive": -1},
        )
        resp.raise_for_status()

        return resp.json()

async def stream_chat(device: dict, model: str, messages: list[dict]) -> AsyncIterator[str]:
    """Yields raw NDJSON lines exactly as Ollama emits them, so the caller
    (websocket handler) can pass each token straight through to the browser"""
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream(
            "POST",
            f"{_base_url(device)}/api/chat",
            json={"model": model, "messages": messages, "stream": True, "keep_alive": -1},
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line:
                    yield line