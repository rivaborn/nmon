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
            smi_source._run_smi(["-q", "-x"])

def test_nonzero_exit_code(smi_source):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="error message")
        with pytest.raises(GPUSourceError):
            smi_source._run_smi(["-q", "-x"])

def test_parse_na_minor_number_indexes_by_enumeration(smi_source):
    # Windows reports <minor_number>N/A</minor_number>; the index must come
    # from enumeration order, not that field.
    samples = smi_source._parse_xml(load_fixture("smi_2gpu.xml"))
    assert [s.gpu.index for s in samples] == [0, 1]

def test_parse_na_power_becomes_zero(smi_source):
    # The second GPU reports power_draw = N/A (common on laptop dGPUs).
    samples = smi_source._parse_xml(load_fixture("smi_2gpu.xml"))
    assert samples[1].gpu.name == "NVIDIA GeForce RTX 3080 Laptop GPU"
    assert samples[1].power_draw_w == 0.0

def test_parse_legacy_power_readings_element(smi_source):
    # Pre-535 drivers used <power_readings> instead of <gpu_power_readings>.
    xml = """<nvidia_smi_log><gpu>
        <uuid>GPU-legacy</uuid>
        <product_name>Legacy GPU</product_name>
        <temperature><gpu_temp>50 C</gpu_temp></temperature>
        <fb_memory_usage><used>1024 MiB</used><total>8192 MiB</total></fb_memory_usage>
        <power_readings><power_draw>75.5 W</power_draw></power_readings>
    </gpu></nvidia_smi_log>"""
    samples = smi_source._parse_xml(xml)
    assert len(samples) == 1
    assert samples[0].power_draw_w == 75.5
    assert samples[0].temperature_c == 50.0

def test_parse_prefers_instant_over_average_power(smi_source):
    # Latest drivers deprecated <power_draw> in favour of instant/average;
    # the instant reading is preferred (closest to NVML's live value).
    xml = """<nvidia_smi_log><gpu>
        <uuid>GPU-x</uuid><product_name>X</product_name>
        <temperature><gpu_temp>60 C</gpu_temp></temperature>
        <fb_memory_usage><used>1 MiB</used><total>2 MiB</total></fb_memory_usage>
        <gpu_power_readings>
            <average_power_draw>100.0 W</average_power_draw>
            <instant_power_draw>125.5 W</instant_power_draw>
        </gpu_power_readings>
    </gpu></nvidia_smi_log>"""
    assert smi_source._parse_xml(xml)[0].power_draw_w == 125.5

def test_parse_falls_back_to_average_power(smi_source):
    xml = """<nvidia_smi_log><gpu>
        <uuid>GPU-y</uuid><product_name>Y</product_name>
        <temperature><gpu_temp>60 C</gpu_temp></temperature>
        <fb_memory_usage><used>1 MiB</used><total>2 MiB</total></fb_memory_usage>
        <gpu_power_readings><average_power_draw>88.0 W</average_power_draw></gpu_power_readings>
    </gpu></nvidia_smi_log>"""
    assert smi_source._parse_xml(xml)[0].power_draw_w == 88.0

def test_parse_missing_fields_degrade_to_zero(smi_source):
    # A <gpu> with no temperature/memory/power elements still produces a
    # sample (with zeros) rather than crashing the whole parse.
    xml = """<nvidia_smi_log><gpu>
        <uuid>GPU-sparse</uuid>
        <product_name>Sparse GPU</product_name>
    </gpu></nvidia_smi_log>"""
    samples = smi_source._parse_xml(xml)
    assert len(samples) == 1
    assert samples[0].temperature_c == 0.0
    assert samples[0].memory_total_mib == 0.0
    assert samples[0].power_draw_w == 0.0

def test_sample_all_uses_q_x_command(smi_source):
    with patch.object(
        smi_source, "_run_smi", return_value=load_fixture("smi_1gpu.xml")
    ) as mock_run:
        smi_source.sample_all()
        mock_run.assert_called_once_with(["-q", "-x"])

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
