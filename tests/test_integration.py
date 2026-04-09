import pytest
import time
from unittest.mock import MagicMock
from nmon.collector import Collector
from nmon.models import AppConfig, GPUInfo, GPUSample
from nmon.storage import Storage

@pytest.fixture
def mock_gpu_source():
    source = MagicMock()
    gpus = [
        GPUInfo(index=0, uuid="GPU-0000", name="RTX 4090"),
        GPUInfo(index=1, uuid="GPU-1111", name="RTX 3080"),
    ]
    source.list_gpus.return_value = gpus

    # Create deterministic samples
    samples = [
        GPUSample(
            gpu=gpus[0],
            timestamp=1000.0,
            temperature_c=70.0,
            memory_used_mib=2048.0,
            memory_total_mib=24564.0,
            power_draw_w=120.0
        ),
        GPUSample(
            gpu=gpus[1],
            timestamp=1000.0,
            temperature_c=65.0,
            memory_used_mib=1024.0,
            memory_total_mib=12288.0,
            power_draw_w=90.0
        )
    ]
    source.sample_all.return_value = samples
    return source

@pytest.fixture
def test_config():
    return AppConfig(
        interval_seconds=1,
        min_interval=1,
        max_interval=60,
        db_path=":memory:",
        retention_hours=1,
        default_tab="dashboard",
        default_time_window_hours=1
    )

def test_sample_stored_and_retrievable(in_memory_storage, mock_gpu_source, test_config):
    # Track how many times sample_all is called
    call_count = {"count": 0}
    original_sample_all = mock_gpu_source.sample_all

    def counting_sample_all():
        call_count["count"] += 1
        return original_sample_all()

    mock_gpu_source.sample_all = counting_sample_all

    # Create collector and run for exactly 3 cycles
    collector = Collector(mock_gpu_source, in_memory_storage, test_config)
    collector.start()

    # Wait for 3 cycles to complete
    while call_count["count"] < 3:
        time.sleep(0.1)

    collector.stop()

    # Verify we got exactly 3 samples
    assert call_count["count"] == 3

    # Test that samples are stored and retrievable
    history = in_memory_storage.get_history(0, "temperature_c", 0)
    assert len(history) == 3
    assert history[0]["value"] == 70.0
    assert history[1]["value"] == 70.0
    assert history[2]["value"] == 70.0
    assert history[0]["timestamp"] == 1000.0
    assert history[1]["timestamp"] > history[0]["timestamp"]
    assert history[2]["timestamp"] > history[1]["timestamp"]

def test_pruning_removes_old_data(in_memory_storage, mock_gpu_source, test_config):
    # Insert some old samples first
    old_samples = [
        GPUSample(
            gpu=GPUInfo(index=0, uuid="GPU-0000", name="RTX 4090"),
            timestamp=time.time() - 3600 * 2,  # 2 hours old
            temperature_c=50.0,
            memory_used_mib=1024.0,
            memory_total_mib=24564.0,
            power_draw_w=80.0
        )
    ]
    in_memory_storage.insert_samples(old_samples)

    # Run collector for 3 cycles with new samples
    call_count = {"count": 0}
    original_sample_all = mock_gpu_source.sample_all

    def counting_sample_all():
        call_count["count"] += 1
        return original_sample_all()

    mock_gpu_source.sample_all = counting_sample_all

    collector = Collector(mock_gpu_source, in_memory_storage, test_config)
    collector.start()

    while call_count["count"] < 3:
        time.sleep(0.1)

    collector.stop()

    # Verify pruning removed old data
    all_history = in_memory_storage.get_history(0, "temperature_c", 0)
    # Should only have the 3 new samples, not the old one
    assert len(all_history) == 3
    assert all(h["timestamp"] > time.time() - 3600 for h in all_history)

def test_multi_gpu_isolation(in_memory_storage, mock_gpu_source, test_config):
    # Run collector for 3 cycles
    call_count = {"count": 0}
    original_sample_all = mock_gpu_source.sample_all

    def counting_sample_all():
        call_count["count"] += 1
        return original_sample_all()

    mock_gpu_source.sample_all = counting_sample_all

    collector = Collector(mock_gpu_source, in_memory_storage, test_config)
    collector.start()

    while call_count["count"] < 3:
        time.sleep(0.1)

    collector.stop()

    # Verify GPU 0 history contains only GPU 0 samples
    gpu0_history = in_memory_storage.get_history(0, "temperature_c", 0)
    assert len(gpu0_history) == 3
    assert all(h["value"] == 70.0 for h in gpu0_history)

    # Verify GPU 1 history contains only GPU 1 samples
    gpu1_history = in_memory_storage.get_history(1, "temperature_c", 0)
    assert len(gpu1_history) == 3
    assert all(h["value"] == 65.0 for h in gpu1_history)

    # Verify no cross-contamination
    assert all(h["value"] != 65.0 for h in gpu0_history)
    assert all(h["value"] != 70.0 for h in gpu1_history)
