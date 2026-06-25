try:
    import msvcrt
except ImportError:  # non-Windows: the interactive TUI can't take keyboard
    msvcrt = None    # input, but the module still imports for tests/portability.
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
from nmon.tui import dashboard, history, llm
from nmon.tui.widgets import StatusBar

TABS = ["dashboard", "temp", "power", "memory", "llm"]
OFFLOAD_BANNER_HOLD_SECONDS = 1.0
OFFLOAD_HEAVY_PCT = 5.0

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
        # Monotonic deadline: banner stays visible until this time.
        # Bumped whenever we observe offloading, held for at least
        # OFFLOAD_BANNER_HOLD_SECONDS so it never flickers at fast sample rates.
        self._offload_until: float = 0.0
        # Peak offload percentage observed during the current banner
        # session. Drives the orange→red color switch so a tick with no
        # fresh Ollama sample doesn't downgrade the warning color.
        self._offload_peak_pct: float = 0.0

    def _persist_state(self) -> None:
        """Write the runtime state (threshold value/visibility) to disk. Called
        from the key thread without the lock held — only that thread mutates
        these values, so the write needs no lock and can run off the hot path."""
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
                # Cap the wait whenever the offload banner is up so it
                # disappears promptly once the hold window elapses,
                # even on long sampling intervals.
                timeout = max(0.5, self._config.interval_seconds / 2)
                remaining = self._offload_until - time.monotonic()
                if remaining > 0:
                    timeout = min(timeout, max(0.1, remaining))
                self._redraw.wait(timeout=timeout)
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
        with self._lock:
            tab = self._tab
            window = self._time_window
            show_hotspot = self._show_hotspot
            show_junction = self._show_junction
            temp_threshold_c = self._temp_threshold_c
            show_temp_threshold = self._show_temp_threshold

        # Staleness guard: if the collector hasn't refreshed an LLM sample
        # in 2× the current sampling interval, treat it as missing rather
        # than rendering frozen state. Without this, a poll thread that
        # stops updating a specific sample (without crashing the GPU
        # path) leaves a stale "model loaded" row on screen — observed
        # with Ollama where the dashboard kept showing an unloaded model.
        stale_after = max(5.0, 2.0 * self._collector.get_interval())
        now_wall = time.time()
        ollama_sample = self._collector.get_latest_ollama()
        if ollama_sample is not None and (now_wall - ollama_sample.timestamp) > stale_after:
            ollama_sample = None
        vllm_sample = self._collector.get_latest_vllm()
        if vllm_sample is not None and (now_wall - vllm_sample.timestamp) > stale_after:
            vllm_sample = None

        show_banner = self._update_offload_banner(ollama_sample)

        layout = Layout()
        if show_banner:
            layout.split_column(
                Layout(name="banner", size=1),
                Layout(name="header", size=1),
                Layout(name="body"),
                Layout(name="footer", size=1),
            )
            heavy = self._offload_peak_pct > OFFLOAD_HEAVY_PCT
            banner_style = "white on red" if heavy else "black on dark_orange"
            banner = Text(
                " ⚠  GPU OFFLOADING — Ollama model is partially in CPU/system RAM ",
                style=banner_style,
                justify="center",
            )
            layout["banner"].update(banner)
        else:
            layout.split_column(
                Layout(name="header", size=1),
                Layout(name="body"),
                Layout(name="footer", size=1),
            )

        def _tab_label(t: str) -> str:
            return "LLM" if t == "llm" else t.capitalize()
        tabs_str = "  ".join(
            f"\\[{t.upper()}]" if t == tab else _tab_label(t)
            for t in TABS
        )
        layout["header"].update(
            Text.from_markup(f" nmon  {tabs_str}", style="bold")
        )
        samples = self._collector.get_latest()
        # If the collector hasn't refreshed GPU samples within the staleness
        # window (e.g. sampling has been failing), flag it so the dashboard and
        # status bar don't present frozen readings as if they were live.
        gpu_stale_age = None
        if samples and (now_wall - samples[0].timestamp) > stale_after:
            gpu_stale_age = now_wall - samples[0].timestamp
        if tab == "dashboard":
            if samples:
                stats = self._build_gpu_stats(samples)
                layout["body"].update(
                    dashboard.build_dashboard(
                        stats,
                        show_hotspot=show_hotspot,
                        show_junction=show_junction,
                        ollama=ollama_sample,
                        vllm=vllm_sample,
                        stale_age=gpu_stale_age,
                    )
                )
            else:
                layout["body"].update(Panel("Waiting for data..."))
        elif tab == "llm":
            layout["body"].update(
                llm.build_llm_history(self._storage, window)
            )
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
        interval = self._collector.get_interval()
        layout["footer"].update(
            StatusBar(
                interval, tab, self._collector.warning_count(),
                show_hotspot=show_hotspot,
                show_junction=show_junction,
                temp_threshold_c=temp_threshold_c,
                show_temp_threshold=show_temp_threshold,
                gpu_stale=gpu_stale_age is not None,
            )
        )
        return layout

    def _handle_keys(self) -> None:
        if msvcrt is None:
            return  # keyboard input needs Windows; elsewhere the TUI is read-only
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
                if key in ('q', '\x03', '\x11'):   # q, Ctrl+C, Ctrl+Q
                    self._quit = True
                elif key in ('1', '2', '3', '4', '5'):
                    idx = int(key) - 1
                    if idx < len(TABS):
                        self._tab = TABS[idx]
                elif key in ('[', '\xe0K'):        # [ or left arrow
                    idx = TIME_WINDOWS.index(self._time_window)
                    self._time_window = TIME_WINDOWS[max(0, idx - 1)]
                elif key in (']', '\xe0M'):        # ] or right arrow
                    idx = TIME_WINDOWS.index(self._time_window)
                    self._time_window = TIME_WINDOWS[min(len(TIME_WINDOWS) - 1, idx + 1)]
                elif key == '+':
                    self._collector.set_interval(self._collector.get_interval() + 1)
                elif key == '-':
                    self._collector.set_interval(self._collector.get_interval() - 1)
                elif key in ('h', 'H'):
                    self._show_hotspot = not self._show_hotspot
                elif key in ('j', 'J'):
                    self._show_junction = not self._show_junction
                elif key in ('t', 'T'):
                    self._show_temp_threshold = not self._show_temp_threshold
                    persist = True
                elif key == '\xe0H' and self._tab == "temp":   # up arrow
                    self._nudge_threshold(1)
                    persist = True
                elif key == '\xe0P' and self._tab == "temp":   # down arrow
                    self._nudge_threshold(-1)
                    persist = True
                else:
                    changed = False
            # Persist outside the lock: only this thread mutates these values,
            # so a slow disk write must not stall the render thread (which
            # takes the same lock every frame).
            if persist:
                self._persist_state()
            if changed:
                self._redraw.set()

    def _build_gpu_stats(self, samples) -> list[GPUStats]:
        stats = []
        for sample in samples:
            # Read the aggregates the collector cached on its last tick rather
            # than querying the DB on every render.
            result = self._collector.get_latest_stats(sample.gpu.index)
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

    def _update_offload_banner(self, ollama_sample) -> bool:
        """Advance the GPU-offloading banner state machine for one frame and
        return whether the banner should show. The banner is held for at least
        OFFLOAD_BANNER_HOLD_SECONDS so it doesn't flicker at fast sample rates,
        and the peak offload percentage seen during a hold window drives the
        orange→red color (so a momentary lighter sample can't downgrade it).
        Runs only on the render thread, so it needs no lock."""
        now_mono = time.monotonic()
        if ollama_sample is not None and ollama_sample.offloading:
            # Fresh banner session → reset peak before folding in this sample.
            if now_mono >= self._offload_until:
                self._offload_peak_pct = 0.0
            self._offload_until = now_mono + OFFLOAD_BANNER_HOLD_SECONDS
            self._offload_peak_pct = max(
                self._offload_peak_pct,
                100.0 - ollama_sample.gpu_pct,
            )
        show_banner = now_mono < self._offload_until
        if not show_banner:
            self._offload_peak_pct = 0.0
        return show_banner

    def _nudge_threshold(self, steps: int) -> None:
        """Move the temperature threshold by `steps` * step, clamped to the
        valid range. Caller holds self._lock."""
        self._temp_threshold_c = max(
            TEMP_THRESHOLD_MIN,
            min(
                TEMP_THRESHOLD_MAX,
                round(self._temp_threshold_c + steps * TEMP_THRESHOLD_STEP, 1),
            ),
        )
