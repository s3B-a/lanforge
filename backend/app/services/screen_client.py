import asyncio

from app.core.devices_store import target_host

async def open_screen_stream(device: dict, token: str) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Connects to scripts/screen_agent.py running on the device."""
    host = target_host(device)
    port = device["screen_port"]

    reader, writer = await asyncio.open_connection(host, port)
    writer.write(f"{token}\n".encode())
    await writer.drain()

    status_line = await reader.readline()
    if status_line.strip() != b"OK":
        writer.close()
        message = status_line.decode(errors="replace").strip() or "screen agent closed the connection unexpectedly"
        raise RuntimeError(message)

    return reader, writer