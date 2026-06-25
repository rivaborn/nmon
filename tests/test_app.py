import pytest
from unittest.mock import MagicMock
import nmon.tui.app as appmod
from nmon.tui.app import (
    NmonApp, OFFLOAD_BANNER_HOLD_SECONDS, TEMP_THRESHOLD_MAX, TEMP_THRESHOLD_MIN,
)
from nmon.models import AppConfig, OllamaSample
from nmon.collector import Collector
from nmon.storage import Storage


@pytest.fixture
def app(tmp_path):
    config = AppConfig(
        interval_seconds=2, min_interval=1, max_interval=60,
        db_path=str(tmp_path / "nmon.db"), retention_hours=24,
        default_tab="dashboard", default_time_window_hours=1,
        default_temp_threshold_c=95.0, default_show_temp_threshold=True,
    )
    return NmonApp(MagicMock(spec=Collector), MagicMock(spec=Storage), config)


def _ollama(gpu_pct, running=True):
    return OllamaSample(
        timestamp=0.0, running=running, model_name="m",
        size_bytes=100, size_vram_bytes=int(gpu_pct),
        gpu_pct=float(gpu_pct), cpu_pct=float(100 - gpu_pct),
    )


def _freeze_time(monkeypatch, holder):
    monkeypatch.setattr(appmod.time, "monotonic", lambda: holder["now"])


def test_banner_shows_on_offload_and_holds(app, monkeypatch):
    t = {"now": 100.0}
    _freeze_time(monkeypatch, t)

    # Offloading at 70% GPU → banner shows, peak = 30.
    assert app._update_offload_banner(_ollama(70)) is True
    assert app._offload_peak_pct == 30.0

    # A fully-resident sample within the hold window keeps the banner up and
    # does not downgrade the peak.
    t["now"] = 100.0 + OFFLOAD_BANNER_HOLD_SECONDS / 2
    assert app._update_offload_banner(_ollama(100)) is True
    assert app._offload_peak_pct == 30.0

    # Past the hold window the banner clears and the peak resets.
    t["now"] = 100.0 + OFFLOAD_BANNER_HOLD_SECONDS + 1
    assert app._update_offload_banner(_ollama(100)) is False
    assert app._offload_peak_pct == 0.0


def test_banner_tracks_worst_peak_in_window(app, monkeypatch):
    _freeze_time(monkeypatch, {"now": 50.0})
    app._update_offload_banner(_ollama(90))   # 10% offload
    app._update_offload_banner(_ollama(40))   # 60% offload
    assert app._offload_peak_pct == 60.0


def test_banner_hidden_without_ollama(app, monkeypatch):
    _freeze_time(monkeypatch, {"now": 10.0})
    assert app._update_offload_banner(None) is False


def test_banner_not_shown_when_fully_resident(app, monkeypatch):
    _freeze_time(monkeypatch, {"now": 10.0})
    assert app._update_offload_banner(_ollama(100)) is False


def test_nudge_threshold_steps(app):
    app._temp_threshold_c = 90.0
    app._nudge_threshold(1)
    assert app._temp_threshold_c == 90.5
    app._nudge_threshold(-1)
    assert app._temp_threshold_c == 90.0


def test_nudge_threshold_clamps_to_range(app):
    app._temp_threshold_c = TEMP_THRESHOLD_MAX
    app._nudge_threshold(1)
    assert app._temp_threshold_c == TEMP_THRESHOLD_MAX

    app._temp_threshold_c = TEMP_THRESHOLD_MIN
    app._nudge_threshold(-1)
    assert app._temp_threshold_c == TEMP_THRESHOLD_MIN
