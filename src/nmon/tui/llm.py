"""LLM Server history tab — GPU% and CPU% usage over time.

The charts are built from the ``ollama_samples`` table populated by
the collector every sampling tick while a model is loaded. Uses the
same time-window controls (1/4/12/24 h) as the other history tabs.
"""

import time
from rich.console import Group
from rich.panel import Panel
from rich.text import Text
from nmon.storage import Storage
from nmon.tui.history import (
    TIME_WINDOWS,
    format_collected_span,
    format_time_window_tabs,
)
from nmon.tui.widgets import MultiSeriesChart

GPU_COLOR = "green"
CPU_COLOR = "red"

def build_llm_history(
    storage: Storage,
    time_window_hours: int,
    width: int = 80,
    height: int = 8,
) -> Panel:
    since = time.time() - time_window_hours * 3600
    gpu_rows = storage.get_ollama_history("gpu_pct", since)
    cpu_rows = storage.get_ollama_history("cpu_pct", since)

    all_timestamps: list[float] = []
    all_timestamps.extend(r["timestamp"] for r in gpu_rows)
    all_timestamps.extend(r["timestamp"] for r in cpu_rows)

    combined = (
        [(gpu_rows, GPU_COLOR), (cpu_rows, CPU_COLOR)],
        "GPU Use vs CPU Use",
    )

    chart = MultiSeriesChart(
        [combined],
        width - 10, height * 2, "%",
        format_time_window_tabs(time_window_hours),
    )

    if all_timestamps:
        span = format_collected_span(max(all_timestamps) - min(all_timestamps))
    else:
        span = "0h 0m 0s"

    if not gpu_rows and not cpu_rows:
        body = Group(
            Text(
                "No Ollama samples collected in the selected window.\n"
                "Load a model on the Ollama server to start recording.",
                style="dim",
            ),
            Text(""),
            chart,
        )
    else:
        body = chart

    subtitle = (
        f"{format_time_window_tabs(time_window_hours)}  "
        f"span: {span}  gpu=green cpu=red"
    )
    return Panel(
        body,
        title="LLM Server History (GPU% / CPU%)",
        subtitle=subtitle,
    )
