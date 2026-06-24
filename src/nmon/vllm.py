"""Lightweight vLLM HTTP client.

Talks to a local vLLM server over its OpenAI-compatible REST API using
only the Python standard library — no new package dependencies. Used
by the collector to sample what model (if any) is currently served.

The vLLM API endpoints we care about:

- ``GET /v1/models`` -> OpenAI-style list of served models. vLLM is
  started with a single model and keeps it pinned in GPU VRAM for the
  lifetime of the process, so we just need the first entry's ``id``.

Unlike Ollama, vLLM does not support partial CPU offload — the model
either fits in VRAM or the server fails to start — so there is no
GPU/CPU split to surface.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass
class VLLMStatus:
    """Snapshot of the model currently served by a vLLM server.

    ``running=False`` means the server responded but reported no model
    in ``/v1/models`` — unusual for vLLM but handled defensively.
    """
    running: bool
    model_name: str | None


class VLLMClient:
    """Best-effort vLLM poller.

    All network calls are guarded with a short timeout and swallow
    every error into ``None``. The collector calls this on every tick,
    so failures must never raise — they just mean "no data this cycle".
    """

    def __init__(self, base_url: str = "http://localhost:8000", timeout: float = 0.5):
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    def ping(self) -> bool:
        try:
            self._get("/v1/models")
            return True
        except Exception:
            return False

    def get_running(self) -> VLLMStatus | None:
        """Return the first served model, or a ``running=False`` stub
        if the server responded but listed no models. Returns ``None``
        when the server is unreachable."""
        try:
            payload = self._get("/v1/models")
        except Exception:
            return None
        models = payload.get("data") or []
        if not models:
            return VLLMStatus(running=False, model_name=None)
        m = models[0]
        return VLLMStatus(running=True, model_name=m.get("id"))

    def _get(self, path: str) -> dict:
        url = self._base + path
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            data = resp.read()
        return json.loads(data.decode("utf-8"))
