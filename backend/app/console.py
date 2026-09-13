"""Interactive command console for the hub's own terminal window.

Runs in a background thread alongside the Robyn server, so the same window
you started `python -m app.main` in doubles as a live console: it can run
shell commands on the hub machine itself ("local") or on any registered SSH
device, send one-shot chat messages to any registered LLM device, and pull
a live CPU/RAM/disk/network/GPU snapshot of any registered SSH device.

No auth token needed here, unlike the HTTP API: whoever can type into this
terminal already has local control of the hub machine, same trust level as
opening a plain shell on it.
"""

import asyncio
import cmd
import shlex
import subprocess
import threading

from app.core import devices_store
from app.services import llm_client, monitor, ssh_client

def _fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024

    return f"{n:.1f}PB"

def _cmd_status(args: list[str]) -> None:
    stats = monitor.get_local_stats()
    print(f"hub: {stats['hostname']}")
    print(f"  cpu    : {stats['cpu']['percent']:.1f}%")
    print(f"  memory : {stats['memory']['percent']:.1f}%  ({_fmt_bytes(stats['memory']['used'])} / {_fmt_bytes(stats['memory']['total'])})")
    print(f"  disk   : {stats['disk']['percent']:.1f}%  ({_fmt_bytes(stats['disk']['used'])} / {_fmt_bytes(stats['disk']['total'])})")
    print(f"  net    : sent {_fmt_bytes(stats['network']['bytes_sent'])}  recv {_fmt_bytes(stats['network']['bytes_recv'])}")
    gpu = stats.get("gpu")
    if gpu:
        print(f"  gpu    : {gpu['percent']:.0f}%  ({gpu['memory_used_mb']:.0f}MB / {gpu['memory_total_mb']:.0f}MB)")
    else:
        print("  gpu    : n/a")

    for device in devices_store.list_devices():
        state = "online" if device["online"] else "offline"
        print(f"  {device['id']:<15} {device['kind']:<10} {state}")

        if device["kind"] != "ssh" or not device["online"]:
            continue
        try:
            remote = ssh_client.get_remote_stats(device)
        except Exception as exc:
            print(f"    (could not get stats: {exc})")
            continue
        _print_remote_stats(remote)

def _print_remote_stats(remote: dict) -> None:
    mem_total = remote.get("memory_total") or 0
    mem_used = remote.get("memory_used") or 0
    disk_total = remote.get("disk_total") or 0
    disk_used = remote.get("disk_used") or 0
    mem_pct = (mem_used / mem_total * 100) if mem_total else 0
    disk_pct = (disk_used / disk_total * 100) if disk_total else 0

    print(f"    cpu    : {remote.get('cpu_percent') or 0:.1f}%")
    print(f"    memory : {mem_pct:.1f}%  ({_fmt_bytes(mem_used)} / {_fmt_bytes(mem_total)})")
    print(f"    disk   : {disk_pct:.1f}%  ({_fmt_bytes(disk_used)} / {_fmt_bytes(disk_total)})")
    print(
        f"    net    : sent {_fmt_bytes(remote.get('network_sent') or 0)}  "
        f"recv {_fmt_bytes(remote.get('network_recv') or 0)}"
    )
    gpu = remote.get("gpu")
    if gpu:
        print(f"    gpu    : {gpu['percent']:.0f}%  ({gpu['memory_used_mb']:.0f}MB / {gpu['memory_total_mb']:.0f}MB)")
    else:
        print("    gpu    : n/a")

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

_HELP = (
    "commands:\n"
    "  status                                  hub + all ssh devices: cpu/ram/disk/net/gpu\n"
    "  shell <device-id|local> <command...>    run a command on a device, or 'local' for this machine\n"
    "  chat <device-id> <model> <message...>   one-shot chat with an llm device\n"
    "  help                                    show this again\n"
    "  exit                                    stop the console (server keeps running)\n"
    "\n"
    "tab-completes device ids (shell, chat) and model names (chat, once a device is typed)."
)

class HubConsole(cmd.Cmd):
    prompt = "hub> "

    def preloop(self) -> None:
        try:
            import readline

            readline.set_completer_delims(" \t\n")
        except ImportError:
            pass

    def emptyline(self) -> None:
        pass

    def default(self, line: str) -> None:
        cmd_word = line.split()[0] if line.split() else line
        print(f"unknown command '{cmd_word}', type 'help' for the list")

    def do_status(self, arg: str) -> None:
        _cmd_status(shlex.split(arg))

    def do_shell(self, arg: str) -> None:
        _cmd_shell(shlex.split(arg))

    def do_chat(self, arg: str) -> None:
        _cmd_chat(shlex.split(arg))

    def do_help(self, arg: str) -> None:
        print(_HELP)

    def do_exit(self, arg: str) -> bool:
        print("(console stopped; server keeps running)")

        return True

    do_quit = do_exit

    def do_EOF(self, arg: str) -> bool:
        print()
        print("(console stopped; server keeps running)")

        return True

    def _device_ids(self, kinds: set[str] | None = None) -> list[str]:
        devices = devices_store.list_devices()
        if kinds:
            devices = [d for d in devices if d["kind"] in kinds]

        return [d["id"] for d in devices]

    def complete_shell(self, text: str, line: str, begidx: int, endidx: int) -> list[str]:
        words = line[:begidx].split()
        if len(words) <= 1:
            candidates = ["local"] + self._device_ids(kinds={"ssh"})
            return [c for c in candidates if c.startswith(text)]
        
        return []

    def complete_chat(self, text: str, line: str, begidx: int, endidx: int) -> list[str]:
        words = line[:begidx].split()
        if len(words) <= 1:
            return [c for c in self._device_ids(kinds={"ssh"}) if c.startswith(text)]
        if len(words) == 2:
            device = devices_store.get_device(words[1])
            if device is None or "ollama_port" not in device:
                return []
            try:
                data = asyncio.run(llm_client.list_models(device))
            except Exception:
                return []
            names = [m.get("name") or m.get("model") for m in data.get("models", [])]
            return [n for n in names if n and n.startswith(text)]
        
        return []

    def cmdloop_forever(self) -> None:
        try:
            self.cmdloop(intro="Hub console ready, type 'help' for commands.")
        except KeyboardInterrupt:
            print()
            print("(console stopped; server keeps running)")

def start_console_thread() -> threading.Thread:
    thread = threading.Thread(target=HubConsole().cmdloop_forever, name="hub-console", daemon=True)
    thread.start()
    return thread