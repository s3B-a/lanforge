import os
from pathlib import Path

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parents[1]

def resolve(args_hub_url: str | None, args_token: str | None) -> tuple[str, str]:
    """Priority: CLI flags > environment variables > cfg/.env"""
    env_path = PROJECT_ROOT / "cfg" / ".env"
    file_values = dotenv_values(env_path) if env_path.exists() else {}

    hub_host = file_values.get("HUB_HOST", "127.0.0.1")
    hub_host = "127.0.0.1" if hub_host == "0.0.0.0" else hub_host
    hub_port = file_values.get("HUB_PORT", "8080")

    hub_url = args_hub_url or os.environ.get("HUB_URL") or f"http://{hub_host}:{hub_port}"
    token = args_token or os.environ.get("HUB_TOKEN") or file_values.get("HUB_TOKEN")

    if not token:
        raise SystemExit(
            "No hub token found. Pass --token, set HUB_TOKEN, or run this from a "
            "clone with cfg/.env configured."
        )

    return hub_url.rstrip("/"), token
