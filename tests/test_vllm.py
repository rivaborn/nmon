import pytest
from nmon.vllm import VLLMClient, VLLMStatus, _is_vllm_model


def _client(monkeypatch, payload=None, exc=None):
    """A VLLMClient whose _get returns `payload` (or raises `exc`)."""
    c = VLLMClient("http://test:8000")

    def fake_get(path):
        if exc is not None:
            raise exc
        return payload

    monkeypatch.setattr(c, "_get", fake_get)
    return c


def test_is_vllm_model():
    assert _is_vllm_model({"owned_by": "vllm"})
    assert _is_vllm_model({"owned_by": "VLLM"})         # case-insensitive
    assert _is_vllm_model({})                           # missing field -> lenient
    assert _is_vllm_model({"owned_by": ""})             # blank -> lenient
    assert not _is_vllm_model({"owned_by": "library"})  # Ollama
    assert not _is_vllm_model({"owned_by": "openai"})


def test_get_running_accepts_vllm(monkeypatch):
    payload = {"data": [{"id": "gemma-4-26b", "owned_by": "vllm"}]}
    c = _client(monkeypatch, payload)
    assert c.get_running() == VLLMStatus(running=True, model_name="gemma-4-26b")
    assert c.ping() is True


def test_get_running_rejects_non_vllm_server(monkeypatch):
    # Ollama also answers /v1/models but tags its models owned_by="library".
    payload = {"data": [{"id": "qwen3:27b", "owned_by": "library"}]}
    c = _client(monkeypatch, payload)
    assert c.get_running() is None  # treated as "no vLLM server here"
    assert c.ping() is False


def test_get_running_accepts_model_without_owner(monkeypatch):
    payload = {"data": [{"id": "some-model"}]}  # no owned_by field
    c = _client(monkeypatch, payload)
    assert c.get_running() == VLLMStatus(running=True, model_name="some-model")


def test_get_running_empty_models_is_running_false(monkeypatch):
    c = _client(monkeypatch, {"data": []})
    assert c.get_running() == VLLMStatus(running=False, model_name=None)
    assert c.ping() is True  # an empty but real vLLM is still a vLLM server


def test_get_running_unreachable_returns_none(monkeypatch):
    c = _client(monkeypatch, exc=OSError("connection refused"))
    assert c.get_running() is None
    assert c.ping() is False
