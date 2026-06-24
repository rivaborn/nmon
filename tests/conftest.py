import pytest
import time
from unittest.mock import MagicMock
from nmon.models import GPUInfo, GPUSample
from nmon.storage import Storage
import nmon.gpu.nvml_source as _nvml_source
import nmon.gpu.nvapi as _nvapi

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
    """Replace the pynvml reference used by NvmlSource with a mock.

    nvml_source binds ``pynvml`` at import time, so patching sys.modules is
    too late — we patch the module attribute directly. ``NVMLError`` must be
    a real exception subclass so the ``except pynvml.NVMLError`` clauses
    behave. ``read_thermal_channels`` is stubbed so ``sample_all()`` never
    reaches out to real NVAPI hardware during unit tests.
    """
    mock = MagicMock()
    mock.NVMLError = type("NVMLError", (Exception,), {})
    monkeypatch.setattr(_nvml_source, "pynvml", mock)
    monkeypatch.setattr(_nvapi, "read_thermal_channels", lambda index: {})
    return mock
