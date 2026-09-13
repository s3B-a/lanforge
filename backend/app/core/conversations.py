import json
import threading

from app.core.config import PROJECT_ROOT

_lock = threading.Lock()
_CONVERSATIONS_DIR = PROJECT_ROOT / "cfg" / "conversations"

def _path(device_id: str):
    return _CONVERSATIONS_DIR / f"{device_id}.json"

def _load_unlocked(device_id: str) -> list[dict]:
    path = _path(device_id)
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f).get("messages", [])

def _save_unlocked(device_id: str, messages: list[dict]) -> None:
    _CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)
    with open(_path(device_id), "w", encoding="utf-8") as f:
        json.dump({"messages": messages}, f, indent=2)

def load_messages(device_id: str) -> list[dict]:
    with _lock:
        return _load_unlocked(device_id)

def append_message(device_id: str, message: dict) -> list[dict]:
    with _lock:
        messages = _load_unlocked(device_id)
        messages.append(message)
        _save_unlocked(device_id, messages)
        
        return messages

def clear(device_id: str) -> None:
    with _lock:
        _save_unlocked(device_id, [])

def replace_messages(device_id: str, messages: list[dict]) -> None:
    with _lock:
        _save_unlocked(device_id, messages)