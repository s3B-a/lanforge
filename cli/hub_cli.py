import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx

from client import HubClient
from commands import chat, shell, status
from config import resolve

def main() -> None:
    parser = argparse.ArgumentParser(prog="hub", description="CLI for the local home server hub")
    parser.add_argument("--hub-url", help="override the hub URL (default: cfg/.env or HUB_URL env var)")
    parser.add_argument("--token", help="override the hub token (default: cfg/.env or HUB_TOKEN env var)")

    sub = parser.add_subparsers(dest="command", required=True)

    p_status = sub.add_parser("status", help="show hub health, system stats, and the device list")
    p_status.set_defaults(func=status.run)

    p_chat = sub.add_parser("chat", help="chat with an LLM device")
    p_chat.add_argument("device", help="device id, e.g. llm-rig")
    p_chat.add_argument("--model", required=True, help="model tag, e.g. qwen3.8:27b-uncensored")
    p_chat.add_argument("-m", "--message", help="one-shot message; omit for an interactive session")
    p_chat.add_argument("--clear", action="store_true", help="clear this device's remembered chat history and exit")
    p_chat.set_defaults(func=chat.run)

    p_shell = sub.add_parser("shell", help="run a command on, or open a session to, an SSH device")
    p_shell.add_argument("device", help="device id, e.g. llm-rig")
    p_shell.add_argument("-c", "--command", help="one-shot command; omit for an interactive session")
    p_shell.set_defaults(func=shell.run)

    args = parser.parse_args()
    hub_url, token = resolve(args.hub_url, args.token)
    client = HubClient(hub_url, token)

    try:
        args.func(args, client)
    except httpx.ConnectError as exc:
        print(f"error: could not reach the hub at {hub_url}: {exc}", file=sys.stderr)
        sys.exit(1)
    except httpx.HTTPStatusError as exc:
        print(f"error: hub returned {exc.response.status_code}: {exc.response.text}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print()
        sys.exit(130)

if __name__ == "__main__":
    main()