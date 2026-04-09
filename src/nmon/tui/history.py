import time
from typing import Literal
from rich.panel import Panel
from rich.text import Text
from nmon.models import GPUInfo
from nmon.storage import Storage
from nmon.tui.widgets import MultiSeriesChart

METRIC_CONFIG = {
    "temp":   {"column": "temperature_c",   "label": "Temperature", "unit": "°C"},
    "power":  {"column": "power_draw_w",    "label": "Power Draw",  "unit": "W"},
    "memory": {"column": "memory_used_mib", "label": "Memory Used", "unit": "MiB"},
}

TIME_WINDOWS = [1, 4, 12, 24]

GPU_COLORS = ["cyan", "magenta", "green", "yellow", "blue", "red"]

def format_time_window_tabs(current: int) -> str:
    parts = []
    for w in TIME_WINDOWS:
        # Use parentheses, not brackets — brackets are Rich markup and crash Panel
        parts.append(f"({w}hr)" if w == current else f" {w}hr ")
    return "  ".join(parts)

def build_history(
    storage: Storage,
    gpu_list: list[GPUInfo],
    metric: Literal["temp", "power", "memory"],
    time_window_hours: int,
    width: int = 80,
    height: int = 10,
):
    cfg = METRIC_CONFIG[metric]
    since = time.time() - time_window_hours * 3600
    series = []
    for gpu in gpu_list:
        rows = storage.get_history(gpu.index, cfg["column"], since)
        color = GPU_COLORS[gpu.index % len(GPU_COLORS)]
        series.append((rows, gpu.name, color))
    chart = MultiSeriesChart(series, width - 10, height, cfg["unit"],
                             format_time_window_tabs(time_window_hours))
    total_points = sum(len(s[0]) for s in series)
    title = f"{cfg['label']} History ({cfg['unit']})"
    subtitle = f"{format_time_window_tabs(time_window_hours)}  {total_points} pts"
    return Panel(chart, title=title, subtitle=subtitle)
