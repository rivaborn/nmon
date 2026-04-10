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

The Dashboard tab shows two sections:

1. **GPU Status** — current temperature, Max 24h, Avg 1h, memory usage, and
   power draw for every detected GPU.
2. **GPU Memory Junction Temperature** — a second table that appears below
   whenever at least one GPU reports a memory junction (VRAM) temperature,
   showing current, Max 24h, and Avg 1h for each supported GPU. Hidden when
   no GPU supports it, or when the junction display is toggled off.

### Temperature Tab Overlay

On the Temp tab, for any GPU that supports it, the memory junction temperature
is drawn on top of the core temperature line in a different color (bright red)
so the two series can be compared at a glance. The panel footer notes
`(junction in red)` when the overlay is active.

### Chart Time Span

History chart panels show the actual time span of collected data currently
displayed, formatted as `Hh Mm Ss` (e.g. `collected: 0h 29m 0s`) alongside
the time-window selector.

### Controls

| Key | Action |
|-----|--------|
| 1-4 | Switch tabs |
| + | Increase sampling interval |
| - | Decrease sampling interval |
| [ or ← | Decrease time window (history tabs) |
| ] or → | Increase time window (history tabs) |
| j | Toggle GPU Memory Junction Temperature on/off |
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

### Memory Junction Temperature Not Showing

- The field-value API returns `NVML_ERROR_NOT_SUPPORTED` on GPUs whose driver
  or firmware doesn't expose memory junction temperature. This is normal.
- Press `j` to confirm the toggle is on — check the status bar for
  `j: Junction (on)`.
- nmon caches unsupported GPUs per run; restart nmon after a driver update
  if you expect support to have been added.

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
