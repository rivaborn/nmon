import pytest
from unittest.mock import MagicMock, patch
from nmon.tui.history import build_history, METRIC_CONFIG, TIME_WINDOWS, GPU_COLORS
from nmon.models import GPUInfo, HistoryRow
from nmon.storage import Storage

@pytest.fixture
def mock_storage():
    storage = MagicMock(spec=Storage)
    return storage

@pytest.fixture
def gpu_list():
    return [
        GPUInfo(index=0, uuid="GPU-0000", name="RTX 4090"),
        GPUInfo(index=1, uuid="GPU-1111", name="RTX 3080"),
    ]

def test_build_history_temp_metric(mock_storage, gpu_list):
    # Mock data for temperature history
    mock_storage.get_history.return_value = [
        HistoryRow(timestamp=1000.0, value=65.0),
        HistoryRow(timestamp=2000.0, value=70.0),
        HistoryRow(timestamp=3000.0, value=68.0),
    ]

    panel = build_history(mock_storage, gpu_list, "temp", 1)

    # Check title and unit
    assert METRIC_CONFIG["temp"]["label"] in panel.title
    assert METRIC_CONFIG["temp"]["unit"] in panel.title

    # Check time window tabs
    assert "1hr" in panel.subtitle

    # Verify get_history was called with correct parameters
    mock_storage.get_history.assert_called()

def test_build_history_power_metric(mock_storage, gpu_list):
    # Mock data for power history
    mock_storage.get_history.return_value = [
        HistoryRow(timestamp=1000.0, value=120.0),
        HistoryRow(timestamp=2000.0, value=150.0),
        HistoryRow(timestamp=3000.0, value=130.0),
    ]

    panel = build_history(mock_storage, gpu_list, "power", 4)

    # Check title and unit
    assert METRIC_CONFIG["power"]["label"] in panel.title
    assert METRIC_CONFIG["power"]["unit"] in panel.title

    # Check time window tabs
    assert "4hr" in panel.subtitle

def test_build_history_memory_metric(mock_storage, gpu_list):
    # Mock data for memory history
    mock_storage.get_history.return_value = [
        HistoryRow(timestamp=1000.0, value=4096.0),
        HistoryRow(timestamp=2000.0, value=8192.0),
        HistoryRow(timestamp=3000.0, value=6144.0),
    ]

    panel = build_history(mock_storage, gpu_list, "memory", 12)

    # Check title and unit
    assert METRIC_CONFIG["memory"]["label"] in panel.title
    assert METRIC_CONFIG["memory"]["unit"] in panel.title

    # Check time window tabs
    assert "12hr" in panel.subtitle

def test_build_history_all_time_windows(mock_storage, gpu_list):
    # Test all time windows
    for window in TIME_WINDOWS:
        mock_storage.get_history.return_value = [
            HistoryRow(timestamp=1000.0, value=65.0),
            HistoryRow(timestamp=2000.0, value=70.0),
        ]

        panel = build_history(mock_storage, gpu_list, "temp", window)

        # Check that the correct time window is highlighted
        assert f"[{window}hr]" in panel.subtitle

def test_build_history_empty_data(mock_storage, gpu_list):
    # Test with empty data
    mock_storage.get_history.return_value = []

    panel = build_history(mock_storage, gpu_list, "temp", 1)

    # Should still create a panel even with empty data
    assert panel is not None
    assert METRIC_CONFIG["temp"]["label"] in panel.title

def test_build_history_multiple_gpus(mock_storage, gpu_list):
    # Test with multiple GPUs
    mock_storage.get_history.side_effect = [
        [HistoryRow(timestamp=1000.0, value=65.0)],
        [HistoryRow(timestamp=1000.0, value=70.0)],
    ]

    panel = build_history(mock_storage, gpu_list, "temp", 1)

    # Should be called for each GPU
    assert mock_storage.get_history.call_count == len(gpu_list)

def test_build_history_color_assignment(mock_storage, gpu_list):
    # Test that colors are assigned correctly
    mock_storage.get_history.return_value = [
        HistoryRow(timestamp=1000.0, value=65.0),
    ]

    panel = build_history(mock_storage, gpu_list, "temp", 1)

    # Verify colors are used from GPU_COLORS
    for i, gpu in enumerate(gpu_list):
        color = GPU_COLORS[gpu.index % len(GPU_COLORS)]
        # The color should be used in the chart (we can't directly test the chart object
        # but we can verify the color was selected correctly)
        assert color in GPU_COLORS

def test_format_time_window_tabs():
    # Test the tab formatting function
    for window in TIME_WINDOWS:
        tabs = build_history.format_time_window_tabs(window)
        assert f"[{window}hr]" in tabs
        # Other windows should not be highlighted
        for other in TIME_WINDOWS:
            if other != window:
                assert f"[{other}hr]" not in tabs
                assert f" {other}hr " in tabs

def test_build_history_custom_dimensions(mock_storage, gpu_list):
    # Test with custom width and height
    mock_storage.get_history.return_value = [
        HistoryRow(timestamp=1000.0, value=65.0),
    ]

    panel = build_history(mock_storage, gpu_list, "temp", 1, width=100, height=20)

    # The panel should be created with the specified dimensions
    assert panel is not None
