"""Runs ON a remote device (e.g. the LLM rig) so the hub always knows its
current LAN IP, even when that device's address changes via DHCP.

Usage:
    python heartbeat_agent.py --hub-url http://hub-host:8080 --device-id llm-rig --token <HUB_TOKEN>
"""

import argparse
import random
import socket
import time
import urllib.error
import urllib.request
import json
from pathlib import Path

BANNERS_DIR = Path(__file__).resolve().parent / "banners"

def load_banners() -> list[str]:
    paths = sorted(BANNERS_DIR.glob("*.txt"))
    return [p.read_text(encoding="utf-8") for p in paths]

def local_ip() -> str:
    """No packets are actually sent; connecting a UDP socket just makes the
    OS pick the right outbound interface/IP for the route to 8.8.8.8."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    finally:
        s.close()

def send_heartbeat(hub_url: str, device_id: str, token: str, ip: str) -> None:
    url = f"{hub_url.rstrip('/')}/devices/{device_id}/heartbeat"
    payload = json.dumps({"ip": ip}).encode()
    request = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=10) as resp:
        resp.read()

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hub-url", required=True)
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--interval", type=int, default=30)
    args = parser.parse_args()

    print(random.choice(load_banners()))
    print(f"device id : {args.device_id}")
    print(f"hub       : {args.hub_url}")
    print(f"interval  : every {args.interval}s")
    print()

    while True:
        ip = local_ip()
        print(f"--> connecting to hub as {ip} ...", end=" ", flush=True)
        try:
            send_heartbeat(args.hub_url, args.device_id, args.token, ip)
            print("connected, hub updated.")
        except urllib.error.URLError as exc:
            print(f"failed: {exc}")
        time.sleep(args.interval)

if __name__ == "__main__":
    main()