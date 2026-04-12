# nmon Implementation — One File Per Session

Each step is a separate aider invocation. The prompt is self-contained —
do NOT --read nmonArchitecture.md, it is too large. Run each command, paste
the prompt, wait for it to finish, then move to the next step.

---

## Step 1 — pyproject.toml + config.toml

```bash
aider --yes pyproject.toml config.toml
```
```
Create pyproject.toml and config.toml for a Python package called nmon.

pyproject.toml:
- [build-system] requires = ["setuptools>=68"], build-backend = "setuptools.backends.legacy:build"
- [project] name="nmon", version="0.1.0", requires-python=">=3.10"
- dependencies: rich>=13.7, pynvml>=11.5.0, readchar>=4.0.5,
  "tomli>=2.0.1; python_version < '3.11'"
- [project.optional-dependencies] dev = [pytest>=8.0, pytest-mock>=3.12, coverage>=7.4]
- [project.scripts] nmon = "nmon.__main__:main"

config.toml:
[sampling]
interval_seconds = 2
min_interval = 1
max_interval = 60

[storage]
db_path = "nmon.db"
retention_hours = 24

[display]
default_tab = "dashboard"
default_time_window_hours = 1
```

---

## Step 2 — models.py

```bash
aider --yes src/nmon/__init__.py src/nmon/models.py
```
```
Create src/nmon/__init__.py as an empty file.

Create src/nmon/models.py with:

from dataclasses import dataclass
from typing import TypedDict, Literal

@dataclass(frozen=True)
class GPUInfo:
    index: int
    uuid: str
    name: str

@dataclass
class GPUSample:
    gpu: GPUInfo
    timestamp: float
    temperature_c: float
    memory_used_mib: float
    memory_total_mib: float
    power_draw_w: float

    @property
    def memory_fraction(self) -> float:
        if self.memory_total_mib == 0:
            return 0.0
        return self.memory_used_mib / self.memory_total_mib

@dataclass
class GPUStats:
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
    default_tab: str
    default_time_window_hours: int

def sample_to_row(sample: GPUSample) -> dict:
    return {
        "gpu_index": sample.gpu.index,
        "gpu_uuid": sample.gpu.uuid,
        "gpu_name": sample.gpu.name,
        "timestamp": sample.timestamp,
        "temperature_c": sample.temperature_c,
        "memory_used_mib": sample.memory_used_mib,
        "memory_total_mib": sample.memory_total_mib,
        "power_draw_w": sample.power_draw_w,
    }

def row_to_sample(row) -> GPUSample:
    # row is a sqlite3.Row or dict with the same keys as sample_to_row output
    gpu = GPUInfo(index=row["gpu_index"], uuid=row["gpu_uuid"], name=row["gpu_name"])
    return GPUSample(
        gpu=gpu,
        timestamp=row["timestamp"],
        temperature_c=row["temperature_c"],
        memory_used_mib=row["memory_used_mib"],
        memory_total_mib=row["memory_total_mib"],
        power_draw_w=row["power_draw_w"],
    )
```

---

## Step 3 — config.py

```bash
aider --yes src/nmon/config.py src/nmon/models.py
```
```
Create src/nmon/config.py.

Use tomllib (Python 3.11+) with tomli fallback:
  try:
      import tomllib
  except ImportError:
      import tomli as tomllib

DEFAULTS = {
    "sampling": {"interval_seconds": 2, "min_interval": 1, "max_interval": 60},
    "storage": {"db_path": "nmon.db", "retention_hours": 24},
    "display": {"default_tab": "dashboard", "default_time_window_hours": 1},
}

class ConfigError(ValueError): pass

def _apply_defaults(raw: dict) -> dict:
    result = {}
    for section, defaults in DEFAULTS.items():
        result[section] = {**defaults, **raw.get(section, {})}
    return result

def _validate(cfg: dict) -> None:
    s = cfg["sampling"]
    if not (s["min_interval"] <= s["interval_seconds"] <= s["max_interval"]):
        raise ConfigError(f"interval_seconds {s['interval_seconds']} out of range")
    if cfg["storage"]["retention_hours"] < 1:
        raise ConfigError("retention_hours must be >= 1")
    if cfg["display"]["default_tab"] not in {"dashboard", "temp", "power", "memory"}:
        raise ConfigError(f"invalid default_tab: {cfg['display']['default_tab']}")
    if cfg["display"]["default_time_window_hours"] not in {1, 4, 12, 24}:
        raise ConfigError("default_time_window_hours must be 1, 4, 12, or 24")

def load_config(path: str | None = None) -> "AppConfig":
    from nmon.models import AppConfig
    import pathlib
    raw = {}
    if path is None:
        for candidate in [pathlib.Path("config.toml"), pathlib.Path.home() / ".nmon" / "config.toml"]:
            if candidate.exists():
                path = str(candidate)
                break
    if path:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    cfg = _apply_defaults(raw)
    _validate(cfg)
    s, st, d = cfg["sampling"], cfg["storage"], cfg["display"]
    return AppConfig(
        interval_seconds=s["interval_seconds"],
        min_interval=s["min_interval"],
        max_interval=s["max_interval"],
        db_path=st["db_path"],
        retention_hours=st["retention_hours"],
        default_tab=d["default_tab"],
        default_time_window_hours=d["default_time_window_hours"],
    )
```

---

## Step 4 — gpu/base.py

```bash
aider --yes src/nmon/gpu/__init__.py src/nmon/gpu/base.py src/nmon/models.py
```
```
Create src/nmon/gpu/__init__.py as an empty file.

Create src/nmon/gpu/base.py:

from abc import ABC, abstractmethod
from nmon.models import GPUInfo, GPUSample

class GPUSourceError(RuntimeError): pass

class GPUSource(ABC):
    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def list_gpus(self) -> list[GPUInfo]: ...

    @abstractmethod
    def sample_all(self) -> list[GPUSample]: ...

    def close(self) -> None:
        pass
```

---

## Step 5 — gpu/nvml_source.py

```bash
aider --yes src/nmon/gpu/nvml_source.py src/nmon/gpu/base.py src/nmon/models.py
```
```
Create src/nmon/gpu/nvml_source.py implementing GPUSource using pynvml.

import time
import pynvml
from nmon.gpu.base import GPUSource, GPUSourceError
from nmon.models import GPUInfo, GPUSample

class NvmlSource(GPUSource):
    def __init__(self):
        self._initialized = False

    def is_available(self) -> bool:
        try:
            pynvml.nvmlInit()
            pynvml.nvmlShutdown()
            return True
        except Exception:
            return False

    def _ensure_init(self) -> None:
        if not self._initialized:
            try:
                pynvml.nvmlInit()
                self._initialized = True
            except pynvml.NVMLError as e:
                raise GPUSourceError(str(e)) from e

    def list_gpus(self) -> list[GPUInfo]:
        return [s.gpu for s in self.sample_all()]

    def sample_all(self) -> list[GPUSample]:
        self._ensure_init()
        try:
            count = pynvml.nvmlDeviceGetCount()
            ts = time.time()
            samples = []
            for i in range(count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                uuid = pynvml.nvmlDeviceGetUUID(handle)
                name = pynvml.nvmlDeviceGetName(handle)
                temp = float(pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU))
                mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                mem_used = mem.used / (1024 * 1024)
                mem_total = mem.total / (1024 * 1024)
                power = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0
                samples.append(GPUSample(
                    gpu=GPUInfo(index=i, uuid=uuid, name=name),
                    timestamp=ts,
                    temperature_c=temp,
                    memory_used_mib=mem_used,
                    memory_total_mib=mem_total,
                    power_draw_w=power,
                ))
            return samples
        except pynvml.NVMLError as e:
            raise GPUSourceError(str(e)) from e

    def close(self) -> None:
        if self._initialized:
            pynvml.nvmlShutdown()
            self._initialized = False
```

---

## Step 6 — gpu/smi_source.py

```bash
aider --yes src/nmon/gpu/smi_source.py src/nmon/gpu/base.py src/nmon/models.py
```
```
Create src/nmon/gpu/smi_source.py implementing GPUSource using nvidia-smi subprocess.

import subprocess, time, xml.etree.ElementTree as ET
from nmon.gpu.base import GPUSource, GPUSourceError
from nmon.models import GPUInfo, GPUSample

class SmiSource(GPUSource):
    SMI_TIMEOUT = 5

    def is_available(self) -> bool:
        try:
            r = subprocess.run(["nvidia-smi", "-L"], capture_output=True, timeout=3)
            return r.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _run_smi(self, args: list[str]) -> str:
        try:
            r = subprocess.run(["nvidia-smi"] + args, capture_output=True,
                               text=True, timeout=self.SMI_TIMEOUT)
        except FileNotFoundError as e:
            raise GPUSourceError("nvidia-smi not found") from e
        except subprocess.TimeoutExpired as e:
            raise GPUSourceError("nvidia-smi timed out") from e
        if r.returncode != 0:
            raise GPUSourceError(r.stderr)
        return r.stdout

    def _parse_xml(self, xml_text: str) -> list[GPUSample]:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            raise GPUSourceError(f"XML parse error: {e}") from e
        ts = time.time()
        samples = []
        for gpu in root.findall("gpu"):
            index = int(gpu.find("minor_number").text)
            uuid = gpu.find("uuid").text.strip()
            name = gpu.find("product_name").text.strip()
            temp = float(gpu.find("temperature/gpu_temp").text.split()[0])
            mem_used = float(gpu.find("fb_memory_usage/used").text.split()[0])
            mem_total = float(gpu.find("fb_memory_usage/total").text.split()[0])
            power = float(gpu.find("power_readings/power_draw").text.split()[0])
            samples.append(GPUSample(
                gpu=GPUInfo(index=index, uuid=uuid, name=name),
                timestamp=ts,
                temperature_c=temp,
                memory_used_mib=mem_used,
                memory_total_mib=mem_total,
                power_draw_w=power,
            ))
        return samples

    def list_gpus(self) -> list[GPUInfo]:
        return [s.gpu for s in self.sample_all()]

    def sample_all(self) -> list[GPUSample]:
        xml_text = self._run_smi(["--xml-format",
            "--query-gpu=gpu_name,uuid,temperature.gpu,memory.used,memory.total,power.draw"])
        return self._parse_xml(xml_text)
```

---

## Step 7 — storage.py

```bash
aider --yes src/nmon/storage.py src/nmon/models.py
```
```
Create src/nmon/storage.py.

import sqlite3, time
from typing import Literal
from nmon.models import GPUSample, HistoryRow, sample_to_row, row_to_sample

class StorageError(RuntimeError): pass

class Storage:
    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_schema()

    def _create_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS gpu_samples (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                gpu_index        INTEGER NOT NULL,
                gpu_uuid         TEXT    NOT NULL,
                gpu_name         TEXT    NOT NULL,
                timestamp        REAL    NOT NULL,
                temperature_c    REAL    NOT NULL,
                memory_used_mib  REAL    NOT NULL,
                memory_total_mib REAL    NOT NULL,
                power_draw_w     REAL    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_samples_gpu_time
                ON gpu_samples (gpu_index, timestamp);
        """)
        self._conn.commit()

    def insert_samples(self, samples: list[GPUSample]) -> None:
        rows = [sample_to_row(s) for s in samples]
        try:
            self._conn.executemany(
                "INSERT INTO gpu_samples (gpu_index,gpu_uuid,gpu_name,timestamp,"
                "temperature_c,memory_used_mib,memory_total_mib,power_draw_w) "
                "VALUES (:gpu_index,:gpu_uuid,:gpu_name,:timestamp,:temperature_c,"
                ":memory_used_mib,:memory_total_mib,:power_draw_w)",
                rows
            )
            self._conn.commit()
        except sqlite3.OperationalError as e:
            raise StorageError(str(e)) from e

    def prune_old(self, retention_hours: int) -> int:
        cutoff = time.time() - retention_hours * 3600
        cur = self._conn.execute("DELETE FROM gpu_samples WHERE timestamp < ?", (cutoff,))
        self._conn.commit()
        return cur.rowcount

    def get_current_stats(self, gpu_index: int) -> tuple[float, float] | None:
        now = time.time()
        cur = self._conn.execute(
            "SELECT MAX(CASE WHEN timestamp >= ? THEN temperature_c END),"
            "       AVG(CASE WHEN timestamp >= ? THEN temperature_c END)"
            " FROM gpu_samples WHERE gpu_index = ?",
            (now - 86400, now - 3600, gpu_index)
        )
        row = cur.fetchone()
        if row[0] is None:
            return None
        return float(row[0]), float(row[1])

    def get_history(
        self,
        gpu_index: int,
        metric: Literal["temperature_c", "memory_used_mib", "power_draw_w"],
        since: float,
    ) -> list[HistoryRow]:
        cur = self._conn.execute(
            f"SELECT timestamp, {metric} FROM gpu_samples "
            "WHERE gpu_index = ? AND timestamp >= ? ORDER BY timestamp ASC",
            (gpu_index, since)
        )
        return [HistoryRow(timestamp=r[0], value=r[1]) for r in cur.fetchall()]

    def close(self) -> None:
        self._conn.close()
```

---

## Step 8 — collector.py

```bash
aider --yes src/nmon/collector.py src/nmon/gpu/base.py src/nmon/storage.py src/nmon/models.py src/nmon/config.py
```
```
Create src/nmon/collector.py.

import threading, time, collections, logging
from nmon.gpu.base import GPUSource, GPUSourceError
from nmon.storage import Storage, StorageError
from nmon.models import GPUSample, AppConfig

log = logging.getLogger(__name__)

class Collector:
    def __init__(self, source: GPUSource, storage: Storage, config: AppConfig):
        self._source = source
        self._storage = storage
        self._interval = config.interval_seconds
        self._min = config.min_interval
        self._max = config.max_interval
        self._retention = config.retention_hours
        self._latest: list[GPUSample] | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_gpu_count: int | None = None
        self.warnings: collections.deque = collections.deque(maxlen=50)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def get_latest(self) -> list[GPUSample] | None:
        with self._lock:
            return self._latest

    def set_interval(self, seconds: int) -> None:
        with self._lock:
            self._interval = max(self._min, min(self._max, seconds))

    def _loop(self) -> None:
        while not self._stop.is_set():
            t0 = time.monotonic()
            try:
                samples = self._source.sample_all()
                count = len(samples)
                if self._last_gpu_count is not None and count != self._last_gpu_count:
                    msg = f"GPU count changed: {self._last_gpu_count} -> {count}"
                    log.warning(msg)
                    self.warnings.append(msg)
                self._last_gpu_count = count
                with self._lock:
                    self._latest = samples
                    interval = self._interval
                self._storage.insert_samples(samples)
                self._storage.prune_old(self._retention)
            except GPUSourceError as e:
                log.warning("GPU source error: %s", e)
            except StorageError as e:
                log.error("Storage error: %s", e)
            except Exception as e:
                log.error("Unexpected error in collector: %s", e)
            with self._lock:
                interval = self._interval
            elapsed = time.monotonic() - t0
            self._stop.wait(max(0.0, interval - elapsed))
```

---

## Step 9 — tui/widgets.py

```bash
aider --yes src/nmon/tui/__init__.py src/nmon/tui/widgets.py src/nmon/models.py
```
```
Create src/nmon/tui/__init__.py as an empty file.

Create src/nmon/tui/widgets.py with four Rich Renderable classes.

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
            # map data points to columns
            for col, val in enumerate(norm[:self.width]):
                row_idx = self.height - 1 - int(val // 4)
                dot_row = int(val % 4)
                if 0 <= row_idx < self.height:
                    grid[row_idx][col] |= BRAILLE[dot_row][0]
        lo = min(values) if values else 0
        hi = max(values) if values else 0
        mid = (lo + hi) / 2
        axis_vals = [hi, mid, lo]
        for r in range(self.height):
            line = Text()
            ax_label = f"{axis_vals[r * (self.height - 1) // max(self.height - 1, 1)]:.0f}" \
                if r in (0, self.height // 2, self.height - 1) else "   "
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
```

---

## Step 10 — tui/dashboard.py

```bash
aider --yes src/nmon/tui/dashboard.py src/nmon/tui/widgets.py src/nmon/models.py
```
```
Create src/nmon/tui/dashboard.py.

from rich.table import Table
from rich.panel import Panel
from rich.text import Text
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

def build_dashboard(stats: list[GPUStats], width: int = 80):
    if not stats:
        return Panel("No GPU data yet.", title="nmon")
    table = Table(show_header=True, header_style="bold cyan", expand=True)
    table.add_column("GPU", no_wrap=True)
    table.add_column("Temp", justify="right")
    table.add_column("Max 24h", justify="right")
    table.add_column("Avg 1h", justify="right")
    table.add_column("Memory", min_width=30)
    table.add_column("Power", justify="right")
    for s in stats:
        table.add_row(*build_gpu_row(s))
    return table
```

---

## Step 11 — tui/history.py

```bash
aider --yes src/nmon/tui/history.py src/nmon/tui/widgets.py src/nmon/storage.py src/nmon/models.py
```
```
Create src/nmon/tui/history.py.

import time
from typing import Literal
from rich.panel import Panel
from rich.text import Text
from nmon.models import GPUInfo
from nmon.storage import Storage
from nmon.tui.widgets import MultiSeriesChart

METRIC_CONFIG = {
    "temp":   {"column": "temperature_c",   "label": "Temperature", "unit": "°C"},
    "power":  {"column": "power_draw_w",    "label": "Power Draw",  "unit": "W"},
    "memory": {"column": "memory_used_mib", "label": "Memory Used", "unit": "MiB"},
}

TIME_WINDOWS = [1, 4, 12, 24]

GPU_COLORS = ["cyan", "magenta", "green", "yellow", "blue", "red"]

def format_time_window_tabs(current: int) -> str:
    parts = []
    for w in TIME_WINDOWS:
        parts.append(f"[{w}hr]" if w == current else f" {w}hr ")
    return "  ".join(parts)

def build_history(
    storage: Storage,
    gpu_list: list[GPUInfo],
    metric: Literal["temp", "power", "memory"],
    time_window_hours: int,
    width: int = 80,
    height: int = 10,
):
    cfg = METRIC_CONFIG[metric]
    since = time.time() - time_window_hours * 3600
    series = []
    for gpu in gpu_list:
        rows = storage.get_history(gpu.index, cfg["column"], since)
        color = GPU_COLORS[gpu.index % len(GPU_COLORS)]
        series.append((rows, gpu.name, color))
    chart = MultiSeriesChart(series, width - 10, height, cfg["unit"],
                             format_time_window_tabs(time_window_hours))
    window_bar = Text(format_time_window_tabs(time_window_hours), style="dim")
    title = f"{cfg['label']} History ({cfg['unit']})"
    return Panel(chart, title=title, subtitle=str(window_bar))
```

---

## Step 12 — tui/app.py

```bash
aider --yes src/nmon/tui/app.py src/nmon/tui/dashboard.py src/nmon/tui/history.py src/nmon/tui/widgets.py src/nmon/collector.py src/nmon/storage.py src/nmon/models.py src/nmon/config.py
```
```
Create src/nmon/tui/app.py.

import time, threading
import readchar
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

    def run(self) -> None:
        self._collector.start()
        key_thread = threading.Thread(target=self._handle_keys, daemon=True)
        key_thread.start()
        with Live(self._render(), refresh_per_second=2, screen=True) as live:
            while not self._quit:
                live.update(self._render())
                time.sleep(max(0.5, self._config.interval_seconds / 2))

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
            f"[{t.upper()}]" if t == tab else t.capitalize()
            for t in TABS
        )
        layout["header"].update(Text(f" nmon  {tabs_str}", style="bold"))
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
            try:
                key = readchar.readkey()
            except Exception:
                continue
            with self._lock:
                if key in ("q", readchar.key.CTRL_C):
                    self._quit = True
                elif key in ("1", "2", "3", "4"):
                    self._tab = TABS[int(key) - 1]
                elif key in ("[", readchar.key.LEFT):
                    idx = TIME_WINDOWS.index(self._time_window)
                    self._time_window = TIME_WINDOWS[max(0, idx - 1)]
                elif key in ("]", readchar.key.RIGHT):
                    idx = TIME_WINDOWS.index(self._time_window)
                    self._time_window = TIME_WINDOWS[min(len(TIME_WINDOWS) - 1, idx + 1)]
                elif key == "+":
                    self._collector.set_interval(self._collector._interval + 1)
                elif key == "-":
                    self._collector.set_interval(self._collector._interval - 1)

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
```

---

## Step 13 — __main__.py

```bash
aider --yes src/nmon/__main__.py src/nmon/tui/app.py src/nmon/collector.py src/nmon/storage.py src/nmon/gpu/nvml_source.py src/nmon/gpu/smi_source.py src/nmon/config.py
```
```
Create src/nmon/__main__.py.

import argparse, sys
from rich.console import Console
from nmon.config import load_config, ConfigError
from nmon.gpu.nvml_source import NvmlSource
from nmon.gpu.smi_source import SmiSource
from nmon.storage import Storage
from nmon.collector import Collector
from nmon.tui.app import NmonApp

console = Console()

def _pick_source():
    nvml = NvmlSource()
    if nvml.is_available():
        console.print("[green]Using pynvml[/green]")
        return nvml
    smi = SmiSource()
    if smi.is_available():
        console.print("[yellow]pynvml unavailable, using nvidia-smi[/yellow]")
        return smi
    return None

def main() -> None:
    parser = argparse.ArgumentParser(description="nmon — Nvidia GPU Monitor")
    parser.add_argument("--config", default=None, help="Path to config.toml")
    parser.add_argument("--interval", type=int, default=None)
    parser.add_argument("--db", default=None, help="Path to SQLite database")
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except ConfigError as e:
        console.print(f"[red]Config error:[/red] {e}")
        sys.exit(1)

    if args.interval is not None:
        config.interval_seconds = args.interval
    if args.db is not None:
        config.db_path = args.db

    source = _pick_source()
    if source is None:
        console.print("[red]No Nvidia GPU source available. "
                      "Install pynvml or ensure nvidia-smi is on PATH.[/red]")
        sys.exit(1)

    storage = Storage(config.db_path)
    collector = Collector(source, storage, config)
    app = NmonApp(collector, storage, config)
    try:
        app.run()
    finally:
        collector.stop()
        storage.close()
        source.close()

if __name__ == "__main__":
    main()
```

---

## Step 14 — Test fixtures

```bash
aider --yes tests/fixtures/smi_1gpu.xml tests/fixtures/smi_2gpu.xml
```
```
Create two nvidia-smi XML fixture files.

tests/fixtures/smi_1gpu.xml — one GPU:
- product_name: NVIDIA GeForce RTX 4090
- uuid: GPU-00000000-0000-0000-0000-000000000000
- minor_number: 0
- temperature/gpu_temp: 72 C
- fb_memory_usage/used: 4096 MiB, total: 24564 MiB
- power_readings/power_draw: 120.50 W

tests/fixtures/smi_2gpu.xml — two GPUs, same structure with a second <gpu>:
- product_name: NVIDIA GeForce RTX 3080
- uuid: GPU-11111111-1111-1111-1111-111111111111
- minor_number: 1
- temperature/gpu_temp: 65 C
- fb_memory_usage/used: 8192 MiB, total: 10240 MiB
- power_readings/power_draw: 220.00 W

Use the real nvidia-smi XML schema with <nvidia_smi_log> root element.
```

---

## Step 15 — conftest.py

```bash
aider --yes tests/conftest.py src/nmon/models.py src/nmon/storage.py
```
```
Create tests/conftest.py with these pytest fixtures:

import pytest, time, sys
from unittest.mock import MagicMock
from nmon.models import GPUInfo, GPUSample
from nmon.storage import Storage

@pytest.fixture
def in_memory_storage():
    s = Storage(":memory:")
    yield s
    s.close()

@pytest.fixture
def fake_gpu_info():
    return [
        GPUInfo(index=0, uuid="GPU-0000", name="RTX 4090"),
        GPUInfo(index=1, uuid="GPU-1111", name="RTX 3080"),
    ]

@pytest.fixture
def fake_sample(fake_gpu_info):
    def _make(gpu=None, timestamp=None, temp=72.0, mem_used=4096.0,
               mem_total=24564.0, power=120.0):
        return GPUSample(
            gpu=gpu or fake_gpu_info[0],
            timestamp=timestamp or time.time(),
            temperature_c=temp,
            memory_used_mib=mem_used,
            memory_total_mib=mem_total,
            power_draw_w=power,
        )
    return _make

@pytest.fixture
def fake_samples_batch(fake_gpu_info, fake_sample):
    now = time.time()
    return [fake_sample(timestamp=now - (2*3600 - i*720)) for i in range(10)]

@pytest.fixture
def mock_pynvml(monkeypatch):
    mock = MagicMock()
    monkeypatch.setitem(sys.modules, "pynvml", mock)
    return mock
```

---

## Step 16 — test_models.py

```bash
aider --yes tests/test_models.py src/nmon/models.py tests/conftest.py
```
```
Create tests/test_models.py with these three tests:

def test_memory_fraction_normal(fake_sample):
    s = fake_sample(mem_used=4096.0, mem_total=8192.0)
    assert s.memory_fraction == pytest.approx(0.5)

def test_memory_fraction_zero_total(fake_sample):
    s = fake_sample(mem_used=0.0, mem_total=0.0)
    assert s.memory_fraction == 0.0

def test_sample_to_row_roundtrip(fake_sample):
    from nmon.models import sample_to_row, row_to_sample
    s = fake_sample()
    assert row_to_sample(sample_to_row(s)) == s
```

---

## Step 17 — test_config.py

```bash
aider --yes tests/test_config.py src/nmon/config.py
```
```
Create tests/test_config.py covering:

- test_load_defaults: load_config(None) with no config file present returns
  AppConfig with interval_seconds=2, db_path="nmon.db", etc.
- test_load_valid_file: write a full valid TOML to tmp_path, load it, assert values.
- test_partial_file_merges_defaults: write TOML with only [sampling] interval_seconds=5,
  load it, assert interval=5 and other fields are defaults.
- test_invalid_interval_raises: write TOML with interval_seconds=0, assert ConfigError.
- test_invalid_tab_raises: write TOML with default_tab="foo", assert ConfigError.
- test_cli_override_wins: load_config returns config; manually override
  interval_seconds and assert it takes effect (simulates CLI override in __main__).

Use tmp_path fixture to write TOML files. Use pytest.raises(ConfigError).
```

---

## Step 18 — test_storage.py

```bash
aider --yes tests/test_storage.py src/nmon/storage.py src/nmon/models.py tests/conftest.py
```
```
Create tests/test_storage.py covering all cases from the architecture section 7.3:

- test_schema_creates_on_init
- test_insert_and_retrieve_single_sample
- test_insert_multiple_gpus
- test_prune_removes_old_rows
- test_prune_returns_count
- test_get_current_stats_empty
- test_get_current_stats_24h_max
- test_get_current_stats_1h_avg
- test_get_history_ordered_by_time
- test_get_history_respects_since
- test_concurrent_read_write (writer and reader threads for 1 second, assert no exceptions)

Use in_memory_storage and fake_sample fixtures.
```

---

## Step 19 — test_gpu_smi.py

```bash
aider --yes tests/test_gpu_smi.py src/nmon/gpu/smi_source.py src/nmon/gpu/base.py tests/conftest.py
```
```
Create tests/test_gpu_smi.py covering all cases from architecture section 7.6.
Mock subprocess.run via unittest.mock.patch. Load fixture XML from
tests/fixtures/smi_1gpu.xml and smi_2gpu.xml using pathlib.Path(__file__).
Cover: is_available true/false/missing binary, parse 1 and 2 GPUs, malformed
XML, subprocess timeout, nonzero exit code.
```

---

## Step 20 — test_gpu_nvml.py

```bash
aider --yes tests/test_gpu_nvml.py src/nmon/gpu/nvml_source.py src/nmon/gpu/base.py tests/conftest.py
```
```
Create tests/test_gpu_nvml.py covering all cases from architecture section 7.5.
Use the mock_pynvml fixture. Cover: is_available true/false, list_gpus 1 and 2
GPUs, sample_all value extraction with correct unit conversion (bytes→MiB,
mW→W), NVMLError wrapped as GPUSourceError, close() calls nvmlShutdown once,
close() is idempotent.
```

---

## Step 21 — test_collector.py

```bash
aider --yes tests/test_collector.py src/nmon/collector.py src/nmon/gpu/base.py src/nmon/storage.py src/nmon/models.py src/nmon/config.py tests/conftest.py
```
```
Create tests/test_collector.py covering all cases from architecture section 7.4.
Use MagicMock for GPUSource and Storage. Use a pytest fixture that creates the
collector and ensures collector.stop() is called in teardown. Cover: start/stop
thread lifecycle, get_latest before/after first sample, GPUSourceError does not
crash loop, StorageError does not crash loop, set_interval clamps to min and max,
GPU count change adds to collector.warnings.
```

---

## Step 22 — test_tui_widgets.py

```bash
aider --yes tests/test_tui_widgets.py src/nmon/tui/widgets.py src/nmon/models.py tests/conftest.py
```
```
Create tests/test_tui_widgets.py covering all cases from architecture section 7.7.
Render each widget using:
    from io import StringIO
    from rich.console import Console
    console = Console(file=StringIO(), width=80)
    with console.capture() as cap:
        console.print(widget)
    output = cap.get()
Then assert expected substrings appear in output.
```

---

## Step 23 — test_tui_dashboard.py

```bash
aider --yes tests/test_tui_dashboard.py src/nmon/tui/dashboard.py src/nmon/models.py tests/conftest.py
```
```
Create tests/test_tui_dashboard.py covering all cases from architecture section 7.8.
Use StringIO-backed Console to capture output. Cover empty stats list, single GPU
values appear in output, temperature color styles for green/yellow/red thresholds.
```

---

## Step 24 — test_tui_history.py

```bash
aider --yes tests/test_tui_history.py src/nmon/tui/history.py src/nmon/storage.py src/nmon/models.py tests/conftest.py
```
```
Create tests/test_tui_history.py covering all cases from architecture section 7.9.
Mock storage.get_history() to return canned HistoryRow lists. Assert chart title,
y-axis unit label, and time window tab formatting. Include empty data case.
```

---

## Step 25 — test_integration.py + final check

```bash
aider --yes tests/test_integration.py src/nmon/collector.py src/nmon/storage.py src/nmon/gpu/base.py src/nmon/models.py src/nmon/config.py tests/conftest.py
```
```
Create tests/test_integration.py covering all cases from architecture section 7.10.

Use real in-memory Storage (in_memory_storage fixture) and a MagicMock GPUSource
configured to return deterministic GPUSample lists. Run the collector for exactly
3 cycles by using threading.Event to count calls, then stop it. Assert:
- test_sample_stored_and_retrievable: get_history returns the inserted rows in order
- test_pruning_removes_old_data: rows older than retention are removed by prune_old
- test_multi_gpu_isolation: get_history(gpu_index=0) returns only GPU 0 rows

After creating the file, run pytest tests/ -v and fix any failures.
```
