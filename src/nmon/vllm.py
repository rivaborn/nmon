"""Lightweight vLLM HTTP client.

Talks to a local vLLM server over its OpenAI-compatible REST API using
only the Python standard library — no new package dependencies. Used
by the collector to sample what model (if any) is currently served.

The vLLM API endpoints we care about:

- ``GET /v1/models`` -> OpenAI-style list of served models. vLLM is
  started with a single model and keeps it pinned in GPU VRAM for the
  lifetime of the process, so we just need the first entry's ``id``.

That endpoint is generic OpenAI, so other servers (Ollama, llama.cpp,
LM Studio, …) answer it too. To avoid latching the "vLLM Server" panel
onto a non-vLLM server when ``vllm.url`` is misconfigured, we require the
model's ``owned_by`` field to be vLLM's ("vllm"); Ollama reports
"library". See ``_is_vllm_model``.

Unlike Ollama, vLLM does not support partial CPU offload — the model
either fits in VRAM or the server fails to start — so there is no
GPU/CPU split to surface.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass
class VLLMStatus:
    """Snapshot of the model currently served by a vLLM server.

    ``running=False`` means the server responded but reported no model
    in ``/v1/models`` — unusual for vLLM but handled defensively.
    """
    running: bool
    model_name: str | None


# vLLM stamps its /v1/models entries with owned_by="vllm". Other
# OpenAI-compatible servers use a different owner (Ollama: "library"), so
# this is how we tell a real vLLM server from one that merely speaks the same
# REST dialect. A missing/blank owner is accepted so a vLLM build that doesn't
# populate the field still registers; only a present, non-vLLM owner is
# rejected.
_VLLM_OWNER = "vllm"


def _is_vllm_model(model: dict) -> bool:
    owned_by = str(model.get("owned_by", "")).strip().lower()
    return owned_by in ("", _VLLM_OWNER)


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
        """True only when the URL serves a *vLLM* ``/v1/models`` response.

        Delegates to ``get_running`` so the owned_by check applies to the
        startup probe too: pointing ``vllm.url`` at another OpenAI-compatible
        server reports "no vLLM server" instead of falsely detecting it.
        """
        return self.get_running() is not None

    def get_running(self) -> VLLMStatus | None:
        """Return the first vLLM-served model, or a ``running=False`` stub if
        a vLLM server responded but listed no models. Returns ``None`` when the
        server is unreachable *or* responded but is not vLLM — so a
        misconfigured non-vLLM URL is treated as "no vLLM server"."""
        try:
            payload = self._get("/v1/models")
        except Exception:
            return None
        models = payload.get("data") or []
        if not models:
            # A vLLM server that responded with no model loaded (unusual).
            return VLLMStatus(running=False, model_name=None)
        vllm_models = [m for m in models if _is_vllm_model(m)]
        if not vllm_models:
            # Responded with models, but none are vLLM-owned -> some other
            # OpenAI-compatible server. Treat it as "not a vLLM server".
            return None
        m = vllm_models[0]
        return VLLMStatus(running=True, model_name=m.get("id"))

    def _get(self, path: str) -> dict:
        url = self._base + path
        if urlparse(url).scheme not in ("http", "https"):
            raise ValueError(f"refusing non-http(s) URL: {url!r}")
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            data = resp.read()
        return json.loads(data.decode("utf-8"))
