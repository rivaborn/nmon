# nmon — Nvidia GPU Monitor

A real-time terminal dashboard for monitoring Nvidia GPU(s) on Windows.
Tracks GPU core temperature, GPU hotspot temperature, GDDR6X memory
junction temperature, memory usage, and power draw with up to 24 hours
of history stored locally in SQLite.

```
 nmon  [DASHBOARD]  Temp  Power  Memory

                       GPU Status
 ┌─────────────────────┬──────┬─────────┬────────┬─────────┬──────┐
 │ GPU                 │ Temp │ Max 24h │ Avg 1h │ Memory  │ Power│
 ├─────────────────────┼──────┼─────────┼────────┼─────────┼──────┤
 │ NVIDIA RTX 4090     │ 72°C │  85°C   │  69°C  │████░ 60%│120 W │
 └─────────────────────┴──────┴─────────┴────────┴─────────┴──────┘

                GPU Hotspot Temperature
 ┌─────────────────────┬──────┬─────────┬────────┐
 │ GPU                 │ Temp │ Max 24h │ Avg 1h │
 ├─────────────────────┼──────┼─────────┼────────┤
 │ NVIDIA RTX 4090     │ 80°C │  92°C   │  77°C  │
 └─────────────────────┴──────┴─────────┴────────┘

             GPU Memory Junction Temperature
 ┌─────────────────────┬──────┬─────────┬────────┐
 │ GPU                 │ Temp │ Max 24h │ Avg 1h │
 ├─────────────────────┼──────┼─────────┼────────┤
 │ NVIDIA RTX 4090     │ 92°C │ 100°C   │  88°C  │
 └─────────────────────┴──────┴─────────┴────────┘

  Interval: 2s │ 1:Dash 2:Temp 3:Power 4:Mem │ h:Hotspot(on) j:Junction(on) q:Quit
```

## Requirements

- Windows 10/11
- Python 3.10 or later
- One or more Nvidia GPUs with drivers installed
- `nvidia-smi` on PATH **or** `nvidia-ml-py`-compatible drivers (recommended)

**GPU Hotspot Temperature** (hottest point on the GPU die) is read
via NVAPI from the undocumented `NvAPI_GPU_ThermChannelGetStatus`
function and works on essentially every modern NVIDIA consumer card.

**GPU Memory Junction Temperature** is read via NVML's field-value
API (`NVML_FI_DEV_MEMORY_TEMP`) on data-center GPUs, or via NVAPI
channel 9 as a fallback on consumer GDDR6X cards (RTX 3080 / 3090 /
4080 / 4090). GDDR6 cards without a dedicated junction sensor simply
omit the section.

## Installation

```bash
git clone <repo>
cd nmon

python -m venv .venv
.venv\Scripts\activate

pip install -e .
```

## Running

```bash
nmon
```

On first launch nmon auto-detects whether to use `nvidia-ml-py` (preferred,
lower overhead) or fall back to `nvidia-smi`. The SQLite database `nmon.db`
is created in the current directory.

### CLI options

| Flag | Description |
|------|-------------|
| `--config PATH` | Load a custom `config.toml` instead of the default |
| `--interval N` | Override the sample interval in seconds |
| `--db PATH` | Override the database file location |

```bash
nmon --interval 5 --db C:\Users\me\nmon.db
```

## Screens

Switch between screens with the number keys.

### 1 — Dashboard (default)

The dashboard has up to three stacked tables.

**GPU Status** — live row per detected GPU:

| Column | Description |
|--------|-------------|
| GPU | Model name |
| Temp | Current core temperature. Green < 60°C, yellow 60–80°C, red > 80°C |
| Max 24h | Highest core temperature recorded in the last 24 hours |
| Avg 1h | Mean core temperature over the last hour |
| Memory | Used / total VRAM with a fill bar and percentage |
| Power | Current power draw in watts |

**GPU Hotspot Temperature** — shown below the status table whenever at
least one GPU exposes a die hotspot sensor. Columns are current Temp,
Max 24h, and Avg 1h. Press `h` to toggle on/off.

**GPU Memory Junction Temperature** — shown whenever at least one GPU
exposes a VRAM junction sensor. Same three columns. Press `j` to
toggle on/off. GDDR6X cards (RTX 3080 / 3090 / 4080 / 4090) have it;
GDDR6 cards typically do not.

All sections refresh automatically at the configured sample interval.

### 2 — Temperature History

Line chart of GPU core temperature over time. One colored series per
GPU. For cards that expose them, hotspot (bright red) and memory
junction (bright magenta) are overlaid on the same chart. Press `h`
or `j` to toggle the respective overlays. The panel footer shows a
legend when overlays are active.

### 3 — Power History

Line chart of power draw over time.

### 4 — Memory History

Line chart of VRAM usage over time.

History charts show the shape of the data across the selected time window,
with Y-axis labels showing the actual min / mid / max values. The panel
footer shows how much data has actually been collected for the current
chart, formatted as `collected: Hh Mm Ss`.

## Keyboard Controls

| Key | Action |
|-----|--------|
| `1` | Switch to Dashboard |
| `2` | Switch to Temperature History |
| `3` | Switch to Power History |
| `4` | Switch to Memory History |
| `]` or `→` | Widen history time window (1hr → 4hr → 12hr → 24hr) |
| `[` or `←` | Narrow history time window |
| `+` | Increase sample interval |
| `-` | Decrease sample interval |
| `h` | Toggle GPU Hotspot Temperature display |
| `j` | Toggle GPU Memory Junction Temperature display |
| `q` | Quit |

## Configuration

Edit `config.toml` in the project root to set defaults:

```toml
[sampling]
interval_seconds = 2   # how often to poll the GPU (seconds)
min_interval = 1       # lower bound for +/- adjustment
max_interval = 60      # upper bound for +/- adjustment

[storage]
db_path = "nmon.db"    # SQLite database path
retention_hours = 24   # how many hours of history to keep

[display]
default_tab = "dashboard"          # opening screen
default_time_window_hours = 1      # opening history window (1, 4, 12, or 24)
```

Data older than `retention_hours` is pruned automatically on every write cycle.

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -v
```
