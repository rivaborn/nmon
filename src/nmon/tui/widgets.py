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
    """
    def __init__(self, series: list[tuple[list[HistoryRow], str]],
                 width: int, height: int, y_label: str):
        self.series = series
        self.width = width
        self.height = height
        self.y_label = y_label

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        all_values = [r["value"] for data, _ in self.series for r in data]
        if all_values:
            lo, hi = min(all_values), max(all_values)
        else:
            lo, hi = 0.0, 0.0
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
                cell_char = " "
                cell_color = None
                for grid, color in grids:
                    if grid[r][col]:
                        cell_char = chr(0x2800 | grid[r][col])
                        cell_color = color
                if cell_color:
                    line.append(cell_char, style=cell_color)
                else:
                    line.append(" ")
            yield line
        footer = Text()
        footer.append("     └" + "─" * self.width, style="dim")
        yield footer

class MultiSeriesChart:
    """Stacks one BrailleChart per group. Each group may contain multiple
    overlaid series (e.g. core + memory junction temperature for one GPU).
    """
    def __init__(self,
                 groups: list[tuple[list[tuple[list[HistoryRow], str]], str]],
                 width: int, height: int, y_label: str, time_window_label: str):
        self.groups = groups
        self.width = width
        self.height = height
        self.y_label = y_label
        self.time_window_label = time_window_label

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        for series_list, label in self.groups:
            primary_color = series_list[0][1] if series_list else "white"
            yield Text(f"  {label}", style=primary_color)
            chart = BrailleChart(series_list, self.width, self.height, self.y_label)
            yield from chart.__rich_console__(console, options)

class StatusBar:
    def __init__(self, interval: int, tab: str, error_count: int,
                 show_junction: bool = True):
        self.interval = interval
        self.tab = tab
        self.error_count = error_count
        self.show_junction = show_junction

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        t = Text()
        t.append(f" Interval: {self.interval}s", style="bold")
        t.append("  │  ", style="dim")
        t.append("1:Dashboard  2:Temp  3:Power  4:Memory", style="dim")
        t.append("  │  ", style="dim")
        jstate = "on" if self.show_junction else "off"
        t.append(f"+/-: Interval  [/]: Window  j: Junction ({jstate})  q: Quit",
                 style="dim")
        if self.error_count:
            t.append(f"  │  ⚠ {self.error_count} warning(s)", style="yellow")
        yield t
