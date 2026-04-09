import pytest
from io import StringIO
from rich.console import Console
from nmon.tui.dashboard import build_dashboard
from nmon.models import GPUInfo, GPUStats, GPUSample

def test_empty_stats_list():
    """Test that empty stats list produces 'No GPU data yet.' message."""
    console = Console(file=StringIO(), force_terminal=True)
    dashboard = build_dashboard([])
    console.print(dashboard)
    output = console.file.getvalue()
    assert "No GPU data yet." in output

def test_single_gpu_values_appear():
    """Test that single GPU values appear correctly in output."""
    gpu = GPUInfo(index=0, uuid="test-uuid", name="Test GPU")
    sample = GPUSample(
        gpu=gpu,
        timestamp=1234567890.0,
        temperature_c=75.0,
        memory_used_mib=4096.0,
        memory_total_mib=16384.0,
        power_draw_w=150.0
    )
    stats = GPUStats(
        gpu=gpu,
        current=sample,
        max_temp_24h=80.0,
        avg_temp_1h=70.0
    )
    console = Console(file=StringIO(), force_terminal=True)
    dashboard = build_dashboard([stats])
    console.print(dashboard)
    output = console.file.getvalue()
    assert "Test GPU" in output
    assert "75°C" in output
    assert "80°C" in output
    assert "70°C" in output
    assert "150.0 W" in output

def test_temperature_color_styles():
    """Test temperature color styles for green/yellow/red thresholds."""
    gpu = GPUInfo(index=0, uuid="test-uuid", name="Test GPU")
    console = Console(file=StringIO(), force_terminal=True)

    # Test green (< 60°C)
    sample_green = GPUSample(
        gpu=gpu,
        timestamp=1234567890.0,
        temperature_c=55.0,
        memory_used_mib=4096.0,
        memory_total_mib=16384.0,
        power_draw_w=150.0
    )
    stats_green = GPUStats(
        gpu=gpu,
        current=sample_green,
        max_temp_24h=58.0,
        avg_temp_1h=56.0
    )
    dashboard_green = build_dashboard([stats_green])
    console.print(dashboard_green)
    output_green = console.file.getvalue()
    assert "55°C" in output_green
    assert "58°C" in output_green
    assert "56°C" in output_green

    # Test yellow (60°C <= temp < 80°C)
    sample_yellow = GPUSample(
        gpu=gpu,
        timestamp=1234567890.0,
        temperature_c=70.0,
        memory_used_mib=4096.0,
        memory_total_mib=16384.0,
        power_draw_w=150.0
    )
    stats_yellow = GPUStats(
        gpu=gpu,
        current=sample_yellow,
        max_temp_24h=75.0,
        avg_temp_1h=65.0
    )
    dashboard_yellow = build_dashboard([stats_yellow])
    console.print(dashboard_yellow)
    output_yellow = console.file.getvalue()
    assert "70°C" in output_yellow
    assert "75°C" in output_yellow
    assert "65°C" in output_yellow

    # Test red (>= 80°C)
    sample_red = GPUSample(
        gpu=gpu,
        timestamp=1234567890.0,
        temperature_c=85.0,
        memory_used_mib=4096.0,
        memory_total_mib=16384.0,
        power_draw_w=150.0
    )
    stats_red = GPUStats(
        gpu=gpu,
        current=sample_red,
        max_temp_24h=90.0,
        avg_temp_1h=82.0
    )
    dashboard_red = build_dashboard([stats_red])
    console.print(dashboard_red)
    output_red = console.file.getvalue()
    assert "85°C" in output_red
    assert "90°C" in output_red
    assert "82°C" in output_red
