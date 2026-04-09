import pytest
from io import StringIO
from rich.console import Console
from nmon.tui.widgets import MemoryBar, BrailleChart, MultiSeriesChart, StatusBar
from nmon.models import HistoryRow

def test_memory_bar():
    """Test MemoryBar widget rendering"""
    widget = MemoryBar(used=4096.0, total=24564.0, width=20)
    console = Console(file=StringIO(), width=80)
    with console.capture() as cap:
        console.print(widget)
    output = cap.get()

    # Check for memory values
    assert "4096/24564 MiB" in output
    # Check for percentage (should be around 16.67%)
    assert "17%" in output or "16%" in output
    # Check for bar characters
    assert "█" in output
    assert "░" in output

def test_memory_bar_zero_total():
    """Test MemoryBar with zero total memory (edge case)"""
    widget = MemoryBar(used=0.0, total=0.0, width=20)
    console = Console(file=StringIO(), width=80)
    with console.capture() as cap:
        console.print(widget)
    output = cap.get()

    # Should show 0/0 and 0%
    assert "0/0 MiB" in output
    assert "0%" in output

def test_braille_chart():
    """Test BrailleChart widget rendering"""
    data = [
        {"timestamp": 1.0, "value": 10.0},
        {"timestamp": 2.0, "value": 20.0},
        {"timestamp": 3.0, "value": 30.0},
        {"timestamp": 4.0, "value": 40.0},
        {"timestamp": 5.0, "value": 50.0},
    ]
    widget = BrailleChart(data, width=10, height=5, label="Temp", color="red", y_label="°C")
    console = Console(file=StringIO(), width=80)
    with console.capture() as cap:
        console.print(widget)
    output = cap.get()

    # Check for axis labels (high, mid, low)
    assert "50" in output  # High value
    assert "10" in output  # Low value
    # Check for braille characters
    assert "│" in output  # Axis line
    assert "─" in output  # Footer line
    # Check for color indicator in output
    assert "red" in output.lower()

def test_braille_chart_empty_data():
    """Test BrailleChart with empty data"""
    widget = BrailleChart([], width=10, height=5, label="Temp", color="red", y_label="°C")
    console = Console(file=StringIO(), width=80)
    with console.capture() as cap:
        console.print(widget)
    output = cap.get()

    # Should still render axis with 0 values
    assert "0" in output
    assert "│" in output

def test_multi_series_chart():
    """Test MultiSeriesChart with multiple data series"""
    temp_data = [
        {"timestamp": 1.0, "value": 50.0},
        {"timestamp": 2.0, "value": 55.0},
        {"timestamp": 3.0, "value": 60.0},
    ]
    power_data = [
        {"timestamp": 1.0, "value": 100.0},
        {"timestamp": 2.0, "value": 110.0},
        {"timestamp": 3.0, "value": 120.0},
    ]
    widget = MultiSeriesChart(
        series=[
            (temp_data, "Temperature", "red"),
            (power_data, "Power", "yellow"),
        ],
        width=10,
        height=5,
        y_label="Units",
        time_window_label="1h"
    )
    console = Console(file=StringIO(), width=80)
    with console.capture() as cap:
        console.print(widget)
    output = cap.get()

    # Check for both series labels
    assert "Temperature" in output
    assert "Power" in output
    # Check for colors
    assert "red" in output.lower()
    assert "yellow" in output.lower()
    # Check for axis elements
    assert "│" in output

def test_status_bar():
    """Test StatusBar widget rendering"""
    widget = StatusBar(interval=5, tab="1", error_count=2)
    console = Console(file=StringIO(), width=80)
    with console.capture() as cap:
        console.print(widget)
    output = cap.get()

    # Check for interval
    assert "Interval: 5s" in output
    # Check for tab information
    assert "1:Dashboard" in output
    # Check for error warning
    assert "⚠ 2 warning(s)" in output
    # Check for control hints
    assert "+/-: Interval" in output
    assert "[/]: Window" in output
    assert "q: Quit" in output

def test_status_bar_no_errors():
    """Test StatusBar with no errors"""
    widget = StatusBar(interval=10, tab="2", error_count=0)
    console = Console(file=StringIO(), width=80)
    with console.capture() as cap:
        console.print(widget)
    output = cap.get()

    # Should not show error warning
    assert "⚠" not in output
    # Should show interval and tab
    assert "Interval: 10s" in output
    assert "2:Temp" in output
