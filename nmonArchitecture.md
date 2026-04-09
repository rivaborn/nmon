# nmon — Nvidia GPU Monitor: Architecture Plan

## 1. Project Structure

```
nmon/
├── pyproject.toml                  # Build metadata, dependencies, entry point
├── config.toml                     # User-editable runtime config (shipped with defaults)
├── nmon.db                         # SQLite DB (created on first run, gitignored)
├── src/
│   └── nmon/
│       ├── __init__.py
│       ├── __main__.py             # Entry point: parse CLI args, bootstrap app
│       ├── config.py               # Config loading, validation, defaults
│       ├── models.py               # Dataclasses and TypedDicts for all data
│       ├── storage.py              # SQLite schema, read/write, pruning
│       ├── collector.py            # Background sampling thread, orchestrator
│       ├── gpu/
│       │   ├── __init__.py
│       │   ├── base.py             # Abstract GPUSource base class
│       │   ├── nvml_source.py      # pynvml implementation
│       │   └── smi_source.py       # nvidia-smi XML subprocess implementation
│       └── tui/
│           ├── __init__.py
│           ├── app.py              # Rich Live loop, tab router, key handler
│           ├── dashboard.py        # Screen 1: live dashboard renderables
│           ├── history.py          # Screens 2–4: history chart renderables
│           └── widgets.py          # Shared Rich renderables (bar, sparkline, chart)
└── tests/
    ├── conftest.py                 # Shared fixtures: in-memory DB, fake samples
    ├── fixtures/
    │   ├── smi_1gpu.xml            # Static nvidia-smi XML for 1 GPU
    │   └── smi_2gpu.xml            # Static nvidia-smi XML for 2 GPUs
    ├── test_config.py
    ├── test_models.py
    ├── test_storage.py
    ├── test_collector.py
    ├── test_gpu_nvml.py
    ├── test_gpu_smi.py
    ├── test_tui_dashboard.py
    ├── test_tui_history.py
    ├── test_tui_widgets.py
    └── test_integration.py
```

---

## 2. Data Model

### 2.1 SQLite Schema

```sql
-- One row per sample per GPU
CREATE TABLE IF NOT EXISTS gpu_samples (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    gpu_index       INTEGER NOT NULL,
    gpu_uuid        TEXT    NOT NULL,
    gpu_name        TEXT    NOT NULL,
    timestamp       REAL    NOT NULL,   -- Unix epoch (seconds, float)
    temperature_c   REAL    NOT NULL,
    memory_used_mib REAL    NOT NULL,
    memory_total_mib REAL   NOT NULL,
    power_draw_w    REAL    NOT NULL
);

-- Query pattern: WHERE gpu_index = ? AND timestamp >= ?
CREATE INDEX IF NOT EXISTS idx_samples_gpu_time
    ON gpu_samples (gpu_index, timestamp);
```

Rationale: a single table keeps queries simple. The index covers all dashboard
and history queries (filter by GPU + time range). No FK normalization needed
at this scale; GPU name/UUID are cheap to repeat.

### 2.2 Python In-Memory Representations

```python
# models.py

from dataclasses import dataclass, field
from typing import TypedDict

@dataclass(frozen=True)
class GPUInfo:
    index: int          # 0-based ordinal from driver
    uuid: str           # GPU-UUID (stable across reboots)
    name: str           # e.g. "NVIDIA GeForce RTX 4090"

@dataclass
class GPUSample:
    gpu: GPUInfo
    timestamp: float        # Unix epoch
    temperature_c: float
    memory_used_mib: float
    memory_total_mib: float
    power_draw_w: float

    @property
    def memory_fraction(self) -> float:
        """Returns 0.0–1.0"""
        if self.memory_total_mib == 0:
            return 0.0
        return self.memory_used_mib / self.memory_total_mib

@dataclass
class GPUStats:
    """Aggregated view shown on the live dashboard."""
    gpu: GPUInfo
    current: GPUSample
    max_temp_24h: float
    avg_temp_1h: float

class HistoryRow(TypedDict):
    timestamp: float
    value: float

@dataclass
class AppConfig:
    interval_seconds: int
    min_interval: int
    max_interval: int
    db_path: str
    retention_hours: int
    default_tab: str            # "dashboard" | "temp" | "power" | "memory"
    default_time_window_hours: int
```

---

## 3. Module Breakdown

### 3.1 `models.py`

**Purpose:** Pure data containers with zero side effects. All modules import from
here; nothing here imports from other nmon modules.

**No external dependencies.**

**Functions:**
```
sample_to_row(sample: GPUSample) -> dict[str, object]
    # Converts GPUSample to a flat dict matching the DB column names.
    # Used by storage.py to avoid coupling DB schema to the dataclass fields.

row_to_sample(row: sqlite3.Row) -> GPUSample
    # Inverse of sample_to_row; reconstructs GPUSample from a DB row.
```

**Error handling:** None needed — pure data transformations.

---

### 3.2 `config.py`

**Purpose:** Load `config.toml`, apply defaults for missing keys, validate ranges,
expose a single `load_config(path: str | None) -> AppConfig` function.

**Functions:**
```
load_config(path: str | None = None) -> AppConfig
    # 1. If path is None, look for config.toml in CWD, then ~/.nmon/config.toml.
    # 2. If no file found, use all defaults (no error).
    # 3. Parse TOML with tomllib (3.11+) or tomli fallback.
    # 4. Call _validate(raw_dict) → raises ConfigError on bad values.
    # 5. Return AppConfig populated from parsed+defaulted dict.

_apply_defaults(raw: dict) -> dict
    # Deep-merges raw against DEFAULTS dict.
    # Returns new dict; does not mutate raw.

_validate(cfg: dict) -> None
    # Raises ConfigError if:
    #   interval_seconds not in [min_interval, max_interval]
    #   retention_hours < 1
    #   db_path is not a string
    #   default_time_window_hours not in {1, 4, 12, 24}
```

**Error handling:** `ConfigError(ValueError)` with a human-readable message
including the offending key and its value. Callers catch and display via Rich
before exiting.

---

### 3.3 `gpu/base.py`

**Purpose:** Abstract contract that both GPU sources implement.

```python
from abc import ABC, abstractmethod
from nmon.models import GPUInfo, GPUSample

class GPUSource(ABC):
    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the underlying driver/binary is usable."""

    @abstractmethod
    def list_gpus(self) -> list[GPUInfo]:
        """Return ordered list of detected GPUs. Empty list if none."""

    @abstractmethod
    def sample_all(self) -> list[GPUSample]:
        """
        Return one GPUSample per GPU, timestamped at call time.
        Raises GPUSourceError on transient failure.
        """

    def close(self) -> None:
        """Optional cleanup (release library handles, etc.)."""
```

**Error handling:** `GPUSourceError(RuntimeError)` for transient errors
(driver hiccup, smi timeout). Callers should catch and retry on next cycle.

---

### 3.4 `gpu/nvml_source.py`

**Purpose:** Implements `GPUSource` using `pynvml`. Preferred path — avoids
subprocess overhead.

**Functions:**
```
class NvmlSource(GPUSource):
    _initialized: bool = False

    def is_available(self) -> bool
        # Try pynvml.nvmlInit(); return True on success, False on NVMLError.
        # Does NOT raise.

    def _ensure_init(self) -> None
        # If not _initialized: call nvmlInit(), set flag.
        # Raises GPUSourceError wrapping NVMLError if init fails.

    def list_gpus(self) -> list[GPUInfo]
        # _ensure_init()
        # nvmlDeviceGetCount() → for each index:
        #   handle = nvmlDeviceGetHandleByIndex(i)
        #   uuid   = nvmlDeviceGetUUID(handle)
        #   name   = nvmlDeviceGetName(handle)
        #   append GPUInfo(index=i, uuid=uuid, name=name)

    def sample_all(self) -> list[GPUSample]
        # _ensure_init()
        # ts = time.time()
        # for each handle:
        #   temp  = nvmlDeviceGetTemperature(handle, NVML_TEMPERATURE_GPU)
        #   mem   = nvmlDeviceGetMemoryInfo(handle) → .used, .total (bytes→MiB)
        #   power = nvmlDeviceGetPowerUsage(handle) / 1000.0  (mW→W)
        #   append GPUSample(...)
        # Wraps NVMLError in GPUSourceError.

    def close(self) -> None
        # if _initialized: nvmlShutdown(); _initialized = False
```

**Error handling:** All `pynvml.NVMLError` exceptions are caught and re-raised
as `GPUSourceError`. The collector layer decides whether to retry or surface.

---

### 3.5 `gpu/smi_source.py`

**Purpose:** Implements `GPUSource` by shelling out to `nvidia-smi --xml-format
--query-gpu`. Fallback when pynvml is unavailable (e.g., system Python without
the library installed).

**Functions:**
```
class SmiSource(GPUSource):
    SMI_TIMEOUT: int = 5  # seconds

    def is_available(self) -> bool
        # subprocess.run(["nvidia-smi", "-L"], capture_output=True, timeout=3)
        # Return True if returncode == 0. Catch FileNotFoundError → False.

    def _run_smi(self, args: list[str]) -> str
        # subprocess.run(["nvidia-smi"] + args, capture_output=True,
        #                text=True, timeout=self.SMI_TIMEOUT)
        # If returncode != 0: raise GPUSourceError(stderr)
        # Return stdout.

    def _parse_xml(self, xml_text: str) -> list[GPUSample]
        # xml.etree.ElementTree.fromstring(xml_text)
        # For each <gpu> element:
        #   index = int(gpu.find("minor_number").text)
        #   uuid  = gpu.find("uuid").text.strip()
        #   name  = gpu.find("product_name").text.strip()
        #   temp  = float(gpu.find("temperature/gpu_temp").text.split()[0])
        #   mem_used  = float(gpu.find("fb_memory_usage/used").text.split()[0])
        #   mem_total = float(gpu.find("fb_memory_usage/total").text.split()[0])
        #   power = float(gpu.find("power_readings/power_draw").text.split()[0])
        # Return list[GPUSample]. Wraps ParseError in GPUSourceError.

    def list_gpus(self) -> list[GPUInfo]
        # samples = self.sample_all()
        # Return [s.gpu for s in samples]

    def sample_all(self) -> list[GPUSample]
        # xml_text = self._run_smi(["--xml-format", "--query-gpu=..."])
        # return self._parse_xml(xml_text)
```

**Error handling:** `subprocess.TimeoutExpired`, `FileNotFoundError`, and
`xml.etree.ElementTree.ParseError` all map to `GPUSourceError`.

---

### 3.6 `storage.py`

**Purpose:** All SQLite I/O. Owns schema creation, inserts, queries, and pruning.
No business logic.

**Functions:**
```
class Storage:
    def __init__(self, db_path: str) -> None
        # sqlite3.connect(db_path, check_same_thread=False)
        # Enable WAL mode for concurrent reader+writer.
        # Call _create_schema().

    def _create_schema(self) -> None
        # Execute CREATE TABLE IF NOT EXISTS and CREATE INDEX IF NOT EXISTS.

    def insert_samples(self, samples: list[GPUSample]) -> None
        # Converts each sample via sample_to_row().
        # executemany() with a single transaction.

    def prune_old(self, retention_hours: int) -> int
        # cutoff = time.time() - retention_hours * 3600
        # DELETE FROM gpu_samples WHERE timestamp < cutoff
        # Return rowcount (for logging).

    def get_current_stats(self, gpu_index: int) -> tuple[float, float] | None
        # Returns (max_temp_24h, avg_temp_1h) for the given GPU.
        # Single query:
        #   SELECT
        #     MAX(CASE WHEN timestamp >= ? THEN temperature_c END),
        #     AVG(CASE WHEN timestamp >= ? THEN temperature_c END)
        #   FROM gpu_samples
        #   WHERE gpu_index = ?
        # Returns None if no rows found.

    def get_history(
        self,
        gpu_index: int,
        metric: Literal["temperature_c", "memory_used_mib", "power_draw_w"],
        since: float,
    ) -> list[HistoryRow]
        # SELECT timestamp, {metric} FROM gpu_samples
        # WHERE gpu_index = ? AND timestamp >= ?
        # ORDER BY timestamp ASC
        # Returns list[HistoryRow].

    def close(self) -> None
        # self._conn.close()
```

**Thread safety:** `check_same_thread=False` + WAL mode. All writes come from
the single collector thread; reads from the TUI thread. WAL prevents reader
starvation.

**Error handling:** `sqlite3.OperationalError` on insert/query is logged and
re-raised as `StorageError(RuntimeError)`. The collector catches it, logs the
error, skips the cycle, and continues.

---

### 3.7 `collector.py`

**Purpose:** Runs the sampling loop in a daemon thread. Writes to `Storage`.
Publishes the latest `list[GPUSample]` to a shared slot the TUI reads from.

```python
class Collector:
    def __init__(
        self,
        source: GPUSource,
        storage: Storage,
        config: AppConfig,
    ) -> None

    def start(self) -> None
        # Spawns daemon thread running _loop().

    def stop(self) -> None
        # Sets _stop_event; joins thread with timeout.

    def get_latest(self) -> list[GPUSample] | None
        # Returns last successful list[GPUSample] (thread-safe read from
        # a threading.Lock-protected slot). Returns None before first sample.

    def set_interval(self, seconds: int) -> None
        # Clamps to [min_interval, max_interval]. Thread-safe write.

    def _loop(self) -> None
        # while not _stop_event.is_set():
        #   t0 = time.monotonic()
        #   try:
        #     samples = source.sample_all()
        #     with _lock: _latest = samples
        #     storage.insert_samples(samples)
        #     storage.prune_old(config.retention_hours)
        #   except GPUSourceError as e:
        #     log warning; if gpu count changed, log additional notice
        #   except StorageError as e:
        #     log error
        #   elapsed = time.monotonic() - t0
        #   _stop_event.wait(max(0, _interval - elapsed))
```

**GPU hot-plug:** After each sample, compare `len(samples)` to
`_last_gpu_count`. If different, emit a warning via the shared log queue and
update `_last_gpu_count`.

**Error handling:** Never lets exceptions escape `_loop()` — catches all known
error types, logs them to a bounded `collections.deque` that the TUI can
display, then sleeps and continues.

---

### 3.8 `tui/widgets.py`

**Purpose:** Custom Rich `Renderable` classes used by both dashboard and history
screens.

```
class MemoryBar:
    """Renders 'used / total MiB [████░░░░] XX%' as a Rich Text object."""
    def __init__(self, used: float, total: float, width: int = 20) -> None
    def __rich_console__(self, console, options) -> RenderResult

class BrailleChart:
    """
    Renders a Unicode Braille-dot line chart for a single time series.
    Uses the 2×4 Braille block grid (U+2800–U+28FF) to achieve
    ~2× horizontal and ~4× vertical resolution vs. block characters.
    """
    def __init__(
        self,
        data: list[HistoryRow],
        width: int,
        height: int,
        label: str,
        color: str,
        y_label: str,
    ) -> None
    def __rich_console__(self, console, options) -> RenderResult
    def _normalize(self, values: list[float]) -> list[float]
        # Scale to [0, height*4] for Braille row packing.
    def _render_axes(self) -> list[str]
        # Returns Y-axis label strings (min, mid, max values).

class MultiSeriesChart:
    """Wraps multiple BrailleChart series into a single renderable."""
    def __init__(
        self,
        series: list[tuple[list[HistoryRow], str, str]],  # (data, label, color)
        width: int,
        height: int,
        y_label: str,
        time_window_label: str,
    ) -> None
    def __rich_console__(self, console, options) -> RenderResult

class StatusBar:
    """Bottom bar: interval, tab hints, error count."""
    def __init__(self, interval: int, tab: str, error_count: int) -> None
    def __rich_console__(self, console, options) -> RenderResult
```

---

### 3.9 `tui/dashboard.py`

**Purpose:** Produces the `Layout` / `Table` renderable for Screen 1.

```
def build_dashboard(
    stats: list[GPUStats],
    width: int,
) -> RenderableType
    # Returns a Rich Table with one row per GPU.
    # Columns: GPU, Temp (°C), Max 24h, Avg 1h, Memory (bar + %), Power (W)
    # If stats is empty: returns a Panel with "No GPU data yet."

def build_gpu_row(stats: GPUStats, bar_width: int) -> list[RenderableType]
    # Returns the cell renderables for one table row.
    # Memory cell = MemoryBar widget.
    # Temperature cells are color-coded:
    #   < 60°C → green, 60–80 → yellow, > 80 → red
```

---

### 3.10 `tui/history.py`

**Purpose:** Produces renderables for Screens 2–4.

```
METRIC_CONFIG: dict[str, dict] = {
    "temp":   {"column": "temperature_c",   "label": "Temperature", "unit": "°C"},
    "power":  {"column": "power_draw_w",    "label": "Power Draw",  "unit": "W"},
    "memory": {"column": "memory_used_mib", "label": "Memory Used", "unit": "MiB"},
}

TIME_WINDOWS: list[int] = [1, 4, 12, 24]  # hours

def build_history(
    storage: Storage,
    gpu_list: list[GPUInfo],
    metric: Literal["temp", "power", "memory"],
    time_window_hours: int,
    width: int,
    height: int,
) -> RenderableType
    # 1. since = time.time() - time_window_hours * 3600
    # 2. For each GPU: storage.get_history(gpu.index, column, since)
    # 3. Build MultiSeriesChart; assign colors by GPU index.
    # 4. Return Panel wrapping the chart + time window selector hint.

def format_time_window_tabs(current: int) -> str
    # Returns e.g. " [1hr]  4hr   12hr  24hr " with current bracketed.
```

---

### 3.11 `tui/app.py`

**Purpose:** Main TUI loop. Owns the `rich.live.Live` instance, dispatches
keyboard input, and renders the active tab.

```
TABS: list[str] = ["dashboard", "temp", "power", "memory"]
TAB_KEYS: dict[str, str] = {"1": "dashboard", "2": "temp", "3": "power", "4": "memory"}

class NmonApp:
    def __init__(self, collector: Collector, storage: Storage, config: AppConfig) -> None

    def run(self) -> None
        # 1. Start collector.
        # 2. Start _key_thread (daemon) → calls _handle_keys().
        # 3. with Live(console=console, refresh_per_second=1/interval, screen=True):
        #      while not _quit:
        #        live.update(self._render())
        #        time.sleep(interval)
        # 4. On exit: collector.stop().

    def _render(self) -> RenderableType
        # Build Layout: header | body | footer
        # header: app name + active tab indicator
        # body: delegate to dashboard.build_dashboard or history.build_history
        # footer: StatusBar widget

    def _handle_keys(self) -> None
        # Runs in daemon thread using readchar.readkey().
        # "q" / Ctrl+C → set _quit.
        # "1"–"4" → switch _active_tab.
        # "[" / "]" → cycle time window for history tabs.
        # "+" / "-" → increase/decrease interval; call collector.set_interval().

    def _build_gpu_stats(self, samples: list[GPUSample]) -> list[GPUStats]
        # For each sample, query storage.get_current_stats() and construct GPUStats.
```

**Thread model:**
- Main thread: `Live` render loop
- Collector thread (daemon): sampling + DB writes
- Key thread (daemon): blocking keyboard reads

The render loop reads from `collector.get_latest()` (lock-protected) and
queries `storage` read-only. No data races.

---

### 3.12 `__main__.py`

```
def main() -> None
    # 1. argparse: --config PATH, --interval N, --db PATH
    # 2. config = load_config(args.config); apply CLI overrides.
    # 3. source = _pick_source()  → NvmlSource if available, else SmiSource
    # 4. if not source.is_available(): print error; sys.exit(1)
    # 5. storage = Storage(config.db_path)
    # 6. collector = Collector(source, storage, config)
    # 7. app = NmonApp(collector, storage, config)
    # 8. try: app.run() finally: storage.close(); source.close()

def _pick_source() -> GPUSource
    # Try NvmlSource; if not available, fall back to SmiSource.
    # Log which source is being used.
```

---

## 4. Sampling Pipeline

```
┌─────────────────────────────────────────────────────────┐
│ Collector thread (runs every N seconds)                  │
│                                                          │
│  GPUSource.sample_all()                                  │
│       │ list[GPUSample]                                  │
│       ▼                                                  │
│  _lock.acquire()                                         │
│  _latest = samples          ◄── TUI reads this slot     │
│  _lock.release()                                         │
│       │                                                  │
│       ▼                                                  │
│  Storage.insert_samples(samples)                         │
│  Storage.prune_old(retention_hours)                      │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ TUI render loop (main thread, every N seconds)           │
│                                                          │
│  collector.get_latest() → list[GPUSample]  (live data)  │
│  storage.get_current_stats(gpu_index)      (aggregates) │
│  storage.get_history(gpu_index, metric, since) (charts) │
│       │                                                  │
│       ▼                                                  │
│  build_dashboard / build_history → RenderableType        │
│  Live.update(renderable)                                 │
└─────────────────────────────────────────────────────────┘
```

Key design decisions:
- The `_latest` slot means the TUI always has *something* to display even if a
  sample cycle fails.
- SQLite WAL mode allows the TUI (reader) and collector (writer) to proceed
  concurrently without blocking.
- `prune_old` runs on every write cycle, so the DB never grows unboundedly.

---

## 5. TUI Layout

```
┌──────────────────────────────────────────────────────────┐
│ nmon  [1:Dashboard]  2:Temp  3:Power  4:Memory           │  ← Header (1 line)
├──────────────────────────────────────────────────────────┤
│                                                          │
│  (body — full remaining height)                          │
│                                                          │
│  Dashboard: rich.table.Table                             │
│    ┌──────┬──────┬────────┬────────┬──────────┬───────┐  │
│    │ GPU  │ Temp │Max 24h │Avg 1h  │  Memory  │ Power │  │
│    ├──────┼──────┼────────┼────────┼──────────┼───────┤  │
│    │ RTX  │ 72°C │  85°C  │  69°C  │ ████░ 60%│ 120 W │  │
│    └──────┴──────┴────────┴────────┴──────────┴───────┘  │
│                                                          │
│  History: rich.panel.Panel + MultiSeriesChart            │
│    ┌─ Temperature History ─ [1hr]  4hr  12hr  24hr ────┐ │
│    │  90 ┤                                              │ │
│    │  70 ┤  ⣾⣿⣷⣾⣿⣷⣾⣿⣷ (braille line)               │ │
│    │  50 ┤                                              │ │
│    │     └───────────────────────────────── time ────  │ │
│    └──────────────────────────────────────────────────┘ │
│                                                          │
├──────────────────────────────────────────────────────────┤
│ Interval: 2s  │  q: Quit  +/-: Interval  [/]: Window    │  ← Footer (1 line)
└──────────────────────────────────────────────────────────┘
```

**Rich components used:**

| Region | Rich component |
|--------|---------------|
| Outer container | `rich.layout.Layout` |
| Auto-refresh | `rich.live.Live(screen=True)` |
| Dashboard table | `rich.table.Table` |
| Memory bar | Custom `MemoryBar` renderable (Rich `Text`) |
| History charts | Custom `BrailleChart` / `MultiSeriesChart` renderables |
| Panels / borders | `rich.panel.Panel` |
| Color/style | `rich.style.Style`, `rich.text.Text` |
| Status bar | Custom `StatusBar` renderable |

---

## 6. Configuration

### 6.1 `config.toml` Schema and Defaults

```toml
[sampling]
# How often to poll the GPU (seconds). Range: [min_interval, max_interval].
interval_seconds = 2
min_interval = 1
max_interval = 60

[storage]
# Path to the SQLite database file.
db_path = "nmon.db"
# How many hours of data to retain. Older rows are pruned on each write.
retention_hours = 24

[display]
# Which tab to show on startup: "dashboard", "temp", "power", "memory"
default_tab = "dashboard"
# Starting time window for history tabs (hours): 1, 4, 12, or 24
default_time_window_hours = 1
```

### 6.2 Validation Rules

| Key | Rule |
|-----|------|
| `interval_seconds` | Integer in `[min_interval, max_interval]` |
| `min_interval` | Integer ≥ 1 |
| `max_interval` | Integer ≤ 300, ≥ `min_interval` |
| `db_path` | Non-empty string |
| `retention_hours` | Integer ≥ 1 |
| `default_tab` | One of `{"dashboard", "temp", "power", "memory"}` |
| `default_time_window_hours` | One of `{1, 4, 12, 24}` |

### 6.3 CLI Overrides

`--config PATH` — path to a custom TOML file  
`--interval N` — overrides `sampling.interval_seconds`  
`--db PATH` — overrides `storage.db_path`

CLI overrides are applied after file parsing, so they win.

---

## 7. Testing Strategy

### 7.1 `test_config.py`

- `test_load_defaults()` — when no file exists, returns all defaults
- `test_load_valid_file()` — parses correct TOML with every field present
- `test_partial_file_merges_defaults()` — missing keys fall back to defaults
- `test_invalid_interval_raises()` — interval < min_interval → ConfigError
- `test_invalid_tab_raises()` — unknown tab name → ConfigError
- `test_cli_override_wins()` — CLI value beats file value

### 7.2 `test_models.py`

- `test_memory_fraction_normal()` — 4096 / 8192 == 0.5
- `test_memory_fraction_zero_total()` — returns 0.0, no ZeroDivisionError
- `test_sample_to_row_roundtrip()` — `row_to_sample(sample_to_row(s)) == s`

### 7.3 `test_storage.py`

Fixtures: in-memory SQLite (`":memory:"`), built in `conftest.py`.

- `test_schema_creates_on_init()` — table and index exist after `__init__`
- `test_insert_and_retrieve_single_sample()` — one sample in, same sample out
- `test_insert_multiple_gpus()` — two GPUs stored; queried independently
- `test_prune_removes_old_rows()` — rows older than cutoff are deleted; newer rows survive
- `test_prune_returns_count()` — return value matches deleted row count
- `test_get_current_stats_empty()` — returns None when no rows
- `test_get_current_stats_24h_max()` — max temp is the highest in 24h window
- `test_get_current_stats_1h_avg()` — avg is computed only over 1h window
- `test_get_history_ordered_by_time()` — rows come back ascending
- `test_get_history_respects_since()` — rows before `since` are excluded
- `test_concurrent_read_write()` — writer thread and reader thread run for 2s without deadlock

### 7.4 `test_collector.py`

Mocks: `MockGPUSource`, `MockStorage` (both using `unittest.mock.MagicMock`).

- `test_start_stop_clean()` — start(); sleep 0.1; stop() — thread is no longer alive
- `test_latest_updated_after_sample()` — get_latest() returns None before first cycle, then data
- `test_source_error_does_not_crash_loop()` — source raises GPUSourceError; loop continues; get_latest() returns previous value
- `test_storage_error_does_not_crash_loop()` — storage.insert_samples raises; loop continues
- `test_set_interval_clamps_to_min()` — set_interval(0) → uses min_interval
- `test_set_interval_clamps_to_max()` — set_interval(999) → uses max_interval
- `test_gpu_count_change_emits_warning()` — first sample has 1 GPU, second has 2 → warning in log queue

### 7.5 `test_gpu_nvml.py`

Mocks: `unittest.mock.patch("pynvml.*")` at module level in fixtures.

- `test_is_available_true()` — nvmlInit succeeds → True
- `test_is_available_false_on_error()` — nvmlInit raises NVMLError → False
- `test_list_gpus_single()` — 1-GPU fixture → list of 1 GPUInfo
- `test_list_gpus_multi()` — 2-GPU fixture → list of 2 GPUInfo
- `test_sample_all_values()` — verifies temp/mem/power extracted correctly and units converted
- `test_sample_all_wraps_nvml_error()` — NVMLError during sample → GPUSourceError
- `test_close_calls_shutdown()` — close() calls nvmlShutdown exactly once
- `test_close_idempotent()` — close() twice → nvmlShutdown called once

### 7.6 `test_gpu_smi.py`

Fixtures: `tests/fixtures/smi_1gpu.xml`, `smi_2gpu.xml` as static files.

- `test_is_available_true()` — `nvidia-smi -L` returns 0 → True
- `test_is_available_false_missing_binary()` — FileNotFoundError → False
- `test_is_available_false_nonzero()` — returncode 1 → False
- `test_parse_xml_1gpu()` — parse `smi_1gpu.xml`; verify all fields
- `test_parse_xml_2gpus()` — parse `smi_2gpu.xml`; two samples with correct indices
- `test_parse_xml_malformed_raises()` — broken XML → GPUSourceError
- `test_smi_timeout_raises()` — subprocess timeout → GPUSourceError
- `test_smi_nonzero_exit_raises()` — exit code 1 + stderr → GPUSourceError

### 7.7 `test_tui_widgets.py`

- `test_memory_bar_full()` — 8192/8192 → bar fully filled
- `test_memory_bar_zero()` — 0/8192 → bar empty, 0%
- `test_memory_bar_half()` — 4096/8192 → ~50%
- `test_braille_chart_empty_data()` — renders without error when data list is empty
- `test_braille_chart_single_point()` — one data point renders without error
- `test_braille_chart_normalize_range()` — min maps to 0, max maps to height*4
- `test_status_bar_renders()` — StatusBar renders all fields without error

### 7.8 `test_tui_dashboard.py`

- `test_build_dashboard_no_gpus()` — empty list → "No GPU data" panel
- `test_build_dashboard_single_gpu()` — correct values appear in table output
- `test_build_dashboard_temp_color_green()` — 55°C → green style
- `test_build_dashboard_temp_color_yellow()` — 70°C → yellow style
- `test_build_dashboard_temp_color_red()` — 85°C → red style

### 7.9 `test_tui_history.py`

Mocks: `MockStorage` with canned `get_history()` responses.

- `test_build_history_temp()` — metric="temp" → chart title and y-label correct
- `test_build_history_power()` — metric="power" → W label
- `test_build_history_memory()` — metric="memory" → MiB label
- `test_time_window_tabs_highlights_current()` — current window is bracketed
- `test_build_history_empty_data()` — no rows → renders without error

### 7.10 `test_integration.py`

End-to-end pipeline using `MockGPUSource` + real in-memory SQLite.

- `test_sample_stored_and_retrievable()`:
  1. Collector writes 3 cycles of synthetic data.
  2. Storage.get_history() returns exactly those rows in order.
  3. Storage.get_current_stats() computes correct max and average.

- `test_pruning_removes_old_data()`:
  1. Insert samples with timestamps spanning 25 hours.
  2. prune_old(24) removes the oldest hour's worth.
  3. get_history(since=now-24h) returns only the retained rows.

- `test_multi_gpu_isolation()`:
  1. Insert 2 GPUs with different temperatures.
  2. get_history(gpu_index=0) returns only GPU 0 rows.

### 7.11 Mocking Strategy

**pynvml:** Patched at the import level in `conftest.py` so tests never need a
real GPU:
```python
@pytest.fixture(autouse=True)
def mock_pynvml(monkeypatch):
    mock = MagicMock()
    monkeypatch.setitem(sys.modules, "pynvml", mock)
    yield mock
```

**nvidia-smi subprocess:** Patched via `unittest.mock.patch("subprocess.run")`.
The fixture configures `returncode`, `stdout` (XML content from fixture files),
and `stderr`.

**Fixture XML files** cover:
- 1 GPU (index 0, RTX 4090, various readings)
- 2 GPUs (indices 0 and 1, different models and readings)
- A malformed XML snippet for error path testing

---

## 8. Dependency List

```toml
# pyproject.toml [project.dependencies]
dependencies = [
    "rich>=13.7",           # Terminal UI framework
    "pynvml>=11.5.0",       # NVML Python bindings (nvidia-smi alternative)
    "readchar>=4.0.5",      # Cross-platform single-keypress reads
    "tomli>=2.0.1; python_version < '3.11'",  # TOML parser (stdlib in 3.11+)
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-mock>=3.12",
    "coverage>=7.4",
]
```

**Rationale for each:**

| Package | Why |
|---------|-----|
| `rich` | TUI rendering; `Live`, `Table`, `Panel`, `Layout`, `Text` |
| `pynvml` | Direct NVML bindings; faster than subprocess, no parsing |
| `readchar` | Blocking single-key reads on Windows without raw-mode boilerplate |
| `tomli` | `tomllib` compatibility shim for Python 3.10 |
| `pytest` | Test runner |
| `pytest-mock` | `mocker` fixture for clean mock management |
| `coverage` | Branch and line coverage reporting |

**Explicitly excluded:**

| Package | Why excluded |
|---------|-------------|
| `asyncio` | Threading is simpler and sufficient for 2 concurrent tasks |
| `plotext` | Braille charts are self-contained and avoid an extra dependency |
| `textual` | Heavyweight; Rich alone is sufficient for this layout |
| `click` | `argparse` is stdlib; no complex CLI needed |

---

## 9. Build and Run Instructions

### 9.1 Prerequisites

- Python 3.10 or later
- Nvidia GPU with drivers installed
- `nvidia-smi` accessible on `PATH` (usually `C:\Windows\System32\nvidia-smi.exe`)
  OR `pynvml`-compatible Nvidia driver (recommended)

### 9.2 Installation

```bash
# Clone or download the project
cd nmon

# Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows

# Install the package and its dependencies
pip install -e .

# (For development/testing)
pip install -e ".[dev]"
```

### 9.3 Configuration

Copy or edit `config.toml` in the project root:
```bash
# Optional: specify a custom config location
nmon --config path/to/myconfig.toml
```

### 9.4 Running

```bash
# Default: uses config.toml in CWD
nmon

# Override interval and DB path via CLI
nmon --interval 5 --db /tmp/nmon.db

# Keyboard controls inside the app:
#   1-4     Switch tabs (1=Dashboard, 2=Temp, 3=Power, 4=Memory)
#   +/-     Increase/decrease sample interval
#   [/]     Cycle time window on history tabs
#   q       Quit
```

### 9.5 Running Tests

```bash
pytest tests/

# With coverage
coverage run -m pytest tests/
coverage report -m

# Single module
pytest tests/test_storage.py -v
```

### 9.6 Database Management

The SQLite database (`nmon.db` by default) is created automatically on first
run. It self-prunes to `retention_hours` on every write cycle. To reset:
```bash
# Delete the DB file — it will be recreated on next launch
del nmon.db
```

---

*End of architecture plan.*
