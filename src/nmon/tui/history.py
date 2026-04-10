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
HOTSPOT_COLOR = "bright_red"
JUNCTION_COLOR = "bright_magenta"
THRESHOLD_COLOR = "bright_white"

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
    show_hotspot: bool = True,
    show_junction: bool = True,
    temp_threshold_c: float | None = None,
    show_temp_threshold: bool = False,
):
    cfg = METRIC_CONFIG[metric]
    since = time.time() - time_window_hours * 3600
    groups = []
    all_timestamps: list[float] = []
    have_hotspot = False
    have_junction = False
    for gpu in gpu_list:
        rows = storage.get_history(gpu.index, cfg["column"], since)
        color = GPU_COLORS[gpu.index % len(GPU_COLORS)]
        series_list = [(rows, color)]
        all_timestamps.extend(r["timestamp"] for r in rows)
        if metric == "temp":
            if show_hotspot:
                hrows = storage.get_history(gpu.index, "hotspot_temp_c", since)
                if hrows:
                    series_list.append((hrows, HOTSPOT_COLOR))
                    all_timestamps.extend(r["timestamp"] for r in hrows)
                    have_hotspot = True
            if show_junction:
                jrows = storage.get_history(
                    gpu.index, "memory_junction_temp_c", since
                )
                if jrows:
                    series_list.append((jrows, JUNCTION_COLOR))
                    all_timestamps.extend(r["timestamp"] for r in jrows)
                    have_junction = True
        groups.append((series_list, gpu.name))

    threshold = (
        temp_threshold_c
        if metric == "temp" and show_temp_threshold and temp_threshold_c is not None
        else None
    )

    chart = MultiSeriesChart(
        groups, width - 10, height, cfg["unit"],
        format_time_window_tabs(time_window_hours),
        threshold=threshold,
        threshold_color=THRESHOLD_COLOR,
    )
    if all_timestamps:
        span = format_collected_span(max(all_timestamps) - min(all_timestamps))
    else:
        span = "0h 0m 0s"
    title = f"{cfg['label']} History ({cfg['unit']})"
    subtitle = f"{format_time_window_tabs(time_window_hours)}  span: {span}"
    if metric == "temp":
        legend_bits = []
        if have_hotspot:
            legend_bits.append("hot=red")
        if have_junction:
            legend_bits.append("jct=magenta")
        if threshold is not None:
            legend_bits.append(f"thr={threshold:.1f}C")
        if legend_bits:
            subtitle += "  " + " ".join(legend_bits)
    return Panel(chart, title=title, subtitle=subtitle)
