import msvcrt
import time
import threading
import traceback
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text
from nmon.collector import Collector
from nmon.storage import Storage
from nmon.models import AppConfig, GPUStats
from nmon.tui import dashboard, history
from nmon.tui.widgets import StatusBar

TABS = ["dashboard", "temp", "power", "memory"]

class NmonApp:
    def __init__(self, collector: Collector, storage: Storage, config: AppConfig):
        self._collector = collector
        self._storage = storage
        self._config = config
        self._tab = config.default_tab
        self._time_window = config.default_time_window_hours
        self._quit = False
        self._lock = threading.Lock()
        self._redraw = threading.Event()
        self._last_key = "none"   # debug: last raw key received

    def run(self) -> None:
        self._collector.start()
        key_thread = threading.Thread(target=self._handle_keys, daemon=True)
        key_thread.start()
        # auto_refresh=False: we drive every frame ourselves so render
        # exceptions surface here rather than dying silently in a background thread.
        with Live(self._render(), screen=True, auto_refresh=False) as live:
            live.refresh()
            while not self._quit:
                self._redraw.wait(timeout=max(0.5, self._config.interval_seconds / 2))
                self._redraw.clear()
                try:
                    live.update(self._render())
                    live.refresh()
                except Exception as e:
                    with open("nmon_debug.log", "a") as f:
                        f.write(f"\nRENDER ERROR: {e}\n{traceback.format_exc()}\n")
                    err = Text("Render error: ", style="red bold")
                    err.append(str(e), style="white")
                    live.update(Panel(err, title="nmon"))
                    live.refresh()

    def _render(self):
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=1),
            Layout(name="body"),
            Layout(name="footer", size=1),
        )
        with self._lock:
            tab = self._tab
            window = self._time_window
        tabs_str = "  ".join(
            f"\\[{t.upper()}]" if t == tab else t.capitalize()
            for t in TABS
        )
        layout["header"].update(
            Text.from_markup(f" nmon  {tabs_str}   key={self._last_key} tab={self._tab}", style="bold")
        )
        samples = self._collector.get_latest()
        if tab == "dashboard":
            if samples:
                stats = self._build_gpu_stats(samples)
                layout["body"].update(dashboard.build_dashboard(stats))
            else:
                layout["body"].update(Panel("Waiting for data..."))
        else:
            gpu_list = [s.gpu for s in samples] if samples else []
            layout["body"].update(
                history.build_history(self._storage, gpu_list, tab, window)
            )
        interval = self._collector._interval
        layout["footer"].update(StatusBar(interval, tab, len(self._collector.warnings)))
        return layout

    def _handle_keys(self) -> None:
        from nmon.tui.history import TIME_WINDOWS
        while not self._quit:
            if not msvcrt.kbhit():
                time.sleep(0.05)
                continue
            ch = msvcrt.getwch()
            # Arrow keys and other special keys send a two-byte sequence:
            # first byte is \x00 or \xe0, second byte identifies the key.
            if ch in ('\x00', '\xe0'):
                ch2 = msvcrt.getwch()
                key = '\xe0' + ch2  # e.g. '\xe0K' = left arrow, '\xe0M' = right
            else:
                key = ch

            # Record for debug display and log file
            self._last_key = repr(key)
            with open("nmon_debug.log", "a") as f:
                f.write(f"key={repr(key)}  tab={self._tab}\n")

            changed = True
            with self._lock:
                if key in ('q', '\x03'):          # q or Ctrl+C
                    self._quit = True
                elif key in ('1', '2', '3', '4'):
                    self._tab = TABS[int(key) - 1]
                elif key in ('[', '\xe0K'):        # [ or left arrow
                    idx = TIME_WINDOWS.index(self._time_window)
                    self._time_window = TIME_WINDOWS[max(0, idx - 1)]
                elif key in (']', '\xe0M'):        # ] or right arrow
                    idx = TIME_WINDOWS.index(self._time_window)
                    self._time_window = TIME_WINDOWS[min(len(TIME_WINDOWS) - 1, idx + 1)]
                elif key == '+':
                    self._collector.set_interval(self._collector._interval + 1)
                elif key == '-':
                    self._collector.set_interval(self._collector._interval - 1)
                else:
                    changed = False
            if changed:
                self._redraw.set()

    def _build_gpu_stats(self, samples) -> list[GPUStats]:
        stats = []
        for sample in samples:
            result = self._storage.get_current_stats(sample.gpu.index)
            if result:
                max_temp, avg_temp = result
            else:
                max_temp = avg_temp = sample.temperature_c
            stats.append(GPUStats(
                gpu=sample.gpu,
                current=sample,
                max_temp_24h=max_temp,
                avg_temp_1h=avg_temp,
            ))
        return stats
