import pytest
import time
from unittest.mock import MagicMock, patch
from nmon.collector import Collector
from nmon.models import AppConfig, GPUInfo, GPUSample
from nmon.gpu.base import GPUSource, GPUSourceError
from nmon.storage import Storage, StorageError

@pytest.fixture
def collector_fixture():
    source = MagicMock(spec=GPUSource)
    storage = MagicMock(spec=Storage)
    config = AppConfig(
        interval_seconds=2,
        min_interval=1,
        max_interval=60,
        db_path="test.db",
        retention_hours=24,
        default_tab="dashboard",
        default_time_window_hours=1,
    )
    collector = Collector(source, storage, config)
    collector.start()
    yield collector
    collector.stop()

def test_start_stop_thread_lifecycle(collector_fixture):
    assert collector_fixture._thread is not None
    assert collector_fixture._thread.is_alive()

def test_get_latest_before_first_sample(collector_fixture):
    assert collector_fixture.get_latest() is None

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
    time.sleep(0.1)  # Allow one iteration
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

def test_gpu_count_change_adds_to_collector_warnings(collector_fixture):
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
    collector_fixture._source.sample_all.return_value = [sample1]
    time.sleep(0.1)  # Allow one iteration
    collector_fixture._source.sample_all.return_value = [sample1, sample2]
    time.sleep(0.1)  # Allow one iteration
    assert len(collector_fixture.warnings) == 1
    assert "GPU count changed" in collector_fixture.warnings[0]
