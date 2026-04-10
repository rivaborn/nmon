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
from nmon.state import state_path_for_db, load_state, save_state
from nmon.tui import dashboard, history
from nmon.tui.widgets import StatusBar

TABS = ["dashboard", "temp", "power", "memory"]

TEMP_THRESHOLD_MIN = 0.0
TEMP_THRESHOLD_MAX = 150.0
TEMP_THRESHOLD_STEP = 0.5

class NmonApp:
    def __init__(self, collector: Collector, storage: Storage, config: AppConfig):
        self._collector = collector
        self._storage = storage
        self._config = config
        self._tab = config.default_tab
        self._time_window = config.default_time_window_hours
        self._show_hotspot = True
        self._show_junction = True

        self._state_path = state_path_for_db(config.db_path)
        state = load_state(self._state_path, {
            "temp_threshold_c": config.default_temp_threshold_c,
            "show_temp_threshold": config.default_show_temp_threshold,
        })
        try:
            self._temp_threshold_c = float(state["temp_threshold_c"])
        except (TypeError, ValueError):
            self._temp_threshold_c = config.default_temp_threshold_c
        self._temp_threshold_c = max(
            TEMP_THRESHOLD_MIN,
            min(TEMP_THRESHOLD_MAX, self._temp_threshold_c),
        )
        self._show_temp_threshold = bool(state["show_temp_threshold"])

        self._quit = False
        self._lock = threading.Lock()
        self._redraw = threading.Event()

    def _persist_state(self) -> None:
        """Snapshot caller holds self._lock."""
        save_state(self._state_path, {
            "temp_threshold_c": self._temp_threshold_c,
            "show_temp_threshold": self._show_temp_threshold,
        })

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
            show_hotspot = self._show_hotspot
            show_junction = self._show_junction
            temp_threshold_c = self._temp_threshold_c
            show_temp_threshold = self._show_temp_threshold
        tabs_str = "  ".join(
            f"\\[{t.upper()}]" if t == tab else t.capitalize()
            for t in TABS
        )
        layout["header"].update(
            Text.from_markup(f" nmon  {tabs_str}", style="bold")
        )
        samples = self._collector.get_latest()
        if tab == "dashboard":
            if samples:
                stats = self._build_gpu_stats(samples)
                layout["body"].update(
                    dashboard.build_dashboard(
                        stats,
                        show_hotspot=show_hotspot,
                        show_junction=show_junction,
                    )
                )
            else:
                layout["body"].update(Panel("Waiting for data..."))
        else:
            gpu_list = [s.gpu for s in samples] if samples else []
            layout["body"].update(
                history.build_history(
                    self._storage, gpu_list, tab, window,
                    show_hotspot=show_hotspot,
                    show_junction=show_junction,
                    temp_threshold_c=temp_threshold_c,
                    show_temp_threshold=show_temp_threshold,
                )
            )
        interval = self._collector._interval
        layout["footer"].update(
            StatusBar(
                interval, tab, len(self._collector.warnings),
                show_hotspot=show_hotspot,
                show_junction=show_junction,
                temp_threshold_c=temp_threshold_c,
                show_temp_threshold=show_temp_threshold,
            )
        )
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

            changed = True
            persist = False
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
                elif key in ('h', 'H'):
                    self._show_hotspot = not self._show_hotspot
                elif key in ('j', 'J'):
                    self._show_junction = not self._show_junction
                elif key in ('t', 'T'):
                    self._show_temp_threshold = not self._show_temp_threshold
                    persist = True
                elif key == '\xe0H' and self._tab == "temp":   # up arrow
                    self._temp_threshold_c = min(
                        TEMP_THRESHOLD_MAX,
                        round(self._temp_threshold_c + TEMP_THRESHOLD_STEP, 1),
                    )
                    persist = True
                elif key == '\xe0P' and self._tab == "temp":   # down arrow
                    self._temp_threshold_c = max(
                        TEMP_THRESHOLD_MIN,
                        round(self._temp_threshold_c - TEMP_THRESHOLD_STEP, 1),
                    )
                    persist = True
                else:
                    changed = False
                if persist:
                    self._persist_state()
            if changed:
                self._redraw.set()

    def _build_gpu_stats(self, samples) -> list[GPUStats]:
        stats = []
        for sample in samples:
            result = self._storage.get_current_stats(sample.gpu.index)
            if result:
                max_temp, avg_temp, hmax, havg, jmax, javg = result
            else:
                max_temp = avg_temp = sample.temperature_c
                hmax = havg = sample.hotspot_temp_c
                jmax = javg = sample.memory_junction_temp_c
            stats.append(GPUStats(
                gpu=sample.gpu,
                current=sample,
                max_temp_24h=max_temp,
                avg_temp_1h=avg_temp,
                hotspot_max_24h=hmax,
                hotspot_avg_1h=havg,
                junction_max_24h=jmax,
                junction_avg_1h=javg,
            ))
        return stats
