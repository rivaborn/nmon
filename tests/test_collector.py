import pytest
import time
from unittest.mock import MagicMock, patch
from nmon.collector import Collector
from nmon.models import AppConfig, GPUInfo, GPUSample
from nmon.gpu.base import GPUSource, GPUSourceError
from nmon.storage import Storage, StorageError

def _wait_until(predicate, timeout=2.0, step=0.01):
    """Poll predicate() until truthy or the timeout elapses.

    The collector samples on a background thread, so tests can't assume a
    given sample has landed after a fixed sleep — they wait for it instead.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return bool(predicate())


@pytest.fixture
def collector_components():
    """An unstarted (source, storage, config) trio for building a Collector.

    ``sample_all`` returns a real empty list by default so the first tick
    stores a list rather than an unconfigured MagicMock. The interval is tiny
    so the background loop re-ticks quickly and waits stay short.
    """
    source = MagicMock(spec=GPUSource)
    source.sample_all.return_value = []
    storage = MagicMock(spec=Storage)
    config = AppConfig(
        interval_seconds=0.02,
        min_interval=1,
        max_interval=60,
        db_path="test.db",
        retention_hours=24,
        default_tab="dashboard",
        default_time_window_hours=1,
    )
    return source, storage, config


@pytest.fixture
def collector_fixture(collector_components):
    source, storage, config = collector_components
    collector = Collector(source, storage, config)
    collector.start()
    yield collector
    collector.stop()

def test_start_stop_thread_lifecycle(collector_fixture):
    assert collector_fixture._thread is not None
    assert collector_fixture._thread.is_alive()

def test_get_latest_before_first_sample(collector_components):
    # A Collector that has never ticked exposes no samples yet.
    source, storage, config = collector_components
    collector = Collector(source, storage, config)
    assert collector.get_latest() is None

def test_get_latest_after_first_sample(collector_fixture):
    gpu = GPUInfo(index=0, uuid="GPU-0000", name="RTX 4090")
    sample = GPUSample(
        gpu=gpu,
        timestamp=time.time(),
        temperature_c=72.0,
        memory_used_mib=4096.0,
        memory_total_mib=24564.0,
        power_draw_w=120.0,
    )
    collector_fixture._source.sample_all.return_value = [sample]
    assert _wait_until(lambda: collector_fixture.get_latest() == [sample])
    latest = collector_fixture.get_latest()
    assert latest is not None
    assert len(latest) == 1
    assert latest[0].gpu.index == 0

def test_gpu_source_error_does_not_crash_loop(collector_fixture):
    collector_fixture._source.sample_all.side_effect = GPUSourceError("Test error")
    time.sleep(0.1)  # Allow one iteration
    assert collector_fixture._thread.is_alive()

def test_storage_error_does_not_crash_loop(collector_fixture):
    collector_fixture._storage.insert_samples.side_effect = StorageError("Test error")
    time.sleep(0.1)  # Allow one iteration
    assert collector_fixture._thread.is_alive()

def test_set_interval_clamps_to_min_and_max(collector_fixture):
    collector_fixture.set_interval(0)  # Below min
    assert collector_fixture._interval == 1
    collector_fixture.set_interval(100)  # Above max
    assert collector_fixture._interval == 60

def test_gpu_count_change_adds_to_collector_warnings(collector_components):
    source, storage, config = collector_components
    gpu1 = GPUInfo(index=0, uuid="GPU-0000", name="RTX 4090")
    gpu2 = GPUInfo(index=1, uuid="GPU-1111", name="RTX 3080")
    sample1 = GPUSample(
        gpu=gpu1,
        timestamp=time.time(),
        temperature_c=72.0,
        memory_used_mib=4096.0,
        memory_total_mib=24564.0,
        power_draw_w=120.0,
    )
    sample2 = GPUSample(
        gpu=gpu2,
        timestamp=time.time(),
        temperature_c=72.0,
        memory_used_mib=4096.0,
        memory_total_mib=24564.0,
        power_draw_w=120.0,
    )
    # First observed count is 1 (no warning); adding a second GPU mid-run
    # triggers exactly one count-change warning.
    source.sample_all.return_value = [sample1]
    collector = Collector(source, storage, config)
    collector.start()
    try:
        assert _wait_until(lambda: collector._last_gpu_count == 1)
        source.sample_all.return_value = [sample1, sample2]
        assert _wait_until(lambda: len(collector.warnings) >= 1)
    finally:
        collector.stop()
    assert len(collector.warnings) == 1
    assert "GPU count changed" in collector.warnings[0]
