"""Lightweight Ollama HTTP client.

Talks to a local Ollama server over its REST API using only the Python
standard library — no new package dependencies. Used by the collector
to sample what model (if any) is currently loaded and how it is split
between GPU VRAM and system RAM.

The Ollama API endpoints we care about:

- ``GET /api/version``  -> cheap liveness probe, returns 200 when up.
- ``GET /api/ps``       -> list of currently loaded models, with
  ``size`` (total model size in bytes) and ``size_vram`` (bytes that
  actually live in VRAM). When ``size_vram < size`` the model is
  partially offloaded to CPU / system RAM, which is exactly what we
  want to surface as "GPU offloading" in the TUI.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass
class OllamaStatus:
    """Snapshot of the most relevant running model on an Ollama server.

    Ollama supports multiple models loaded at once; we only surface the
    first one in the /api/ps response since the dashboard has room for
    a single row. ``running=False`` means the server is reachable but
    no model is currently loaded.
    """
    running: bool
    model_name: str | None
    size_bytes: int
    size_vram_bytes: int

    @property
    def gpu_pct(self) -> float:
        if self.size_bytes <= 0:
            return 0.0
        return max(0.0, min(100.0, self.size_vram_bytes / self.size_bytes * 100.0))

    @property
    def cpu_pct(self) -> float:
        return max(0.0, 100.0 - self.gpu_pct)

    @property
    def offloading(self) -> bool:
        """True when any part of the model lives outside VRAM."""
        return self.running and self.gpu_pct < 100.0


class OllamaClient:
    """Best-effort Ollama poller.

    All network calls are guarded with a short timeout and swallow
    every error into ``None``. The collector calls this on every tick,
    so failures must never raise — they just mean "no data this cycle".
    """

    def __init__(self, base_url: str = "http://localhost:11434", timeout: float = 0.5):
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    def ping(self) -> bool:
        try:
            self._get("/api/version")
            return True
        except Exception:
            return False

    def get_running(self) -> OllamaStatus | None:
        """Return the first running model, or a ``running=False`` stub
        if the server is up but no model is loaded. Returns ``None``
        when the server is unreachable."""
        try:
            payload = self._get("/api/ps")
        except Exception:
            return None
        models = payload.get("models") or []
        if not models:
            return OllamaStatus(
                running=False,
                model_name=None,
                size_bytes=0,
                size_vram_bytes=0,
            )
        m = models[0]
        return OllamaStatus(
            running=True,
            model_name=m.get("name") or m.get("model"),
            size_bytes=int(m.get("size") or 0),
            size_vram_bytes=int(m.get("size_vram") or 0),
        )

    def _get(self, path: str) -> dict:
        url = self._base + path
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            data = resp.read()
        return json.loads(data.decode("utf-8"))
