import argparse
import ctypes
import json
import select
import socket
import subprocess
import sys
import threading
import time
from ctypes import wintypes

_STARTUP_GRACE_SECONDS = 1.0

user32 = ctypes.windll.user32

_INPUT_MOUSE = 0
_INPUT_KEYBOARD = 1

_MOUSEEVENTF_MOVE = 0x0001
_MOUSEEVENTF_ABSOLUTE = 0x8000
_MOUSEEVENTF_WHEEL = 0x0800
_MOUSE_BUTTON_FLAGS = {
    ("left", True): 0x0002,
    ("left", False): 0x0004,
    ("right", True): 0x0008,
    ("right", False): 0x0010,
    ("middle", True): 0x0020,
    ("middle", False): 0x0040,
}

_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_UNICODE = 0x0004

_VK_MAP = {
    "Enter": 0x0D,
    "Backspace": 0x08,
    "Tab": 0x09,
    "Escape": 0x1B,
    "Delete": 0x2E,
    "ArrowUp": 0x26,
    "ArrowDown": 0x28,
    "ArrowLeft": 0x25,
    "ArrowRight": 0x27,
    "Home": 0x24,
    "End": 0x23,
    "PageUp": 0x21,
    "PageDown": 0x22,
    "Control": 0x11,
    "Shift": 0x10,
    "Alt": 0x12,
    "Meta": 0x5B,
    "F1": 0x70, "F2": 0x71, "F3": 0x72, "F4": 0x73, "F5": 0x74, "F6": 0x75,
    "F7": 0x76, "F8": 0x77, "F9": 0x78, "F10": 0x79, "F11": 0x7A, "F12": 0x7B,
}

class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]

class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]

class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]

class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUTUNION)]

def _send_inputs(*inputs: _INPUT) -> None:
    count = len(inputs)
    array = (_INPUT * count)(*inputs)
    user32.SendInput(count, array, ctypes.sizeof(_INPUT))

def _move_mouse(x_frac: float, y_frac: float) -> None:
    x_frac = min(1.0, max(0.0, x_frac))
    y_frac = min(1.0, max(0.0, y_frac))
    mi = _MOUSEINPUT(
        dx=int(x_frac * 65535), dy=int(y_frac * 65535), mouseData=0,
        dwFlags=_MOUSEEVENTF_MOVE | _MOUSEEVENTF_ABSOLUTE, time=0, dwExtraInfo=None,
    )
    _send_inputs(_INPUT(type=_INPUT_MOUSE, union=_INPUTUNION(mi=mi)))

def _mouse_button(button: str, down: bool) -> None:
    flags = _MOUSE_BUTTON_FLAGS.get((button, down))
    if flags is None:
        return
    mi = _MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=flags, time=0, dwExtraInfo=None)
    _send_inputs(_INPUT(type=_INPUT_MOUSE, union=_INPUTUNION(mi=mi)))

def _mouse_scroll(delta: int) -> None:
    mi = _MOUSEINPUT(dx=0, dy=0, mouseData=delta, dwFlags=_MOUSEEVENTF_WHEEL, time=0, dwExtraInfo=None)
    _send_inputs(_INPUT(type=_INPUT_MOUSE, union=_INPUTUNION(mi=mi)))

def _type_text(text: str) -> None:
    inputs = []
    for ch in text:
        code = ord(ch)
        inputs.append(_INPUT(type=_INPUT_KEYBOARD, union=_INPUTUNION(
            ki=_KEYBDINPUT(wVk=0, wScan=code, dwFlags=_KEYEVENTF_UNICODE, time=0, dwExtraInfo=None)
        )))
        inputs.append(_INPUT(type=_INPUT_KEYBOARD, union=_INPUTUNION(
            ki=_KEYBDINPUT(wVk=0, wScan=code, dwFlags=_KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP, time=0, dwExtraInfo=None)
        )))
    if inputs:
        _send_inputs(*inputs)

def _key_event(key: str, down: bool) -> None:
    vk = _VK_MAP.get(key)
    if vk is None:
        return
    flags = 0 if down else _KEYEVENTF_KEYUP
    ki = _KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=None)
    _send_inputs(_INPUT(type=_INPUT_KEYBOARD, union=_INPUTUNION(ki=ki)))

def _apply_input_event(line: bytes) -> None:
    """One JSON object per line, from the browser via the hub:
      {"type": "mouse_move", "x": 0..1, "y": 0..1}
      {"type": "mouse_down"|"mouse_up", "x": 0..1, "y": 0..1, "button": "left"|"right"|"middle"}
      {"type": "scroll", "dy": <signed int>}
      {"type": "text", "text": "..."}                (printable characters)
      {"type": "key_down"|"key_up", "key": "Enter"}  (special keys, see _VK_MAP)
    x/y are fractions of the captured desktop (0.0 top/left - 1.0 bottom/right),
    not pixels, so this doesn't need to know the actual screen resolution."""
    try:
        event = json.loads(line.decode(errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return

    kind = event.get("type")
    try:
        if kind == "mouse_move":
            _move_mouse(float(event["x"]), float(event["y"]))
        elif kind == "mouse_down":
            _move_mouse(float(event["x"]), float(event["y"]))
            _mouse_button(event.get("button", "left"), True)
        elif kind == "mouse_up":
            _move_mouse(float(event["x"]), float(event["y"]))
            _mouse_button(event.get("button", "left"), False)
        elif kind == "scroll":
            _mouse_scroll(int(event.get("dy", 0)))
        elif kind == "text":
            _type_text(str(event.get("text", "")))
        elif kind == "key_down":
            _key_event(str(event.get("key", "")), True)
        elif kind == "key_up":
            _key_event(str(event.get("key", "")), False)
    except (KeyError, ValueError, TypeError) as exc:
        print(f"bad input event {event!r}: {exc}")

def _pump_input(conn: socket.socket, stop_event: threading.Event) -> None:
    """Reads newline-delimited JSON input events from the same connection
    the frames are being streamed out on, on its own thread."""
    buffer = b""
    try:
        while not stop_event.is_set():
            ready, _, _ = select.select([conn], [], [], 1.0)
            if not ready:
                continue
            chunk = conn.recv(4096)
            if not chunk:
                return
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                if line:
                    _apply_input_event(line)
    except (ConnectionError, OSError):
        pass

def _handle_client(conn: socket.socket, token: str, framerate: int, quality: int) -> None:
    addr = conn.getpeername()
    try:
        conn.settimeout(10)
        line = b""
        while not line.endswith(b"\n"):
            chunk = conn.recv(256)
            if not chunk:
                return
            line += chunk
        conn.settimeout(None)

        if line.strip().decode(errors="replace") != token:
            print(f"{addr}: rejected, bad token")
            conn.sendall(b"ERROR: invalid token\n")
            return

        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-f", "gdigrab",
            "-framerate", str(framerate),
            "-i", "desktop",
            "-f", "image2pipe",
            "-vcodec", "mjpeg",
            "-q:v", str(quality),
            "-",
        ]
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        time.sleep(_STARTUP_GRACE_SECONDS)
        if proc.poll() is not None:
            stderr_text = proc.stderr.read().decode(errors="replace").strip()
            print(f"{addr}: ffmpeg exited immediately: {stderr_text}")
            conn.sendall(f"ERROR: {stderr_text or 'ffmpeg exited immediately'}\n".encode())
            return

        print(f"{addr}: streaming")
        conn.sendall(b"OK\n")

        stop_event = threading.Event()
        input_thread = threading.Thread(target=_pump_input, args=(conn, stop_event), daemon=True)
        input_thread.start()
        try:
            while True:
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                conn.sendall(chunk)
        finally:
            stop_event.set()
            proc.kill()
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
    except (ConnectionError, OSError) as exc:
        print(f"{addr}: connection error: {exc}")
    finally:
        conn.close()
        print(f"{addr}: disconnected")

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--token", required=True, help="must match HUB_TOKEN in the hub's cfg/.env")
    parser.add_argument("--port", type=int, default=5910)
    parser.add_argument("--framerate", type=int, default=15)
    parser.add_argument("--quality", type=int, default=5, help="ffmpeg mjpeg -q:v scale, 2 (best) - 31 (worst)")
    args = parser.parse_args()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(("0.0.0.0", args.port))
    except OSError as exc:
        print(f"error: could not bind to port {args.port}: {exc}", file=sys.stderr)
        sys.exit(1)
    server.listen(5)
    print(f"screen agent listening on :{args.port}, Ctrl+C to stop")

    try:
        while True:
            conn, _addr = server.accept()
            threading.Thread(
                target=_handle_client,
                args=(conn, args.token, args.framerate, args.quality),
                daemon=True,
            ).start()
    except KeyboardInterrupt:
        print()

if __name__ == "__main__":
    main()