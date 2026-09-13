import argparse
import socket
import subprocess
import sys
import threading
import time

_STARTUP_GRACE_SECONDS = 1.0

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
        try:
            while True:
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                conn.sendall(chunk)
        finally:
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