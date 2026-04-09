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
    def __init__(self, data: list[HistoryRow], width: int, height: int,
                 label: str, color: str, y_label: str):
        self.data = data
        self.width = width
        self.height = height
        self.label = label
        self.color = color
        self.y_label = y_label

    def _normalize(self, values: list[float]) -> list[float]:
        if not values:
            return []
        lo, hi = min(values), max(values)
        rng = hi - lo or 1
        return [(v - lo) / rng * (self.height * 4 - 1) for v in values]

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        values = [r["value"] for r in self.data]
        norm = self._normalize(values)
        # build character grid: height rows x width cols
        grid = [[0] * self.width for _ in range(self.height)]
        if norm:
            n = len(norm)
            for col in range(min(self.width, n)):
                # Map each column to an evenly-spaced index across all data points
                # so the full time window is always represented, not just the first N.
                idx = col * (n - 1) // (self.width - 1) if self.width > 1 else 0
                val = norm[idx]
                row_idx = self.height - 1 - int(val // 4)
                dot_row = int(val % 4)
                if 0 <= row_idx < self.height:
                    grid[row_idx][col] |= BRAILLE[dot_row][0]
        lo = min(values) if values else 0
        hi = max(values) if values else 0
        mid = (lo + hi) / 2
        axis_labels = {0: f"{hi:.0f}", self.height // 2: f"{mid:.0f}", self.height - 1: f"{lo:.0f}"}
        for r in range(self.height):
            line = Text()
            ax_label = axis_labels.get(r, "")
            line.append(f"{ax_label:>4} │", style="dim")
            for col in range(self.width):
                ch = chr(0x2800 | grid[r][col]) if grid[r][col] else " "
                line.append(ch, style=self.color)
            yield line
        footer = Text()
        footer.append("     └" + "─" * self.width, style="dim")
        yield footer

class MultiSeriesChart:
    def __init__(self, series: list[tuple[list[HistoryRow], str, str]],
                 width: int, height: int, y_label: str, time_window_label: str):
        self.series = series
        self.width = width
        self.height = height
        self.y_label = y_label
        self.time_window_label = time_window_label

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        for data, label, color in self.series:
            chart = BrailleChart(data, self.width, self.height, label, color, self.y_label)
            yield Text(f"  {label}", style=color)
            yield from chart.__rich_console__(console, options)

class StatusBar:
    def __init__(self, interval: int, tab: str, error_count: int):
        self.interval = interval
        self.tab = tab
        self.error_count = error_count

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        t = Text()
        t.append(f" Interval: {self.interval}s", style="bold")
        t.append("  │  ", style="dim")
        t.append("1:Dashboard  2:Temp  3:Power  4:Memory", style="dim")
        t.append("  │  ", style="dim")
        t.append("+/-: Interval  [/]: Window  q: Quit", style="dim")
        if self.error_count:
            t.append(f"  │  ⚠ {self.error_count} warning(s)", style="yellow")
        yield t
