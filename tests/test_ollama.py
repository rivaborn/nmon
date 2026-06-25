import pytest
from nmon.ollama import OllamaClient, OllamaStatus


def _client(monkeypatch, payload=None, exc=None):
    c = OllamaClient("http://test:11434")

    def fake_get(path):
        if exc is not None:
            raise exc
        return payload

    monkeypatch.setattr(c, "_get", fake_get)
    return c


def test_percentages_full_vram():
    s = OllamaStatus(running=True, model_name="m", size_bytes=1000, size_vram_bytes=1000)
    assert s.gpu_pct == 100.0
    assert s.cpu_pct == 0.0
    assert s.offloading is False


def test_percentages_partial_offload():
    s = OllamaStatus(running=True, model_name="m", size_bytes=1000, size_vram_bytes=600)
    assert s.gpu_pct == 60.0
    assert s.cpu_pct == 40.0
    assert s.offloading is True


def test_percentages_zero_size():
    s = OllamaStatus(running=True, model_name="m", size_bytes=0, size_vram_bytes=0)
    assert s.gpu_pct == 0.0
    assert s.cpu_pct == 100.0


def test_percentages_clamped_when_vram_exceeds_size():
    s = OllamaStatus(running=True, model_name="m", size_bytes=1000, size_vram_bytes=1500)
    assert s.gpu_pct == 100.0
    assert s.cpu_pct == 0.0


def test_offloading_false_when_not_running():
    s = OllamaStatus(running=False, model_name=None, size_bytes=0, size_vram_bytes=0)
    assert s.offloading is False


def test_get_running_parses_first_model(monkeypatch):
    payload = {"models": [
        {"name": "llama3:8b", "size": 8_000_000_000, "size_vram": 8_000_000_000},
        {"name": "other", "size": 1, "size_vram": 1},
    ]}
    s = _client(monkeypatch, payload).get_running()
    assert s.running is True
    assert s.model_name == "llama3:8b"
    assert s.size_bytes == 8_000_000_000
    assert s.size_vram_bytes == 8_000_000_000


def test_get_running_falls_back_to_model_key(monkeypatch):
    # Some Ollama responses use "model" instead of "name".
    payload = {"models": [{"model": "qwen:7b", "size": 100, "size_vram": 50}]}
    assert _client(monkeypatch, payload).get_running().model_name == "qwen:7b"


def test_get_running_no_models_is_running_false(monkeypatch):
    s = _client(monkeypatch, {"models": []}).get_running()
    assert s.running is False
    assert s.model_name is None


def test_get_running_unreachable_returns_none(monkeypatch):
    assert _client(monkeypatch, exc=OSError("refused")).get_running() is None


def test_ping(monkeypatch):
    assert _client(monkeypatch, {"version": "0.1"}).ping() is True
    assert _client(monkeypatch, exc=OSError()).ping() is False
