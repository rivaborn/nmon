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
JUNCTION_COLOR = "bright_red"

def format_time_window_tabs(current: int) -> str:
    parts = []
    for w in TIME_WINDOWS:
        parts.append(f"({w}hr)" if w == current else f" {w}hr ")
    return "  ".join(parts)

def format_collected_span(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m}m {s}s"

def build_history(
    storage: Storage,
    gpu_list: list[GPUInfo],
    metric: Literal["temp", "power", "memory"],
    time_window_hours: int,
    width: int = 80,
    height: int = 10,
    show_junction: bool = True,
):
    cfg = METRIC_CONFIG[metric]
    since = time.time() - time_window_hours * 3600
    groups = []
    all_timestamps: list[float] = []
    for gpu in gpu_list:
        rows = storage.get_history(gpu.index, cfg["column"], since)
        color = GPU_COLORS[gpu.index % len(GPU_COLORS)]
        series_list = [(rows, color)]
        all_timestamps.extend(r["timestamp"] for r in rows)
        if metric == "temp" and show_junction:
            jrows = storage.get_history(gpu.index, "memory_junction_temp_c", since)
            if jrows:
                series_list.append((jrows, JUNCTION_COLOR))
                all_timestamps.extend(r["timestamp"] for r in jrows)
        groups.append((series_list, gpu.name))
    chart = MultiSeriesChart(groups, width - 10, height, cfg["unit"],
                             format_time_window_tabs(time_window_hours))
    if all_timestamps:
        span = format_collected_span(max(all_timestamps) - min(all_timestamps))
    else:
        span = "0h 0m 0s"
    title = f"{cfg['label']} History ({cfg['unit']})"
    subtitle = f"{format_time_window_tabs(time_window_hours)}  collected: {span}"
    if metric == "temp" and show_junction and any(
        len(g[0]) > 1 for g in groups
    ):
        subtitle += "  (junction in red)"
    return Panel(chart, title=title, subtitle=subtitle)
