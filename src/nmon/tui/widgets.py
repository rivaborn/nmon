from rich.console import Console, ConsoleOptions, RenderResult
from rich.text import Text
from rich.style import Style
from nmon.models import HistoryRow

BRAILLE = [
    [0x01, 0x08], [0x02, 0x10], [0x04, 0x20], [0x40, 0x80]
]  # row 0=top, col 0=left

class MemoryBar:
    def __init__(self, used: float, total: float, width: int = 20):
        self.used = used
        self.total = total
        self.width = width

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        frac = (self.used / self.total) if self.total > 0 else 0.0
        filled = round(frac * self.width)
        bar = "█" * filled + "░" * (self.width - filled)
        pct = round(frac * 100)
        t = Text()
        t.append(f"{int(self.used)}/{int(self.total)} MiB ")
        t.append(f"[{bar}]", style="cyan")
        t.append(f" {pct}%")
        yield t

class BrailleChart:
    """Renders one or more time series as a Braille-dot chart.

    `series` is a list of (data, color) tuples that are overlaid on a shared
    axis. When cells from multiple series land on the same column, the series
    drawn last wins for that cell.

    `threshold`, when given, draws a horizontal line across the chart at
    that Y value. The Y range is expanded to include the threshold so
    the line is always visible. Data dots win on cells where they
    collide with the threshold line.
    """
    def __init__(self, series: list[tuple[list[HistoryRow], str]],
                 width: int, height: int, y_label: str,
                 threshold: float | None = None,
                 threshold_color: str = "bright_white"):
        self.series = series
        self.width = width
        self.height = height
        self.y_label = y_label
        self.threshold = threshold
        self.threshold_color = threshold_color

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        all_values = [r["value"] for data, _ in self.series for r in data]
        if all_values:
            lo, hi = min(all_values), max(all_values)
        else:
            lo, hi = 0.0, 0.0
        if self.threshold is not None:
            lo = min(lo, self.threshold)
            hi = max(hi, self.threshold)
        rng = (hi - lo) or 1.0

        grids: list[tuple[list[list[int]], str]] = []
        for data, color in self.series:
            grid = [[0] * self.width for _ in range(self.height)]
            values = [r["value"] for r in data]
            n = len(values)
            if n:
                for col in range(self.width):
                    idx = col * (n - 1) // (self.width - 1) if self.width > 1 else 0
                    v = values[idx]
                    norm = (v - lo) / rng * (self.height * 4 - 1)
                    row_idx = self.height - 1 - int(norm // 4)
                    dot_row = int(norm % 4)
                    if 0 <= row_idx < self.height:
                        grid[row_idx][col] |= BRAILLE[dot_row][0]
            grids.append((grid, color))

        threshold_row_idx: int | None = None
        threshold_mask = 0
        if self.threshold is not None:
            norm = (self.threshold - lo) / rng * (self.height * 4 - 1)
            threshold_row_idx = self.height - 1 - int(norm // 4)
            dot_row = int(norm % 4)
            threshold_mask = BRAILLE[dot_row][0] | BRAILLE[dot_row][1]

        mid = (lo + hi) / 2
        axis_labels = {
            0: f"{hi:.0f}",
            self.height // 2: f"{mid:.0f}",
            self.height - 1: f"{lo:.0f}",
        }
        for r in range(self.height):
            line = Text()
            ax_label = axis_labels.get(r, "")
            line.append(f"{ax_label:>4} │", style="dim")
            for col in range(self.width):
                data_mask = 0
                data_color = None
                for grid, color in grids:
                    if grid[r][col]:
                        data_mask = grid[r][col]
                        data_color = color
                is_threshold_row = (r == threshold_row_idx)
                if data_color:
                    if is_threshold_row:
                        line.append(
                            chr(0x2800 | data_mask | threshold_mask),
                            style=data_color,
                        )
                    else:
                        line.append(chr(0x2800 | data_mask), style=data_color)
                elif is_threshold_row:
                    line.append(
                        chr(0x2800 | threshold_mask),
                        style=self.threshold_color,
                    )
                else:
                    line.append(" ")
            yield line
        footer = Text()
        footer.append("     └" + "─" * self.width, style="dim")
        yield footer

class MultiSeriesChart:
    """Stacks one BrailleChart per group. Each group may contain multiple
    overlaid series (e.g. core + hotspot + memory junction temperature
    for one GPU). An optional horizontal threshold line is drawn on
    every sub-chart at the same Y value.
    """
    def __init__(self,
                 groups: list[tuple[list[tuple[list[HistoryRow], str]], str]],
                 width: int, height: int, y_label: str, time_window_label: str,
                 threshold: float | None = None,
                 threshold_color: str = "bright_white"):
        self.groups = groups
        self.width = width
        self.height = height
        self.y_label = y_label
        self.time_window_label = time_window_label
        self.threshold = threshold
        self.threshold_color = threshold_color

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        for series_list, label in self.groups:
            primary_color = series_list[0][1] if series_list else "white"
            yield Text(f"  {label}", style=primary_color)
            chart = BrailleChart(
                series_list, self.width, self.height, self.y_label,
                threshold=self.threshold,
                threshold_color=self.threshold_color,
            )
            yield from chart.__rich_console__(console, options)

class StatusBar:
    def __init__(self, interval: int, tab: str, error_count: int,
                 show_hotspot: bool = True, show_junction: bool = True,
                 temp_threshold_c: float | None = None,
                 show_temp_threshold: bool = False):
        self.interval = interval
        self.tab = tab
        self.error_count = error_count
        self.show_hotspot = show_hotspot
        self.show_junction = show_junction
        self.temp_threshold_c = temp_threshold_c
        self.show_temp_threshold = show_temp_threshold

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        t = Text()
        t.append(f" {self.interval}s", style="bold")
        t.append("  │  ", style="dim")
        t.append("1:Dash 2:Temp 3:Pwr 4:Mem 5:LLM", style="dim")
        t.append("  │  ", style="dim")
        hstate = "on" if self.show_hotspot else "off"
        jstate = "on" if self.show_junction else "off"
        t.append(
            f"+/-:Int  [/]:Win  h:Hot({hstate})  j:Jct({jstate})",
            style="dim",
        )
        if self.tab == "temp":
            thr_state = "on" if self.show_temp_threshold else "off"
            thr_val = (
                f"{self.temp_threshold_c:.1f}C"
                if self.temp_threshold_c is not None else "?"
            )
            t.append(
                f"  t:Thr({thr_state},{thr_val})  Up/Dn:+/-0.5",
                style="dim",
            )
        t.append("  q:Quit", style="dim")
        if self.error_count:
            t.append(f"  │  ⚠ {self.error_count} warning(s)", style="yellow")
        yield t
