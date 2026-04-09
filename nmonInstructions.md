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
  - `pynvml` Python package (recommended), **or**
  - `nvidia-smi` executable on your PATH

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

### Controls

| Key | Action |
|-----|--------|
| 1-4 | Switch tabs |
| + | Increase sampling interval |
| - | Decrease sampling interval |
| [ | Decrease time window (history tabs) |
| ] | Increase time window (history tabs) |
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
- Verify `nvidia-smi` is on your PATH or `pynvml` is installed
- Check that the Nvidia driver service is running

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

## Building and Packaging

To build a distribution package:
```bash
python -m build
```

This creates `dist/nmon-*.tar.gz` and `dist/nmon-*-py3-none-any.whl`.

---

## Support

For issues or questions, please open an issue on the project repository.
