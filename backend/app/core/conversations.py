import json
import secrets
import threading
import time

from app.core.config import PROJECT_ROOT

_lock = threading.Lock()
_CONVERSATIONS_DIR = PROJECT_ROOT / "cfg" / "conversations"

def _device_dir(device_id: str):
    return _CONVERSATIONS_DIR / device_id

def _index_path(device_id: str):
    return _device_dir(device_id) / "index.json"

def _messages_path(device_id: str, conversation_id: str):
    return _device_dir(device_id) / f"{conversation_id}.json"

def _legacy_path(device_id: str):
    return _CONVERSATIONS_DIR / f"{device_id}.json"

def _load_index_unlocked(device_id: str) -> list[dict]:
    path = _index_path(device_id)
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f).get("conversations", [])

def _save_index_unlocked(device_id: str, entries: list[dict]) -> None:
    _device_dir(device_id).mkdir(parents=True, exist_ok=True)
    with open(_index_path(device_id), "w", encoding="utf-8") as f:
        json.dump({"conversations": entries}, f, indent=2)

def _load_messages_unlocked(device_id: str, conversation_id: str) -> list[dict]:
    path = _messages_path(device_id, conversation_id)
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f).get("messages", [])

def _save_messages_unlocked(device_id: str, conversation_id: str, messages: list[dict]) -> None:
    _device_dir(device_id).mkdir(parents=True, exist_ok=True)
    with open(_messages_path(device_id, conversation_id), "w", encoding="utf-8") as f:
        json.dump({"messages": messages}, f, indent=2)

def _new_entry_unlocked(device_id: str, title: str | None, messages: list[dict] | None = None) -> dict:
    entries = _load_index_unlocked(device_id)
    entry = {
        "id": secrets.token_hex(6),
        "title": title or "New chat",
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    entries.append(entry)
    _save_index_unlocked(device_id, entries)
    _save_messages_unlocked(device_id, entry["id"], messages or [])
    return entry

def _migrate_legacy_unlocked(device_id: str) -> None:
    legacy_path = _legacy_path(device_id)
    if not legacy_path.exists():
        return
    try:
        with open(legacy_path, "r", encoding="utf-8") as f:
            messages = json.load(f).get("messages", [])
    except (OSError, json.JSONDecodeError):
        messages = []

    legacy_path.rename(legacy_path.with_suffix(".json.bak"))
    if messages:
        _new_entry_unlocked(device_id, "Previous chat", messages)

def list_conversations(device_id: str) -> list[dict]:
    with _lock:
        if not _index_path(device_id).exists():
            _migrate_legacy_unlocked(device_id)

        entries = _load_index_unlocked(device_id)
        if not entries:
            entries = [_new_entry_unlocked(device_id, "New chat")]

        return sorted(entries, key=lambda e: e["updated_at"], reverse=True)

def create_conversation(device_id: str, title: str | None = None) -> dict:
    with _lock:
        return _new_entry_unlocked(device_id, title)

def conversation_exists(device_id: str, conversation_id: str) -> bool:
    with _lock:
        return any(e["id"] == conversation_id for e in _load_index_unlocked(device_id))

def get_conversation(device_id: str, conversation_id: str) -> dict | None:
    with _lock:
        for entry in _load_index_unlocked(device_id):
            if entry["id"] == conversation_id:
                return entry
            
        return None

def set_title(device_id: str, conversation_id: str, title: str) -> dict | None:
    with _lock:
        entries = _load_index_unlocked(device_id)
        updated = None
        for entry in entries:
            if entry["id"] == conversation_id:
                entry["title"] = title
                updated = entry
                break
        if updated is not None:
            _save_index_unlocked(device_id, entries)

        return updated

def delete_conversation(device_id: str, conversation_id: str) -> None:
    with _lock:
        entries = [e for e in _load_index_unlocked(device_id) if e["id"] != conversation_id]
        _save_index_unlocked(device_id, entries)
        path = _messages_path(device_id, conversation_id)
        if path.exists():
            path.unlink()

def load_messages(device_id: str, conversation_id: str) -> list[dict]:
    with _lock:
        return _load_messages_unlocked(device_id, conversation_id)

def append_message(device_id: str, conversation_id: str, message: dict) -> list[dict]:
    with _lock:
        messages = _load_messages_unlocked(device_id, conversation_id)
        messages.append(message)
        _save_messages_unlocked(device_id, conversation_id, messages)

        entries = _load_index_unlocked(device_id)
        found = False
        for entry in entries:
            if entry["id"] == conversation_id:
                entry["updated_at"] = time.time()
                if entry.get("title") in (None, "", "New chat") and message.get("role") == "user" and message.get("content"):
                    entry["title"] = message["content"][:40]
                found = True
                break
        if not found:
            entries.append(
                {
                    "id": conversation_id,
                    "title": "New chat",
                    "created_at": time.time(),
                    "updated_at": time.time(),
                }
            )
        _save_index_unlocked(device_id, entries)

        return messages

def clear(device_id: str, conversation_id: str) -> None:
    with _lock:
        _save_messages_unlocked(device_id, conversation_id, [])

def replace_messages(device_id: str, conversation_id: str, messages: list[dict]) -> None:
    with _lock:
        _save_messages_unlocked(device_id, conversation_id, messages)