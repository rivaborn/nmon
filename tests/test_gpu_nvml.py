import pytest
from unittest.mock import MagicMock
from nmon.gpu.nvml_source import NvmlSource
from nmon.gpu.base import GPUSourceError

def test_is_available_true(mock_pynvml):
    mock_pynvml.nvmlInit.return_value = None
    mock_pynvml.nvmlShutdown.return_value = None
    source = NvmlSource()
    assert source.is_available() is True

def test_is_available_false(mock_pynvml):
    mock_pynvml.nvmlInit.side_effect = Exception("Init failed")
    source = NvmlSource()
    assert source.is_available() is False

def test_list_gpus_1_gpu(mock_pynvml, fake_gpu_info):
    mock_pynvml.nvmlInit.return_value = None
    mock_pynvml.nvmlShutdown.return_value = None
    mock_pynvml.nvmlDeviceGetCount.return_value = 1
    mock_pynvml.nvmlDeviceGetHandleByIndex.return_value = MagicMock()
    mock_pynvml.nvmlDeviceGetUUID.return_value = fake_gpu_info[0].uuid
    mock_pynvml.nvmlDeviceGetName.return_value = fake_gpu_info[0].name
    source = NvmlSource()
    gpus = source.list_gpus()
    assert len(gpus) == 1
    assert gpus[0].index == 0
    assert gpus[0].uuid == fake_gpu_info[0].uuid
    assert gpus[0].name == fake_gpu_info[0].name

def test_list_gpus_2_gpus(mock_pynvml, fake_gpu_info):
    mock_pynvml.nvmlInit.return_value = None
    mock_pynvml.nvmlShutdown.return_value = None
    mock_pynvml.nvmlDeviceGetCount.return_value = 2
    mock_pynvml.nvmlDeviceGetHandleByIndex.side_effect = [
        MagicMock(), MagicMock()
    ]
    mock_pynvml.nvmlDeviceGetUUID.side_effect = [
        fake_gpu_info[0].uuid, fake_gpu_info[1].uuid
    ]
    mock_pynvml.nvmlDeviceGetName.side_effect = [
        fake_gpu_info[0].name, fake_gpu_info[1].name
    ]
    source = NvmlSource()
    gpus = source.list_gpus()
    assert len(gpus) == 2
    assert gpus[0].index == 0
    assert gpus[0].uuid == fake_gpu_info[0].uuid
    assert gpus[0].name == fake_gpu_info[0].name
    assert gpus[1].index == 1
    assert gpus[1].uuid == fake_gpu_info[1].uuid
    assert gpus[1].name == fake_gpu_info[1].name

def test_sample_all_value_extraction(mock_pynvml, fake_gpu_info):
    mock_pynvml.nvmlInit.return_value = None
    mock_pynvml.nvmlShutdown.return_value = None
    mock_pynvml.nvmlDeviceGetCount.return_value = 1
    mock_pynvml.nvmlDeviceGetHandleByIndex.return_value = MagicMock()
    mock_pynvml.nvmlDeviceGetUUID.return_value = fake_gpu_info[0].uuid
    mock_pynvml.nvmlDeviceGetName.return_value = fake_gpu_info[0].name
    mock_pynvml.nvmlDeviceGetTemperature.return_value = 72.0
    mock_pynvml.nvmlDeviceGetMemoryInfo.return_value = MagicMock(
        used=4096 * 1024 * 1024,
        total=24564 * 1024 * 1024
    )
    mock_pynvml.nvmlDeviceGetPowerUsage.return_value = 120000.0
    source = NvmlSource()
    samples = source.sample_all()
    assert len(samples) == 1
    assert samples[0].gpu.index == 0
    assert samples[0].gpu.uuid == fake_gpu_info[0].uuid
    assert samples[0].gpu.name == fake_gpu_info[0].name
    assert samples[0].temperature_c == 72.0
    assert samples[0].memory_used_mib == 4096.0
    assert samples[0].memory_total_mib == 24564.0
    assert samples[0].power_draw_w == 120.0

def test_nvmlerror_wrapped_as_gpusourceerror(mock_pynvml):
    mock_pynvml.nvmlInit.return_value = None
    mock_pynvml.nvmlShutdown.return_value = None
    mock_pynvml.nvmlDeviceGetCount.side_effect = Exception("NVMLError")
    source = NvmlSource()
    with pytest.raises(GPUSourceError):
        source.sample_all()

def test_close_calls_nvmlshutdown_once(mock_pynvml):
    mock_pynvml.nvmlInit.return_value = None
    mock_pynvml.nvmlShutdown.return_value = None
    source = NvmlSource()
    source.close()
    assert mock_pynvml.nvmlShutdown.call_count == 1

def test_close_is_idempotent(mock_pynvml):
    mock_pynvml.nvmlInit.return_value = None
    mock_pynvml.nvmlShutdown.return_value = None
    source = NvmlSource()
    source.close()
    source.close()
    assert mock_pynvml.nvmlShutdown.call_count == 1
