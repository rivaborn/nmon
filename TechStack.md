# nmon — Tech Stack and Internals

This document describes how nmon is put together: the runtime stack, the
module responsibilities, how a sample flows from the driver to the
screen, and the empirical findings behind the NVAPI fallback that reads
GPU memory junction temperature on consumer GeForce cards.

---

## 1. Runtime Stack

| Layer | Choice | Why |
|-------|--------|-----|
| Language | Python ≥ 3.10 | stdlib dataclasses, `tomllib`, modern typing, `sqlite3` |
| GPU telemetry (primary) | `nvidia-ml-py` (NVML) | Official, low-overhead, cross-platform |
| GPU telemetry (Windows fallback) | `nvapi64.dll` via `ctypes` | Reads GDDR6/6X memory junction temp that NVML hides on GeForce |
| GPU telemetry (last-resort fallback) | `nvidia-smi --xml-format` subprocess | Works anywhere `nvidia-smi` is on `PATH` |
| Persistence | SQLite (`sqlite3` stdlib) in WAL mode | Zero external services, concurrent reader + writer |
| TUI framework | `rich` (`Live`, `Layout`, `Table`, `Panel`, custom renderables) | Mature, composable, good Windows support |
| Charting | Custom Braille-dot renderer (U+2800–U+28FF) | Self-contained, no plotting dependency |
| Keyboard input | `msvcrt` (Windows) | Non-blocking single-key reads without raw-mode wrangling |
| Config | TOML via `tomllib` | Stdlib in 3.11+, simple schema |
| Packaging | `setuptools` + `pyproject.toml`, editable install | Fast local iteration |

Explicitly rejected: `asyncio` (threading is simpler for two concurrent
tasks), `plotext` (in-house Braille rendering is ~60 lines), `textual`
(rich alone is enough for this layout), `click` (argparse is fine).

---

## 2. Process and Threading Model

nmon runs as a single process with three threads:

```
┌────────────────────────────────────────────────────────────┐
│                        main thread                         │
│                                                            │
│   rich.live.Live render loop                               │
│     - reads collector.get_latest()  (lock-protected)       │
│     - reads storage.get_current_stats / get_history        │
│     - builds a Layout and calls Live.update()              │
│     - sleeps until _redraw event or interval/2             │
└────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│                   collector thread (daemon)                │
│                                                            │
│   every N seconds:                                         │
│     samples = GPUSource.sample_all()                       │
│     publish to _latest slot (under _lock)                  │
│     Storage.insert_samples(samples)                        │
│     Storage.prune_old(retention_hours)                     │
│   never lets exceptions escape the loop — catches          │
│   GPUSourceError / StorageError, logs to a bounded         │
│   deque, continues.                                        │
└────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│                    key thread (daemon)                     │
│                                                            │
│   polls msvcrt.kbhit() at 20 Hz, dispatches keys to        │
│   the app state under _lock, sets _redraw to kick the      │
│   main thread out of its sleep.                            │
└────────────────────────────────────────────────────────────┘
```

Concurrency primitives:

- `threading.Lock` protects the app state (current tab, time window,
  show-junction toggle) and the collector's `_latest` slot and
  `_interval`.
- `threading.Event` (`_redraw`, `_stop`) lets the key thread wake the
  render loop and the main thread cleanly stop the collector.
- SQLite is opened with `check_same_thread=False` and `PRAGMA
  journal_mode=WAL`, so the collector (writer) and TUI (reader) never
  block each other.

Why threads and not async: the workload is two bounded periodic tasks
plus one blocking keyboard reader. Async adds scheduling overhead and
makes the Rich `Live` + `ctypes` paths clunkier without any concurrency
benefit at this scale.

---

## 3. Project Layout

```
nmon/
├── pyproject.toml              editable install, entry point nmon=nmon.__main__:main
├── config.toml                 user-editable runtime config with defaults
├── nmon.db                     SQLite file (auto-created, gitignored)
├── src/nmon/
│   ├── __main__.py             CLI parsing, source selection, wiring
│   ├── config.py               TOML loading, validation, defaults
│   ├── models.py               Dataclasses and TypedDicts
│   ├── storage.py              SQLite schema, insert, query, prune
│   ├── collector.py            Background sampling thread
│   ├── gpu/
│   │   ├── base.py             GPUSource abstract contract
│   │   ├── nvml_source.py      pynvml implementation + NVAPI fallback wiring
│   │   ├── smi_source.py       nvidia-smi subprocess fallback
│   │   └── nvapi.py            NVAPI ctypes wrapper (Windows, memory junction)
│   └── tui/
│       ├── app.py              NmonApp: Live loop, key dispatcher, tab router
│       ├── dashboard.py        Screen 1: GPU status + junction temp tables
│       ├── history.py          Screens 2–4: history chart panels
│       └── widgets.py          MemoryBar, BrailleChart, MultiSeriesChart, StatusBar
└── tests/                      pytest, in-memory DB fixtures, XML fixture files
```

---

## 4. Data Flow

### 4.1 Sample path (writer)

```
GPUSource.sample_all()  →  list[GPUSample]
                             │
                             ▼
              Collector.get_latest() slot   (lock-protected, TUI reads this)
                             │
                             ▼
              Storage.insert_samples()      (single transaction)
                             │
                             ▼
              Storage.prune_old()           (rows older than retention_hours)
```

`GPUSample` carries:

```python
gpu: GPUInfo                    # index, uuid, name
timestamp: float                # Unix epoch
temperature_c: float            # core temp
memory_used_mib: float
memory_total_mib: float
power_draw_w: float
memory_junction_temp_c: float | None   # VRAM junction, None on unsupported cards
```

### 4.2 Render path (reader)

```
collector.get_latest()             → current list[GPUSample]
storage.get_current_stats(i)       → (max_temp_24h, avg_temp_1h,
                                      junction_max_24h, junction_avg_1h)
storage.get_history(i, metric, t)  → list[HistoryRow]
                             │
                             ▼
         dashboard.build_dashboard() | history.build_history()
                             │
                             ▼
                     rich.live.Live.update()
```

---

## 5. Storage Schema

Single table. A composite index covers every query pattern.

```sql
CREATE TABLE IF NOT EXISTS gpu_samples (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    gpu_index              INTEGER NOT NULL,
    gpu_uuid               TEXT    NOT NULL,
    gpu_name               TEXT    NOT NULL,
    timestamp              REAL    NOT NULL,   -- Unix epoch, seconds
    temperature_c          REAL    NOT NULL,
    memory_used_mib        REAL    NOT NULL,
    memory_total_mib       REAL    NOT NULL,
    power_draw_w           REAL    NOT NULL,
    memory_junction_temp_c REAL                -- NULL = sensor unsupported
);
CREATE INDEX IF NOT EXISTS idx_samples_gpu_time
    ON gpu_samples (gpu_index, timestamp);
```

The `memory_junction_temp_c` column was added after the initial release.
`Storage._create_schema()` runs `ALTER TABLE ... ADD COLUMN` inside a
try/except so upgrading an existing `nmon.db` is a no-op if the column
already exists.

`get_current_stats()` returns four aggregates in a single query so the
dashboard avoids repeated round trips:

```sql
SELECT MAX(CASE WHEN timestamp >= ? THEN temperature_c END),
       AVG(CASE WHEN timestamp >= ? THEN temperature_c END),
       MAX(CASE WHEN timestamp >= ? THEN memory_junction_temp_c END),
       AVG(CASE WHEN timestamp >= ? THEN memory_junction_temp_c END)
  FROM gpu_samples WHERE gpu_index = ?;
```

`get_history()` filters `WHERE metric IS NOT NULL` so the junction
column's NULLs on unsupported GPUs don't show up as gaps in the chart.

---

## 6. GPU Source Abstraction

`gpu/base.py` defines a minimal contract:

```python
class GPUSource(ABC):
    def is_available(self) -> bool: ...
    def list_gpus(self) -> list[GPUInfo]: ...
    def sample_all(self) -> list[GPUSample]: ...   # raises GPUSourceError
    def close(self) -> None: ...
```

Two implementations:

- **`NvmlSource`** — uses `nvidia-ml-py`. Reads core temp, memory info,
  and power via NVML. For memory junction temperature, it tries NVML's
  `NVML_FI_DEV_MEMORY_TEMP` field first; if NVML returns
  `NVML_ERROR_NOT_SUPPORTED` (the common case on consumer GeForce
  cards), it falls back to `nvapi.read_memory_junction_temp()`. Failed
  lookups are cached per GPU index so repeated samples don't re-probe
  unsupported hardware.
- **`SmiSource`** — used when NVML isn't available. Shells out to
  `nvidia-smi --xml-format --query-gpu=...` and parses the XML. Does
  not attempt memory junction temperature.

`__main__._pick_source()` prefers NVML and falls back to SMI.

---

## 7. TUI

### 7.1 Tabs

```
 nmon  [DASHBOARD]  Temp  Power  Memory
```

- **1 Dashboard** — a `rich.table.Table` of current GPU status stacked
  above a second `Table` that shows memory junction temperature for the
  GPUs that expose it. Stacking is done with `rich.console.Group`; the
  second table is omitted when no GPU reports junction temp or when the
  user toggles it off.
- **2 Temp** — line chart of core temperature over the selected time
  window. Memory junction temperature is overlaid on the same chart in
  bright red when available.
- **3 Power** — line chart of power draw.
- **4 Memory** — line chart of VRAM usage.

### 7.2 Keyboard controls

| Key | Action |
|-----|--------|
| `1`–`4` | Switch tabs |
| `+` / `-` | Sampling interval |
| `[` / `]` or `←` / `→` | History time window (1 / 4 / 12 / 24 hr) |
| `j` | Toggle junction-temp display on dashboard and temp chart |
| `q` or Ctrl+C | Quit |

### 7.3 Braille charts

`widgets.BrailleChart` renders one or more time series onto a shared
axis using the 2×4 dot grid of Unicode Braille characters
(U+2800–U+28FF). Each column of the chart is one character cell; each
cell contains up to 8 dots. The current implementation uses only the
left column of each Braille cell (four vertical positions), which keeps
the rendering simple and legible on all fonts.

- **Shared axis** — when multiple series are overlaid (core + junction
  on the temp tab), the chart computes `lo` / `hi` across every value
  in every series so the Y scale is common.
- **Column mapping** — the `width` of the chart is mapped evenly across
  all data points, so narrowing the chart compresses the time series
  rather than truncating it.
- **Overlay priority** — when cells from multiple series land on the
  same `(row, col)`, the series drawn last wins. In practice the two
  series are offset enough that overlap is rare.

`widgets.MultiSeriesChart` stacks one `BrailleChart` per GPU so each
GPU gets its own axis label strip, while overlays (core + junction)
share a chart within that GPU's strip.

Chart panel footers show how much *actually collected* history is in
the current view, formatted as `Hh Mm Ss` — computed from the span
between the earliest and latest timestamps in the rendered series, not
the configured time window.

---

## 8. NVAPI Memory Junction Fallback

This section documents the reverse-engineering findings that made
memory junction temperature work on consumer GeForce cards.

### 8.1 The problem

NVML exposes memory junction temperature via the field-value API:

```python
pynvml.nvmlDeviceGetFieldValues(handle, [pynvml.NVML_FI_DEV_MEMORY_TEMP])
```

On data-center GPUs (A100, H100, etc.) and some workstation cards this
works. On consumer GeForce cards — **including cards with a real
GDDR6/6X junction sensor like the RTX 3080 / 3090 / 4080 / 4090** —
NVML returns `NVML_ERROR_NOT_SUPPORTED (3)` even though the sensor
exists in hardware.

Third-party tools (HWiNFO, GPU-Z, MSI Afterburner) read the same
sensor via NVAPI — Nvidia's Windows-only C API — using an undocumented
thermal channel function. nmon's `gpu/nvapi.py` implements that path in
pure-Python `ctypes`.

### 8.2 NVAPI basics

NVAPI exposes a single entry point, `nvapi_QueryInterface(function_id)
→ void*`. Every other function is resolved by passing a 32-bit id and
getting back a function pointer. The public ids we use:

| Id | Function | Status |
|----|----------|--------|
| `0x0150E828` | `NvAPI_Initialize` | documented |
| `0xE5AC921F` | `NvAPI_EnumPhysicalGPUs` | documented |
| `0xE3640A56` | `NvAPI_GPU_GetThermalSettings` | documented, only reports core |
| `0x65FE3AAD` | `NvAPI_GPU_ThermChannelGetStatus` | **undocumented, reports all channels including memory junction** |

`NvAPI_GPU_ThermChannelGetStatus` takes a physical GPU handle and a
pointer to a versioned struct. The version field encodes both the
version number (upper 16 bits) and the struct size in bytes (lower 16
bits):

```
version_tag = struct_size | (version_number << 16)
```

### 8.3 The struct and the investigation

The struct layout, mask semantics, and unit of the temperature field
are **not documented**. What worked, and how we found each piece:

**Struct size and version — `0x000200a8` (v2, 168 bytes)**

When nmon first tried this call, the diagnostic caught a debug string
printed by the Nvidia driver itself to stderr:

```
NvAPI_GPU_ThermChannelGetStatus received version: 10088
While allowed versions are as below
Ver-1:1003c   Ver-2:200a8   Ver-3:334c8
```

Decoded:

- Received `0x10088` = v1 with 136 bytes → **rejected**
- Accepted `0x1003c` = v1, 60 bytes
- Accepted `0x200a8` = v2, **168 bytes** (the sweet spot we target)
- Accepted `0x334c8` = v3, 13512 bytes (richer metadata, not needed)

That error message was the Rosetta Stone. It confirmed we needed
exactly 168 bytes with version 2 in the upper half of the version word.

**Field layout — `(mask: u32, reserved: u32[8], temperatures: i32[32])`**

With the size pinned, the question was what lived *inside* those 168
bytes. The probe tried two candidate layouts:

```
layout A:  version(4) + mask(4) + temps[32](128) + reserved[8](32)  →  temps@8
layout B:  version(4) + mask(4) + reserved[8](32) + temps[32](128)  →  temps@40
```

Both returned `status=0` (the driver doesn't validate internal layout),
but only **layout B (temps@40)** produced plausible values that
cross-referenced against the documented GPU core temperature. In
layout A the values were scattered and didn't match the documented
core temp.

**Mask — `0xFF`, not `0xFFFFFFFF`**

Initial attempts with `mask = 0xFFFFFFFF` (request all 32 channels)
returned `-1 (NVAPI_ERROR)`. The probe iterated through masks
`0x01, 0x0F, 0xFF, 0xFFFFFFFF` and found that the driver rejects any
mask that asks for channels the card doesn't have. On the RTX 3080
Laptop tested, exactly 8 channels are populated, so `mask = 0xFF` is
the widest accepted value. Production uses `0xFF` with a graceful
fallback through `0x1F, 0x0F, 0x03, 0x01` in case some card has even
fewer.

**Unit — Q8.8 fixed point (divide raw by 256)**

Several published reverse-engineering notes claim the values are in
milli-degrees Celsius (divide by 1000). This is **wrong** for this
function. With the right struct layout and mask, the first sensor of
the RTX 3080 Laptop returned `raw = 16648` while the documented
thermal settings call reported `current = 65°C`. The math:

```
16648 / 256 = 65.03    ← matches
16648 / 1000 = 16.65   ← nonsense
```

`16648 = 0x4108`, upper byte `0x41 = 65` (whole degrees), lower byte
`0x08 = 8 / 256 = 0.03` (fractional). That's Q8.8 fixed point: 8 bits
of integer degrees, 8 bits of fraction. Production divides raw values
by `256.0`.

**Channel index — empirical**

The eight channels on a typical Ampere card look like this under idle
conditions when the GPU core is at 65°C:

```
sensor[ 0] =  65.03C    <-- matches GPU core
sensor[ 1] =  71.19C    <-- core + 6.2C (memory junction)
sensor[ 2] =  65.03C    <-- matches GPU core
sensor[ 3] =  65.06C    <-- matches GPU core
sensor[ 4] =  70.06C    <-- core + 5.1C (hotspot)
sensor[ 5] =  65.03C    <-- matches GPU core
sensor[ 6] =  68.91C    <-- core + 3.9C (VRM)
sensor[ 7] =  66.69C    <-- matches GPU core
```

Channel `1` is the memory junction on every Ampere / Ada consumer card
tested. nmon reads that index by default; if a new card orders them
differently the `_SENSOR_INDEX_MEMORY` constant in `gpu/nvapi.py` is
the one knob to change.

### 8.4 Production parameters

All of the above collapses to a short, concrete set of constants:

```python
_NVAPI_GPU_CLIENT_THERMAL_SENSORS_GET_VALUES = 0x65FE3AAD  # function id
_V2_VERSION  = 168 | (2 << 16)                             # 0x000200a8
_SENSOR_MASKS = (0xFF, 0x1F, 0x0F, 0x03, 0x01)             # widest first
_TEMP_DIVISOR = 256.0                                       # Q8.8 fixed point
_SENSOR_INDEX_MEMORY = 1                                    # memory junction channel

class _NvGpuClientThermalSensors(ctypes.Structure):
    _fields_ = [
        ("version",      ctypes.c_uint32),
        ("mask",         ctypes.c_uint32),
        ("reserved",     ctypes.c_uint32 * 8),
        ("temperatures", ctypes.c_int32  * 32),
    ]
```

### 8.5 Diagnostic entry point

`python -m nmon.gpu.nvapi` prints, for each GPU:

- The documented `NvAPI_GPU_GetThermalSettings` output as a reference
  (GPU core temp in whole degrees).
- The undocumented `NvAPI_GPU_ThermChannelGetStatus` output with every
  populated channel shown in Q8.8 decoded form, auto-labeled by
  difference from the documented core temp. Channels within 2°C of
  core are tagged "matches GPU core"; hotter channels are tagged with
  the delta and an educated guess ("likely memory/hotspot").

This same diagnostic was how the layout / mask / divisor / index were
each nailed down in turn — keeping it in the tree means the next
unsupported card can be diagnosed without re-running the investigation
from scratch.

### 8.6 Failure modes and fallthrough

Every step of the NVAPI call path is wrapped so failure returns `None`
instead of raising:

1. Non-Windows platform → `nvapi64.dll` is never loaded.
2. `nvapi64.dll` missing → `OSError` caught at load time.
3. `nvapi_QueryInterface` export missing → handled.
4. `NvAPI_Initialize` returns non-zero → handled.
5. `NvAPI_EnumPhysicalGPUs` returns non-zero or fewer GPUs than NVML →
   unsupported index cached.
6. All sensor masks rejected → unsupported index cached.
7. Channel `_SENSOR_INDEX_MEMORY` reports `0` → treated as "sensor not
   wired on this card" and cached.

Any cached "unsupported" GPU is never re-probed for the remainder of
the process — one failed call costs at most a few microseconds per
sample on repeat.

The net effect: nmon never crashes or slows down on cards without a
junction sensor; it just silently omits the junction dashboard section
and chart overlay for those cards.

---

## 9. Configuration

`config.toml` in the project root (or `~/.nmon/config.toml`) with
command-line overrides via `argparse`:

```toml
[sampling]
interval_seconds = 2        # poll cadence; clamped to [min_interval, max_interval]
min_interval     = 1
max_interval     = 60

[storage]
db_path         = "nmon.db"
retention_hours = 24        # pruned on every write cycle

[display]
default_tab               = "dashboard"
default_time_window_hours = 1
```

CLI overrides: `--config PATH`, `--interval N`, `--db PATH`. Applied
after file parsing, so CLI wins.

---

## 10. Dependencies

```toml
dependencies = [
    "rich>=13.7",
    "nvidia-ml-py>=12.0",    # (pyproject currently pins pynvml — see note)
    "readchar>=4.0.5",
    "tomli>=2.0.1; python_version < '3.11'",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-mock>=3.12", "coverage>=7.4"]
```

NVAPI has no Python package — it's called directly through `ctypes`
against `nvapi64.dll` shipped with the Nvidia driver, so it adds
nothing to `pyproject.toml`.

---

*End of tech stack document.*
