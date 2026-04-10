from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.console import Group
from nmon.models import GPUStats
from nmon.tui.widgets import MemoryBar

def _temp_style(temp: float) -> str:
    if temp < 60:
        return "green"
    if temp < 80:
        return "yellow"
    return "red"

def build_gpu_row(stats: GPUStats, bar_width: int = 20) -> list:
    s = stats.current
    return [
        stats.gpu.name,
        Text(f"{s.temperature_c:.0f}°C", style=_temp_style(s.temperature_c)),
        Text(f"{stats.max_temp_24h:.0f}°C", style=_temp_style(stats.max_temp_24h)),
        Text(f"{stats.avg_temp_1h:.0f}°C", style=_temp_style(stats.avg_temp_1h)),
        MemoryBar(s.memory_used_mib, s.memory_total_mib, bar_width),
        f"{s.power_draw_w:.1f} W",
    ]

def build_junction_row(stats: GPUStats) -> list:
    cur = stats.current.memory_junction_temp_c
    jmax = stats.junction_max_24h if stats.junction_max_24h is not None else cur
    javg = stats.junction_avg_1h if stats.junction_avg_1h is not None else cur
    return [
        stats.gpu.name,
        Text(f"{cur:.0f}°C", style=_temp_style(cur)),
        Text(f"{jmax:.0f}°C", style=_temp_style(jmax)),
        Text(f"{javg:.0f}°C", style=_temp_style(javg)),
    ]

def build_dashboard(
    stats: list[GPUStats], width: int = 80, show_junction: bool = True
):
    if not stats:
        return Panel("No GPU data yet.", title="nmon")
    table = Table(show_header=True, header_style="bold cyan", expand=True,
                  title="GPU Status", title_style="bold")
    table.add_column("GPU", no_wrap=True)
    table.add_column("Temp", justify="right")
    table.add_column("Max 24h", justify="right")
    table.add_column("Avg 1h", justify="right")
    table.add_column("Memory", min_width=30)
    table.add_column("Power", justify="right")
    for s in stats:
        table.add_row(*build_gpu_row(s))

    junction_stats = [
        s for s in stats if s.current.memory_junction_temp_c is not None
    ]
    if not show_junction or not junction_stats:
        return table

    jtable = Table(show_header=True, header_style="bold magenta", expand=True,
                   title="GPU Memory Junction Temperature",
                   title_style="bold magenta")
    jtable.add_column("GPU", no_wrap=True)
    jtable.add_column("Temp", justify="right")
    jtable.add_column("Max 24h", justify="right")
    jtable.add_column("Avg 1h", justify="right")
    for s in junction_stats:
        jtable.add_row(*build_junction_row(s))
    return Group(table, Text(""), jtable)
