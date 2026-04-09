import pytest
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock
from nmon.gpu.smi_source import SmiSource
from nmon.gpu.base import GPUSourceError
from nmon.models import GPUInfo, GPUSample

@pytest.fixture
def smi_source():
    return SmiSource()

def load_fixture(name: str) -> str:
    path = Path(__file__).parent / "fixtures" / name
    return path.read_text()

def test_is_available_true(smi_source):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        assert smi_source.is_available() is True

def test_is_available_false(smi_source):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1)
        assert smi_source.is_available() is False

def test_is_available_missing_binary(smi_source):
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = FileNotFoundError()
        assert smi_source.is_available() is False

def test_parse_1gpu(smi_source):
    xml_text = load_fixture("smi_1gpu.xml")
    samples = smi_source._parse_xml(xml_text)
    assert len(samples) == 1
    assert samples[0].gpu.index == 0
    assert samples[0].gpu.uuid == "GPU-00000000-0000-0000-0000-000000000000"
    assert samples[0].gpu.name == "NVIDIA GeForce RTX 4090"
    assert samples[0].temperature_c == 72.0
    assert samples[0].memory_used_mib == 4096.0
    assert samples[0].memory_total_mib == 24564.0
    assert samples[0].power_draw_w == 120.0

def test_parse_2gpus(smi_source):
    xml_text = load_fixture("smi_2gpu.xml")
    samples = smi_source._parse_xml(xml_text)
    assert len(samples) == 2
    assert samples[0].gpu.index == 0
    assert samples[1].gpu.index == 1

def test_parse_malformed_xml(smi_source):
    with pytest.raises(GPUSourceError):
        smi_source._parse_xml("<malformed>")

def test_subprocess_timeout(smi_source):
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired("nvidia-smi", 5)
        with pytest.raises(GPUSourceError):
            smi_source._run_smi(["--xml-format"])

def test_nonzero_exit_code(smi_source):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="error message")
        with pytest.raises(GPUSourceError):
            smi_source._run_smi(["--xml-format"])

def test_list_gpus(smi_source):
    xml_text = load_fixture("smi_1gpu.xml")
    with patch.object(smi_source, "_run_smi", return_value=xml_text):
        gpus = smi_source.list_gpus()
        assert len(gpus) == 1
        assert isinstance(gpus[0], GPUInfo)

def test_sample_all(smi_source):
    xml_text = load_fixture("smi_1gpu.xml")
    with patch.object(smi_source, "_run_smi", return_value=xml_text):
        samples = smi_source.sample_all()
        assert len(samples) == 1
        assert isinstance(samples[0], GPUSample)
