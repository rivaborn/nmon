# nmon — Nvidia GPU Monitor: User Guide

## Quick Start

1. Install the package:
   ```bash
   pip install -e .
   ```

2. Run the app:
   ```bash
   nmon
   ```

3. Press `q` to quit.

---

## Installation

### Prerequisites

- Python 3.10 or later
- Nvidia GPU with drivers installed
- Either:
  - `nvidia-ml-py` Python package (recommended), **or**
  - `nvidia-smi` executable on your PATH

GPU Memory Junction Temperature is read through NVML's field-value API and is
only available on GPUs whose driver/firmware exposes it (typically data-center
and higher-end consumer cards with HBM or GDDR6X). On unsupported cards the
feature is silently skipped — the core temperature still works.

### Installing nmon

```bash
# Clone or download the project
git clone https://github.com/your/repo.git
cd nmon

# Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS/Linux

# Install the package and its dependencies
pip install -e .
```

For development/testing:
```bash
pip install -e ".[dev]"
```

---

## Running the App

### Basic Usage

```bash
nmon
```

This will:
- Look for `config.toml` in the current directory
- Use default values for any missing configuration
- Start the TUI interface

### Command-Line Options

| Option | Description |
|--------|-------------|
| `--config PATH` | Path to a custom TOML configuration file |
| `--interval N` | Override the sampling interval (seconds) |
| `--db PATH` | Override the SQLite database path |

Examples:
```bash
# Use a custom config file
nmon --config /etc/nmon/config.toml

# Override interval and DB path
nmon --interval 5 --db /tmp/nmon.db
```

---

## Configuration

### Configuration File

Copy `config.toml` from the project root to your desired location and edit it.

Example `config.toml`:
```toml
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
temp_threshold_c = 95.0
show_temp_threshold = true
```

### Configuration Options

| Section | Key | Description | Default |
|---------|-----|-------------|---------|
| sampling | interval_seconds | Sampling interval (seconds) | 2 |
| sampling | min_interval | Minimum allowed interval | 1 |
| sampling | max_interval | Maximum allowed interval | 60 |
| storage | db_path | SQLite database path | "nmon.db" |
| storage | retention_hours | Data retention period (hours) | 24 |
| display | default_tab | Starting tab ("dashboard", "temp", "power", "memory") | "dashboard" |
| display | default_time_window_hours | Starting time window (1, 4, 12, or 24) | 1 |
| display | temp_threshold_c | First-run position of the Temp tab threshold line (°C) | 95.0 |
| display | show_temp_threshold | Whether the threshold line is enabled on first run | true |

`temp_threshold_c` and `show_temp_threshold` are **first-run defaults
only** — after the first run the live values are persisted in
`.nmon_state.json` next to the database, and that file overrides
config.toml on the next startup.

---

## TUI Interface

### Tabs

| Key | Tab | Description |
|-----|-----|-------------|
| 1 | Dashboard | Live metrics for all GPUs |
| 2 | Temp | Temperature history chart |
| 3 | Power | Power draw history chart |
| 4 | Memory | Memory usage history chart |

### Dashboard Layout

The Dashboard tab shows up to three stacked sections:

1. **GPU Status** — current core temperature, Max 24h, Avg 1h, memory
   usage, and power draw for every detected GPU.
2. **GPU Hotspot Temperature** — the hottest point on the GPU die.
   Appears whenever at least one GPU exposes a hotspot sensor (all
   modern NVIDIA consumer cards, read through NVAPI on Windows).
   Shows current, Max 24h, and Avg 1h. Hidden when no GPU exposes it
   or when hotspot display is toggled off with `h`.
3. **GPU Memory Junction Temperature** — the GDDR6X memory junction
   sensor. Appears on cards that expose it (RTX 3080 / 3090 / 4080 /
   4090 and newer GDDR6X-equipped cards). Hidden when no GPU exposes
   it or when junction display is toggled off with `j`.

### Temperature Tab Overlay

On the Temp tab, every available temperature series is overlaid per
GPU on the same chart:

- **Core temperature** — in the GPU's base color (cyan, magenta, ...).
- **Hotspot temperature** — in bright red when available.
- **Memory junction temperature** — in bright magenta when available.

The panel footer shows a compact legend (e.g. `hot=red jct=magenta`)
whenever any overlay is active. Each overlay can be independently
toggled with `h` (hotspot) and `j` (junction).

### Temperature Threshold Line

The Temp tab also draws a horizontal reference line at a configurable
temperature — useful for marking a throttling ceiling or a personal
"too hot" limit. Default position is **95°C**.

- Press **`t`** to toggle the line on and off.
- When the Temp tab is active, **Up / Down arrows** raise or lower the
  line by **0.5°C** per press, clamped to `[0, 150]`.
- The chart's Y range automatically expands to include the threshold,
  so the line is always visible regardless of current GPU temperature.
- The threshold line is drawn in bright white; data dots win where
  they overlap with the line.
- The footer legend includes `thr=NN.NC` when the line is active.

Position and on/off state are persisted in `.nmon_state.json` next to
the database, so they survive restarts. The `config.toml` values
under `[display]` (`temp_threshold_c`, `show_temp_threshold`) set the
**first-run** defaults; the state file overrides them on every
subsequent startup.

### Chart Time Span

History chart panels show the actual time span of collected data
currently displayed, formatted as `Hh Mm Ss` (e.g. `collected: 0h 29m
0s`) alongside the time-window selector.

### Controls

| Key | Action |
|-----|--------|
| 1-4 | Switch tabs |
| + | Increase sampling interval |
| - | Decrease sampling interval |
| [ or ← | Decrease time window (history tabs) |
| ] or → | Increase time window (history tabs) |
| h | Toggle GPU Hotspot Temperature on/off |
| j | Toggle GPU Memory Junction Temperature on/off |
| t | Toggle temperature threshold line on/off (Temp tab) |
| ↑ | Raise threshold line by 0.5°C (Temp tab only) |
| ↓ | Lower threshold line by 0.5°C (Temp tab only) |
| q | Quit the app |

---

## Database Management

The SQLite database (`nmon.db` by default) is created automatically on first run.

### Resetting the Database

To reset the database (delete all historical data):
```bash
del nmon.db
```

The database will be recreated on the next run.

---

## Troubleshooting

### No GPU Detected

- Ensure Nvidia drivers are installed
- Verify `nvidia-smi` is on your PATH or `nvidia-ml-py` is installed
- Check that the Nvidia driver service is running

### Hotspot or Memory Junction Temperature Not Showing

nmon reads two extra temperatures beyond the core GPU temp: GPU
Hotspot (the hottest point on the GPU die) and GPU Memory Junction
(the GDDR6X VRAM sensor).

**Source paths:**

- **GPU Hotspot** — NVAPI only. Read from the undocumented
  `NvAPI_GPU_ThermChannelGetStatus` function at channel index `1`.
  Works on virtually all modern NVIDIA consumer cards on Windows.
- **GPU Memory Junction** — NVML's `NVML_FI_DEV_MEMORY_TEMP` field
  first (works on data-center GPUs like A100 / H100). On consumer
  GeForce cards NVML returns `NVML_ERROR_NOT_SUPPORTED`, so nmon
  falls back to NVAPI channel index `9`. GDDR6X-equipped cards (RTX
  3080 / 3090 / 4080 / 4090) expose it; GDDR6 cards do not.

If a sensor isn't exposed by any path, its dashboard section and
chart overlay stay hidden.

To see exactly what NVAPI is returning, run the diagnostic:

```bash
python -m nmon.gpu.nvapi
```

Expected output on a card with hotspot and memory junction:

```
NVAPI: found 1 GPU(s).

GPU 0:
  documented sensors: count=1
    [0] target=GPU            current=65C range=[0,127]
  client thermal channels: mask=0x000003ff (Q8.8 fixed point, divide raw by 256)
    sensor[ 0] =  65.03C  (raw 16648)  <-- matches GPU core
    sensor[ 1] =  71.19C  (raw 18224)  <-- [HOTSPOT used by nmon] | core +6.2C (hotter than core)
    sensor[ 2] =  65.03C  (raw 16648)  <-- matches GPU core
    ...
    sensor[ 9] =  86.00C  (raw 22016)  <-- [MEMORY JUNCTION used by nmon] | core +21.0C (hotter than core)

  Channel roles on tested Ampere/Ada cards:
    index 0 = GPU core (same as documented path)
    index 1 = GPU hotspot (hottest point on the die)
    index 9 = GPU memory junction (GDDR6X sensor)
```

Interpretation guide:

- **documented sensors** — always works; shows at least GPU core temp.
  If this block is empty, NVAPI isn't reachable at all (check driver).
- **client thermal channels** — each populated channel is labeled by
  its difference from GPU core. Channels at the production indices
  `[HOTSPOT used by nmon]` and `[MEMORY JUNCTION used by nmon]` are
  explicitly flagged so you can verify they're reading what you
  expect.
- If only `mask=0x1ff` (9 channels, indices 0-8) is accepted, your
  card doesn't expose channel 9 — typical for GDDR6 cards without a
  dedicated junction sensor. Hotspot still works.
- If a clearly hotter channel appears at an index other than 1 or 9,
  update `_SENSOR_INDEX_HOTSPOT` or `_SENSOR_INDEX_MEMORY` in
  `src/nmon/gpu/nvapi.py`.

**Technical note:** nmon calls `NvAPI_GPU_ThermChannelGetStatus`
(id `0x65FE3AAD`) with a 168-byte v2 request (`version = 0x000200a8`),
iterating the mask from `0xFFFF` down through `0xFF / 0x1F / ...`
until one succeeds. Temperatures come back in Q8.8 fixed point —
divide raw values by 256.

Other checks:

- Press `h` / `j` to confirm the toggles are on — the status bar
  shows `h:Hotspot(on)  j:Junction(on)` when enabled.
- nmon caches unsupported GPUs per run; restart nmon after a driver
  update if you expect support to have been added.

### App Crashes on Start

- Ensure all dependencies are installed (`pip install -e .`)
- Check Python version (≥ 3.10)
- Try running with `--config` pointing to a minimal config file

### Keyboard Input Not Responding

- Ensure your terminal supports single-key input
- Try a different terminal emulator

---

## Testing

To run the test suite:
```bash
pytest tests/
```

With coverage:
```bash
coverage run -m pytest tests/
coverage report -m
```

---

## Rebuild and Redeploy

Because nmon is installed as an editable package (`pip install -e .`), you
usually don't need to rebuild anything after changing source files — just run
`nmon` again and your edits are picked up automatically.

### After editing source files

```bash
nmon
```

That's it. Schema changes to the SQLite database are applied on the next run
via `ALTER TABLE` migrations, so the existing `nmon.db` is kept intact.

### After editing `pyproject.toml` or adding/removing dependencies

Re-run the editable install so new dependencies are fetched and entry points
re-registered:

```bash
pip install -e .
```

### Resetting the database

Only needed if you want to discard all recorded history:

```bash
del nmon.db          # Windows
rm nmon.db           # macOS/Linux
```

The database is recreated automatically on the next run.

---

## Building and Packaging

To build a distribution package for installing on another machine:

```bash
pip install build
python -m build
```

This creates `dist/nmon-*.tar.gz` and `dist/nmon-*-py3-none-any.whl`. Install
the wheel on the target machine with:

```bash
pip install dist/nmon-0.1.0-py3-none-any.whl
```

---

## Support

For issues or questions, please open an issue on the project repository.
