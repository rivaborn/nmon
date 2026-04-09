import pytest
import time
from nmon.models import GPUInfo, GPUSample
from nmon.storage import Storage

def test_schema_creates_on_init(in_memory_storage):
    # Schema should be created during initialization
    # We can verify by trying to insert a sample
    sample = GPUSample(
        gpu=GPUInfo(index=0, uuid="test-uuid", name="test-gpu"),
        timestamp=time.time(),
        temperature_c=50.0,
        memory_used_mib=1024.0,
        memory_total_mib=8192.0,
        power_draw_w=100.0
    )
    in_memory_storage.insert_samples([sample])
    # If schema wasn't created, this would raise an error
    assert True

def test_insert_and_retrieve_single_sample(in_memory_storage, fake_sample):
    sample = fake_sample()
    in_memory_storage.insert_samples([sample])

    # Retrieve the sample
    history = in_memory_storage.get_history(
        gpu_index=sample.gpu.index,
        metric="temperature_c",
        since=0
    )
    assert len(history) == 1
    assert history[0]["timestamp"] == sample.timestamp
    assert history[0]["value"] == sample.temperature_c

def test_insert_multiple_gpus(in_memory_storage, fake_gpu_info, fake_sample):
    samples = [
        fake_sample(gpu=fake_gpu_info[0]),
        fake_sample(gpu=fake_gpu_info[1]),
    ]
    in_memory_storage.insert_samples(samples)

    # Verify both GPUs have their samples
    for gpu in fake_gpu_info:
        history = in_memory_storage.get_history(
            gpu_index=gpu.index,
            metric="temperature_c",
            since=0
        )
        assert len(history) == 1

def test_prune_removes_old_rows(in_memory_storage, fake_sample):
    now = time.time()
    # Insert samples with different timestamps
    samples = [
        fake_sample(timestamp=now - 3600),  # 1 hour old
        fake_sample(timestamp=now - 7200),  # 2 hours old
        fake_sample(timestamp=now - 10800), # 3 hours old
    ]
    in_memory_storage.insert_samples(samples)

    # Prune samples older than 2 hours
    count = in_memory_storage.prune_old(retention_hours=2)
    assert count == 2  # Should remove 2 samples

    # Verify only the newest sample remains
    history = in_memory_storage.get_history(
        gpu_index=samples[0].gpu.index,
        metric="temperature_c",
        since=0
    )
    assert len(history) == 1
    assert history[0]["timestamp"] == samples[0].timestamp

def test_prune_returns_count(in_memory_storage, fake_sample):
    now = time.time()
    samples = [
        fake_sample(timestamp=now - 3600),
        fake_sample(timestamp=now - 7200),
    ]
    in_memory_storage.insert_samples(samples)

    count = in_memory_storage.prune_old(retention_hours=1)
    assert count == 2

def test_get_current_stats_empty(in_memory_storage):
    stats = in_memory_storage.get_current_stats(gpu_index=0)
    assert stats is None

def test_get_current_stats_24h_max(in_memory_storage, fake_sample):
    now = time.time()
    samples = [
        fake_sample(timestamp=now - 86400, temp=60.0),  # 24 hours ago
        fake_sample(timestamp=now - 43200, temp=70.0),  # 12 hours ago
        fake_sample(timestamp=now - 3600, temp=80.0),   # 1 hour ago
    ]
    in_memory_storage.insert_samples(samples)

    max_temp, avg_temp = in_memory_storage.get_current_stats(gpu_index=0)
    assert max_temp == 80.0  # Should be the max from the last 24 hours

def test_get_current_stats_1h_avg(in_memory_storage, fake_sample):
    now = time.time()
    samples = [
        fake_sample(timestamp=now - 7200, temp=60.0),  # 2 hours ago
        fake_sample(timestamp=now - 3600, temp=70.0),  # 1 hour ago
        fake_sample(timestamp=now - 1800, temp=80.0),  # 30 minutes ago
    ]
    in_memory_storage.insert_samples(samples)

    max_temp, avg_temp = in_memory_storage.get_current_stats(gpu_index=0)
    assert abs(avg_temp - 75.0) < 0.01  # Should be avg of last hour (70 and 80)

def test_get_history_ordered_by_time(in_memory_storage, fake_sample):
    now = time.time()
    samples = [
        fake_sample(timestamp=now - 100),
        fake_sample(timestamp=now - 50),
        fake_sample(timestamp=now - 25),
    ]
    in_memory_storage.insert_samples(samples)

    history = in_memory_storage.get_history(
        gpu_index=0,
        metric="temperature_c",
        since=0
    )
    assert len(history) == 3
    assert history[0]["timestamp"] < history[1]["timestamp"] < history[2]["timestamp"]

def test_get_history_respects_since(in_memory_storage, fake_sample):
    now = time.time()
    samples = [
        fake_sample(timestamp=now - 100),
        fake_sample(timestamp=now - 50),
        fake_sample(timestamp=now - 25),
    ]
    in_memory_storage.insert_samples(samples)

    # Get history since 75 seconds ago (should only include the last sample)
    history = in_memory_storage.get_history(
        gpu_index=0,
        metric="temperature_c",
        since=now - 75
    )
    assert len(history) == 1
    assert history[0]["timestamp"] == samples[2].timestamp

def test_concurrent_read_write(in_memory_storage, fake_sample):
    import threading

    def writer():
        for i in range(100):
            sample = fake_sample(timestamp=time.time())
            in_memory_storage.insert_samples([sample])
            time.sleep(0.01)

    def reader():
        for i in range(100):
            history = in_memory_storage.get_history(
                gpu_index=0,
                metric="temperature_c",
                since=0
            )
            assert len(history) >= 0
            time.sleep(0.01)

    writer_thread = threading.Thread(target=writer)
    reader_thread = threading.Thread(target=reader)

    writer_thread.start()
    reader_thread.start()

    writer_thread.join()
    reader_thread.join()
