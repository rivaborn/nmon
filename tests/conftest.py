import pytest
import time
import sys
from unittest.mock import MagicMock
from nmon.models import GPUInfo, GPUSample
from nmon.storage import Storage

@pytest.fixture
def in_memory_storage():
    s = Storage(":memory:")
    yield s
    s.close()

@pytest.fixture
def fake_gpu_info():
    return [
        GPUInfo(index=0, uuid="GPU-0000", name="RTX 4090"),
        GPUInfo(index=1, uuid="GPU-1111", name="RTX 3080"),
    ]

@pytest.fixture
def fake_sample(fake_gpu_info):
    def _make(gpu=None, timestamp=None, temp=72.0, mem_used=4096.0,
               mem_total=24564.0, power=120.0):
        return GPUSample(
            gpu=gpu or fake_gpu_info[0],
            timestamp=timestamp or time.time(),
            temperature_c=temp,
            memory_used_mib=mem_used,
            memory_total_mib=mem_total,
            power_draw_w=power,
        )
    return _make

@pytest.fixture
def fake_samples_batch(fake_gpu_info, fake_sample):
    now = time.time()
    return [fake_sample(timestamp=now - (2*3600 - i*720)) for i in range(10)]

@pytest.fixture
def mock_pynvml(monkeypatch):
    mock = MagicMock()
    monkeypatch.setitem(sys.modules, "pynvml", mock)
    return mock
