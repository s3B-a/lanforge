import json
import socket
import threading
import time

from app.core.config import DEVICES_FILE, HEARTBEAT_TIMEOUT

_lock = threading.Lock()

def _load() -> dict:
    if not DEVICES_FILE.exists():
        return {"devices": []}
    with open(DEVICES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def _save(data: dict) -> None:
    DEVICES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DEVICES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def _probe_tcp(host: str, port: int, timeout: float = 0.75) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False

def _is_online(device: dict) -> bool:
    if device["kind"] == "ssh":
        last_seen = device.get("last_seen")
        if last_seen is not None and time.time() - last_seen <= HEARTBEAT_TIMEOUT:
            return True
        
        # fall back to a live SSH port
        return _probe_tcp(device.get("last_ip") or device["host"], device.get("ssh_port", 22))
    if device["kind"] == "presence":
        return _probe_tcp(device["host"], device.get("probe_port", 80))
    
    return False

def target_host(device: dict) -> str:
    """Address to actually connect to: prefer the last self-reported IP
    (handles DHCP address changes) and fall back to the configured host"""
    return device.get("last_ip") or device["host"]

def list_devices() -> list[dict]:
    with _lock:
        data = _load()
    for device in data["devices"]:
        device["online"] = _is_online(device)

    return data["devices"]

def get_device(device_id: str) -> dict | None:
    for device in list_devices():
        if device["id"] == device_id:
            return device
        
    return None

def add_device(device: dict) -> dict:
    with _lock:
        data = _load()
        if any(d["id"] == device["id"] for d in data["devices"]):
            raise ValueError(f"device '{device['id']}' already exists")
        data["devices"].append(device)
        _save(data)

    return device

def update_device(device_id: str, fields: dict) -> dict | None:
    """Merges the given fields into an existing device (used for e.g. adding
    ollama_port after the fact, without deleting and re-adding it)."""
    with _lock:
        data = _load()
        for device in data["devices"]:
            if device["id"] == device_id:
                device.update({k: v for k, v in fields.items() if v is not None})
                _save(data)
                return device
            
        return None

def remove_device(device_id: str) -> bool:
    with _lock:
        data = _load()
        before = len(data["devices"])
        data["devices"] = [d for d in data["devices"] if d["id"] != device_id]
        _save(data)

        return len(data["devices"]) < before

def record_heartbeat(device_id: str, ip: str) -> dict | None:
    with _lock:
        data = _load()
        for device in data["devices"]:
            if device["id"] == device_id:
                device["last_ip"] = ip
                device["last_seen"] = time.time()
                _save(data)
                return device
            
        return None