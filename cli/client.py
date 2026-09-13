from typing import Iterator

import httpx

class HubClient:
    def __init__(self, hub_url: str, token: str):
        self.hub_url = hub_url
        self.token = token
        self.headers = {"Authorization": f"Bearer {token}"}

    def get(self, path: str) -> dict:
        resp = httpx.get(f"{self.hub_url}{path}", headers=self.headers, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def post(self, path: str, json: dict | None = None) -> dict:
        resp = httpx.post(f"{self.hub_url}{path}", headers=self.headers, json=json or {}, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def stream_post(self, path: str, json: dict) -> Iterator[str]:
        """Yields raw SSE lines (still prefixed with 'data: ')"""
        with httpx.stream(
            "POST", f"{self.hub_url}{path}", headers=self.headers, json=json, timeout=None
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if line:
                    yield line