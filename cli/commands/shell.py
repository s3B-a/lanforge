import asyncio
import sys
import websockets

def run(args, client):
    if args.command:
        result = client.post(f"/shell/{args.device}/exec", {"command": args.command})
        if result.get("stdout"):
            print(result["stdout"], end="")
        if result.get("stderr"):
            print(result["stderr"], end="", file=sys.stderr)
        sys.exit(result.get("exit_code", 0))

    asyncio.run(_interactive(client, args.device))

async def _interactive(client, device_id: str) -> None:
    ws_scheme = "wss" if client.hub_url.startswith("https://") else "ws"
    host_part = client.hub_url.split("://", 1)[1]
    url = f"{ws_scheme}://{host_part}/shell/{device_id}/session?token={client.token}"

    print(f"Connected to '{device_id}'. Ctrl+C to disconnect.")
    async with websockets.connect(url) as ws:
        reader_task = asyncio.create_task(_read_loop(ws))
        loop = asyncio.get_event_loop()
        try:
            while True:
                line = await loop.run_in_executor(None, sys.stdin.readline)
                if not line:
                    break
                await ws.send(line)
        except KeyboardInterrupt:
            pass
        finally:
            reader_task.cancel()

async def _read_loop(ws) -> None:
    async for message in ws:
        print(message, end="", flush=True)