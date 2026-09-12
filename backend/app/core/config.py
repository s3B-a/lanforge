from pathlib import Path

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parents[3]

_env_path = PROJECT_ROOT / "cfg" / ".env"
_values = {**dotenv_values(PROJECT_ROOT / "cfg" / ".env.example"), **dotenv_values(_env_path)}

def _get(key: str, default: str = "") -> str:
    return _values.get(key) or default

HUB_TOKEN = _get("HUB_TOKEN")
HUB_HOST = _get("HUB_HOST", "0.0.0.0")
HUB_PORT = int(_get("HUB_PORT", "8080"))
DEVICES_FILE = PROJECT_ROOT / _get("DEVICES_FILE", "cfg/devices.json")
HEARTBEAT_TIMEOUT = int(_get("HEARTBEAT_TIMEOUT", "90"))

if not _env_path.exists():
    raise RuntimeError(
        f"Missing {_env_path}. Copy cfg/.env.example to cfg/.env and fill in HUB_TOKEN."
    )

if HUB_TOKEN == "changeme-generate-a-long-random-token" or not HUB_TOKEN:
    raise RuntimeError("Set a real HUB_TOKEN in cfg/.env before starting the hub.")
