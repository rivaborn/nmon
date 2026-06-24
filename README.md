# nmon — Nvidia GPU Monitor

A terminal dashboard for NVIDIA GPUs. Live temperatures, memory, and power
across every visible card; per-metric history charts rendered with Braille
dots; persistent SQLite-backed time series; and zero-config detection of
local Ollama and vLLM servers with whatever model is currently loaded.

Tested on Windows 11 with consumer GeForce hardware (RTX 30/40 series).
The Linux-friendly `nvidia-smi` fallback path exists but the TUI key
handling currently uses `msvcrt`, so the interactive UI is Windows-only
for now.

---

## Features

- **Multi-GPU live dashboard.** Per-GPU current temp, 24-hour max, 1-hour
  average, memory bar, and instantaneous power draw, refreshed at the
  sampling interval.
- **GPU Hot Spot and GDDR6X memory junction temps.** Read via NVAPI on
  Windows (NVML doesn't surface these on consumer cards). Both have
  their own dashboard sub-tables and history series. Either can be
  toggled off.
- **History tabs with Braille charts.** Temperature, power, and memory
  history per GPU at four time windows (1, 4, 12, 24 hours). The
  temperature chart overlays core + hotspot + junction on one axis with
  an optional horizontal threshold line.
- **Adjustable temperature threshold line.** Move it up or down with
  the arrow keys on the Temp tab; the value persists across restarts
  next to the SQLite database.
- **Ollama integration.** If an Ollama server is reachable at startup,
  the dashboard gains an "Ollama Server" section showing the loaded
  model, size, and GPU/CPU split. A red banner appears at the top of
  the screen whenever the model is partially offloaded to CPU/system
  RAM. The LLM history tab charts the GPU% / CPU% split over time.
- **vLLM integration.** If a vLLM server is reachable at startup, the
  dashboard gains a "vLLM Server" section showing the served model.
  vLLM keeps its model pinned in VRAM, so there is no offload split or
  history to chart — just a single line confirming what is loaded.
- **Persistent SQLite storage.** All GPU samples and Ollama samples
  are inserted on every tick. Old rows are pruned to the configured
  retention window automatically.
- **Single binary entry point.** `pip install -e .` and run `nmon`.
- **Stdlib-only HTTP clients.** Ollama and vLLM are queried with
  `urllib`; no extra HTTP dependencies.

---

## Requirements

- Python 3.10 or newer.
- NVIDIA driver and at least one of:
  - `pynvml` / `nvidia-ml-py` for the fast path (preferred), or
  - `nvidia-smi` on `PATH` for the fallback.
- Windows for the interactive TUI (the keyboard input layer uses
  `msvcrt`). The collector and storage layers run anywhere.
- Optional: a local Ollama server on `http://localhost:11434`.
- Optional: a local vLLM server on `http://localhost:8000`.

Dependencies declared in `pyproject.toml`: `rich`, `pynvml`, `readchar`,
plus `tomli` on Python 3.10.

---

## Install

```powershell
git clone <repo-url> nmon
cd nmon
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

`-e` (editable) installs the package so edits in `src/nmon/` take effect
without reinstalling. After this, the `nmon` command lives in
`.venv\Scripts\` and is on `PATH` while the venv is active.

---

## Run

```powershell
nmon
```

On startup, nmon prints a one-line status for each subsystem before
opening the TUI:

```
Using pynvml
Ollama detected at http://localhost:11434
vLLM detected at http://localhost:8000
```

If either LLM server is unreachable, the corresponding line is dimmed
and the matching dashboard section is hidden until the server is
detected. The collector re-probes a missing server roughly once a
minute, so a server started after nmon will appear without a restart.

### CLI flags

| Flag                  | Effect                                              |
| --------------------- | --------------------------------------------------- |
| `--config <path>`     | Path to a `config.toml` (default: see below).       |
| `--interval <int>`    | Override the sampling interval in seconds.          |
| `--db <path>`         | Override the SQLite database path.                  |
| `-h`, `--help`        | Show the argparse usage.                            |

---

## The TUI

The status bar at the bottom shows the live keybindings. A condensed
reference:

| Key               | Action                                              |
| ----------------- | --------------------------------------------------- |
| `1` … `5`         | Switch tab: Dashboard, Temp, Power, Memory, LLM.    |
| `[` / `]` or `←`/`→` | Cycle history time window: 1 / 4 / 12 / 24 hours. |
| `+` / `-`         | Increase / decrease sampling interval (1 s steps).  |
| `h`               | Toggle hotspot temp display.                        |
| `j`               | Toggle memory junction temp display.                |
| `t`               | Toggle the temperature threshold line (Temp tab).   |
| `↑` / `↓`         | Move threshold line ±0.5 °C (Temp tab only).        |
| `q`, `Ctrl+C`, `Ctrl+Q` | Quit.                                         |

### Tabs

- **Dashboard.** One row per GPU with name, current temp, 24-hour max,
  1-hour average, a memory bar (`used / total MiB` plus a filled-block
  indicator), and instantaneous power. If hotspot or memory junction
  temps are available, they appear as separate three-column tables
  below. If an Ollama or vLLM server is detected, a section per server
  appears below the GPU tables.
- **Temp.** Per-GPU temperature history. Each card's chart can overlay
  three series (core, hotspot, junction) and the threshold line.
- **Power.** Per-GPU power history.
- **Memory.** Per-GPU VRAM usage history (MiB).
- **LLM.** GPU% vs CPU% history of the Ollama model — drawn from the
  `ollama_samples` table the collector populates whenever a model is
  loaded.

### The "GPU OFFLOADING" banner

Whenever the Ollama poll observes a model with `size_vram < size`, a
banner stretches across the top of the screen for at least one second.
The banner is dark-orange when the CPU spillover is ≤ 5 % and switches
to red on white when it exceeds that. The banner colour tracks the
worst observation in the current display window, so a brief sample
with less spillover does not downgrade the warning until the hold
window expires.

---

## Configuration

nmon looks for `config.toml` in this order:

1. The path passed via `--config <path>`.
2. `./config.toml` in the current working directory.
3. `~/.nmon/config.toml`.

Missing keys or missing sections fall through to the built-in defaults,
so a partial file is fine.

```toml
[sampling]
interval_seconds = 2          # How often we sample.
min_interval     = 1          # Lower bound for the `+`/`-` keybindings.
max_interval     = 60         # Upper bound.

[storage]
db_path         = "nmon.db"   # SQLite database location.
retention_hours = 24          # Anything older is pruned each tick.

[display]
default_tab               = "dashboard"   # dashboard | temp | power | memory | llm
default_time_window_hours = 1             # 1 | 4 | 12 | 24
temp_threshold_c          = 95.0          # First-run threshold-line value.
show_temp_threshold       = true          # First-run threshold-line visibility.

[ollama]
enabled = true
url     = "http://localhost:11434"

[vllm]
enabled = true
url     = "http://localhost:8000"
```

### Runtime state

Some TUI settings — the temperature threshold value and its on/off
toggle — are written by nmon itself to a small JSON file next to the
database:

```
<db_dir>/.nmon_state.json
```

This file overrides the `[display]` defaults on the next startup. It
exists so that the user's runtime tweaks survive restarts without
having to hand-edit `config.toml`. Failures to read or write it are
swallowed; nmon falls back to the configured defaults.

---

## GPU data sources

nmon picks the first available source at startup:

1. **`pynvml`** (preferred). Direct NVML bindings, no subprocess.
   Provides core temperature, VRAM usage, and power draw on every
   supported GPU. Also queries `NVML_FI_DEV_MEMORY_TEMP` for the
   memory junction sensor on data-center cards.
2. **`nvidia-smi`** (fallback). Shells out to the binary with
   `--xml-format`. Provides the same four core metrics. No NVAPI
   integration on this path, so hotspot and junction temps are
   unavailable.

### NVAPI for hotspot and GDDR6X memory junction

On Windows, NVML does not expose the GPU hotspot temperature, and
returns `NOT_SUPPORTED` for memory temp on most consumer GeForce cards.
nmon falls back to the undocumented but stable
`NvAPI_GPU_ClientThermalSensors_GetValues` call to read them directly
from `nvapi64.dll`. This is the same entry point HWiNFO and GPU-Z use.

Channel indices were verified against Ampere/Ada cards:

- Index 0: GPU core (matches NVML's documented value).
- Index 1: GPU Hot Spot.
- Index 9: GDDR6X memory junction.

If your card maps these differently, run

```powershell
python -m nmon.gpu.nvapi
```

The diagnostic prints every populated channel with its delta from the
documented GPU core temperature, plus a hint for which indices to edit
in `src/nmon/gpu/nvapi.py`.

---

## LLM server integration

### Ollama

Polled every sampling tick via `GET /api/ps`. The first model in the
response is surfaced on the dashboard with:

- Total model size (bytes formatted as KiB/MiB/GiB).
- `size_vram / size`: the GPU% / CPU% split. Green when the model is
  fully in VRAM, red when any part has spilled to system RAM.

Every sample is inserted into the `ollama_samples` SQLite table, so
the LLM history tab can chart GPU% vs CPU% over the chosen time
window. Pruning matches the GPU samples retention.

The startup probe and per-tick poll both use 0.5 s HTTP timeouts and
swallow all exceptions, so a stopped Ollama server cannot stall or
crash the TUI.

### vLLM

Polled every sampling tick via `GET /v1/models` (OpenAI-compatible).
The first model in the response is surfaced on the dashboard with its
ID and a "loaded" status. vLLM allocates VRAM up-front and does not
support partial CPU offload, so there is no GPU/CPU split to display
and no history is recorded.

The same conventions apply as Ollama: 0.5 s timeout, all errors
swallowed, dashboard section silently absent when the server is down.

---

## Storage

SQLite, opened with WAL journaling. Two tables:

**`gpu_samples`** — one row per (GPU, sample tick):

```
id, gpu_index, gpu_uuid, gpu_name, timestamp,
temperature_c, memory_used_mib, memory_total_mib, power_draw_w,
hotspot_temp_c, memory_junction_temp_c
```

Indexed on `(gpu_index, timestamp)` for fast windowed queries.

**`ollama_samples`** — one row per Ollama poll when a model is loaded:

```
id, timestamp, running, model_name,
size_bytes, size_vram_bytes, gpu_pct, cpu_pct
```

Indexed on `timestamp`.

On startup the schema is created if absent. Legacy databases (where
hotspot temp was mistakenly stored in the `memory_junction_temp_c`
column) are migrated in place — the misnamed column is renamed and a
fresh `memory_junction_temp_c` is added for the real sensor.

vLLM samples are deliberately not persisted; there is nothing
time-varying to chart for a pinned-in-VRAM single model.

---

## Architecture

```
+--------------------+        +-----------------------+
|   GPUSource        |        |   OllamaClient        |
|   - NvmlSource     |        |   VLLMClient          |
|   - SmiSource      |        |   (stdlib urllib)     |
+----------+---------+        +-----------+-----------+
           |                              |
           |  sample_all()                |  get_running()
           v                              v
        +--+------------------------------+--+
        |             Collector              |
        |  - daemon thread, loop()           |
        |  - holds latest sample under lock  |
        +--+------------------------------+--+
           |                              |
   insert  |                              |  read latest
           v                              v
        +--+---------+                 +--+--------+
        |  Storage   |                 |  NmonApp  |
        |  (SQLite)  | <-- queries --- |   (TUI)   |
        +------------+                 +-----------+
                                          ^
                                          |
                                          +-- msvcrt key thread
```

- `Collector` runs on a background daemon thread, never on the TUI
  thread. The TUI reads the latest sample under a lock without
  blocking on the network.
- `Storage` uses `check_same_thread=False`; concurrent writes from the
  collector and reads from the TUI are serialised by SQLite WAL.
- `NmonApp` drives its own refresh loop with `rich.live.Live(auto_refresh=False)`
  so any render exception surfaces in the main thread (and is logged
  to `nmon_debug.log` with a fallback error panel) instead of dying
  silently.

---

## Project layout

```
nmon/
├── pyproject.toml             package + entry point (nmon = nmon.__main__:main)
├── config.toml                example config (read from CWD by default)
├── src/nmon/
│   ├── __main__.py            CLI, source probe, server probes, app wiring
│   ├── collector.py           background sampling thread
│   ├── config.py              TOML loader with defaults + validation
│   ├── models.py              dataclasses: GPUSample, OllamaSample, VLLMSample, AppConfig
│   ├── storage.py             SQLite schema, inserts, history queries, migration
│   ├── state.py               runtime-state JSON (threshold value etc.)
│   ├── ollama.py              GET /api/ps client
│   ├── vllm.py                GET /v1/models client
│   ├── gpu/
│   │   ├── base.py            GPUSource abstract base
│   │   ├── nvml_source.py     pynvml-backed sampler
│   │   ├── smi_source.py      nvidia-smi XML fallback
│   │   └── nvapi.py           NVAPI hotspot + memory junction (Windows)
│   └── tui/
│       ├── app.py             event loop, layout, key handler
│       ├── dashboard.py       GPU/Ollama/vLLM tables for the Dashboard tab
│       ├── history.py         metric history tabs (Temp/Power/Memory)
│       ├── llm.py             LLM server history tab
│       └── widgets.py         MemoryBar, BrailleChart, MultiSeriesChart, StatusBar
└── tests/                     pytest suite
```

---

## Troubleshooting

**`No Nvidia GPU source available.`** Neither `pynvml` could initialise
nor was `nvidia-smi` found on `PATH`. Confirm the NVIDIA driver is
installed and either `pip install pynvml` succeeds or `nvidia-smi -L`
prints a GPU list.

**Hotspot or memory junction columns are missing.** They only appear
when NVAPI reports a non-zero raw value on the configured channel.
Run `python -m nmon.gpu.nvapi` to dump every populated channel; if a
channel hotter than the GPU core appears at an index other than 1 or
9, update `_SENSOR_INDEX_HOTSPOT` / `_SENSOR_INDEX_MEMORY` in
`src/nmon/gpu/nvapi.py`.

**`No Ollama server at …` / `No vLLM server at …`.** The startup probe
timed out (0.5 s). Confirm the server URL is correct, the server is
running, and nothing is firewalling the port. The dashboard section
stays hidden while the server is unreachable; the collector re-probes
roughly once a minute (`REDETECT_INTERVAL_SECONDS`), so it will appear
on its own once the server is up — no restart needed.

**Threshold line does not move with arrow keys.** Arrow keys only
move the threshold while the Temp tab is the active tab. The same
arrow keys cycle the time window on the other tabs.

**Render exceptions.** A traceback is appended to `nmon_debug.log`
in the working directory and the TUI continues to refresh with an
error panel instead of crashing. Inspect that file when the screen
shows `Render error:`.
