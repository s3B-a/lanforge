"""Interactive command console for the hub's own terminal window.

Runs in a background thread alongside the Robyn server, so the same window
you started `python -m app.main` in doubles as a live console: it can run
shell commands on the hub machine itself ("local") or on any registered SSH
device, and send one-shot chat messages to any registered LLM device.

No auth token needed here, unlike the HTTP API: whoever can type into this
terminal already has local control of the hub machine, same trust level as
opening a plain shell on it.
"""

import asyncio
import shlex
import subprocess
import threading

from app.core import devices_store
from app.services import llm_client, monitor, ssh_client

def _cmd_status(args: list[str]) -> None:
    stats = monitor.get_local_stats()
    print(
        f"hub: {stats['hostname']}  "
        f"cpu {stats['cpu']['percent']:.1f}%  "
        f"mem {stats['memory']['percent']:.1f}%"
    )
    for device in devices_store.list_devices():
        state = "online" if device["online"] else "offline"
        print(f"  {device['id']:<15} {device['kind']:<10} {state}")

def _cmd_shell(args: list[str]) -> None:
    if len(args) < 2:
        print("usage: shell <device-id|local> <command...>")
        return

    target, *command_parts = args
    command = " ".join(command_parts)

    if target == "local":
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        print(result.stdout, end="")
        print(result.stderr, end="")
        return

    device = devices_store.get_device(target)
    if device is None or device["kind"] != "ssh":
        print(f"error: '{target}' is not a known ssh device")
        return

    result = ssh_client.run_command(device, command)
    print(result["stdout"], end="")
    print(result["stderr"], end="")

def _cmd_chat(args: list[str]) -> None:
    if len(args) < 3:
        print("usage: chat <device-id> <model> <message...>")
        return

    device_id, model, *message_parts = args
    message = " ".join(message_parts)

    device = devices_store.get_device(device_id)
    if device is None or device["kind"] != "ssh" or "ollama_port" not in device:
        print(f"error: '{device_id}' is not a known llm device")
        return

    try:
        data = asyncio.run(llm_client.chat(device, model, [{"role": "user", "content": message}]))
        print(data.get("message", {}).get("content", ""))
    except Exception as exc:
        print(f"error: {exc}")

_COMMANDS = {
    "status": _cmd_status,
    "shell": _cmd_shell,
    "chat": _cmd_chat,
}

_HELP = (
    "commands:\n"
    "  status                                  hub stats + device list\n"
    "  shell <device-id|local> <command...>    run a command on a device, or 'local' for this machine\n"
    "  chat <device-id> <model> <message...>   one-shot chat with an llm device\n"
    "  help                                    show this again\n"
    "  exit                                    stop the console (server keeps running)"
)

def _loop() -> None:
    print("Hub console ready, type 'help' for commands.")
    while True:
        try:
            line = input("hub> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not line:
            continue

        try:
            cmd, *args = shlex.split(line)
        except ValueError as exc:
            print(f"error: {exc}")
            continue

        if cmd in ("exit", "quit"):
            print("(console stopped; server keeps running)")
            break
        if cmd == "help":
            print(_HELP)
            continue

        handler = _COMMANDS.get(cmd)
        if handler is None:
            print(f"unknown command '{cmd}', type 'help' for the list")
            continue

        try:
            handler(args)
        except Exception as exc:
            print(f"error: {exc}")

def start_console_thread() -> threading.Thread:
    thread = threading.Thread(target=_loop, name="hub-console", daemon=True)
    thread.start()
    return thread