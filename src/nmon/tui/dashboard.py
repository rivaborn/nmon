from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.console import Group
from nmon.models import GPUStats, OllamaSample
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

def _build_extra_temp_table(
    stats: list[GPUStats],
    title: str,
    header_style: str,
    current_attr: str,
    max_attr: str,
    avg_attr: str,
) -> Table:
    """Build a three-column temperature table (current / Max 24h / Avg 1h)
    for either the hotspot or memory junction section. Only the GPUs
    with a non-None current value are included."""
    table = Table(
        show_header=True, header_style=header_style, expand=True,
        title=title, title_style=header_style,
    )
    table.add_column("GPU", no_wrap=True)
    table.add_column("Temp", justify="right")
    table.add_column("Max 24h", justify="right")
    table.add_column("Avg 1h", justify="right")
    for s in stats:
        cur = getattr(s.current, current_attr)
        if cur is None:
            continue
        smax = getattr(s, max_attr)
        savg = getattr(s, avg_attr)
        smax = smax if smax is not None else cur
        savg = savg if savg is not None else cur
        table.add_row(
            s.gpu.name,
            Text(f"{cur:.0f}°C", style=_temp_style(cur)),
            Text(f"{smax:.0f}°C", style=_temp_style(smax)),
            Text(f"{savg:.0f}°C", style=_temp_style(savg)),
        )
    return table

def _format_size_bytes(n: int) -> str:
    if n <= 0:
        return "—"
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    f = float(n)
    i = 0
    while f >= 1024 and i < len(units) - 1:
        f /= 1024
        i += 1
    return f"{f:.2f} {units[i]}"

def build_ollama_table(sample: OllamaSample) -> Table:
    """Ollama Server section. Called from build_dashboard when an
    Ollama server is detected. GPU/CPU percentages are colored green
    when the model lives entirely in VRAM and red when any part has
    spilled over to system RAM (GPU offloading)."""
    table = Table(
        show_header=True, header_style="bold cyan", expand=True,
        title="Ollama Server", title_style="bold cyan",
    )
    table.add_column("Model", no_wrap=True)
    table.add_column("Size", justify="right")
    table.add_column("GPU %", justify="right")
    table.add_column("CPU %", justify="right")
    if not sample.running:
        table.add_row(
            Text("(no model loaded)", style="dim"),
            "—", "—", "—",
        )
        return table
    offloading = sample.gpu_pct < 100.0
    pct_style = "red" if offloading else "green"
    table.add_row(
        sample.model_name or "(unknown)",
        _format_size_bytes(sample.size_bytes),
        Text(f"{sample.gpu_pct:.0f}%", style=pct_style),
        Text(f"{sample.cpu_pct:.0f}%", style=pct_style),
    )
    return table

def build_dashboard(
    stats: list[GPUStats],
    width: int = 80,
    show_hotspot: bool = True,
    show_junction: bool = True,
    ollama: OllamaSample | None = None,
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

    sections = [table]

    if show_hotspot and any(
        s.current.hotspot_temp_c is not None for s in stats
    ):
        sections.append(Text(""))
        sections.append(_build_extra_temp_table(
            stats,
            title="GPU Hotspot Temperature",
            header_style="bold red",
            current_attr="hotspot_temp_c",
            max_attr="hotspot_max_24h",
            avg_attr="hotspot_avg_1h",
        ))

    if show_junction and any(
        s.current.memory_junction_temp_c is not None for s in stats
    ):
        sections.append(Text(""))
        sections.append(_build_extra_temp_table(
            stats,
            title="GPU Memory Junction Temperature",
            header_style="bold magenta",
            current_attr="memory_junction_temp_c",
            max_attr="junction_max_24h",
            avg_attr="junction_avg_1h",
        ))

    if ollama is not None:
        sections.append(Text(""))
        sections.append(build_ollama_table(ollama))

    if len(sections) == 1:
        return table
    return Group(*sections)
