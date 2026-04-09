# nmon — Nvidia GPU Monitor: Implementation Planning Prompt

## Context

I want to create a Python terminal application called **nmon** that monitors Nvidia GPU(s) in real time. You are writing a detailed architecture and implementation plan — **no code yet**.

- **Target machine**: Windows 11, one or more Nvidia GPUs
- **Language**: Python 3.10+
- **UI framework**: Rich (terminal UI) — single-process TUI with tabbed views
- **Data layer**: SQLite for persistence (lightweight, no server dependency)
- **GPU data source**: `nvidia-smi` CLI (XML output via `--query-gpu` / `--xml`) or `pynvml` library
- **Testing**: pytest with full unit test coverage for every function
- **Output**: Write the plan to `nmonArchitecture.md`

## Monitored Metrics (per GPU)

| Metric          | Sampled | Stored |
|-----------------|---------|--------|
| Temperature (°C)| Yes     | 24 hrs rolling |
| Memory used (MiB)| Yes    | 24 hrs rolling |
| Power draw (W)  | Yes     | 24 hrs rolling |

- **Default sample interval**: 2 seconds (user-adjustable: 1s–60s)
- **Data older than 24 hours** is pruned automatically on each write cycle

## Functional Requirements

### Screen 1 — Live Dashboard (default view)
- Current temperature, memory usage, and power draw for each detected GPU
- Auto-refreshes at the configured sample interval
- Shows **max temperature** over the past 24 hours (per GPU)
- Shows **average temperature** over the past 1 hour (per GPU)
- Shows **current memory used / total memory** as both value and percentage bar
- Interval adjustment control (keyboard shortcut to cycle or type a value)

### Screen 2 — Temperature History (tab)
- Line chart: temperature over time per GPU
- Selectable time window: 1hr / 4hr / 12hr / 24hr
- Y-axis: °C, X-axis: timestamps
- One series line per GPU, color-coded

### Screen 3 — Power History (tab)
- Line chart: power draw over time per GPU
- Same time window options as Screen 2
- Y-axis: Watts, X-axis: timestamps

### Screen 4 — Memory History (tab)
- Line chart: memory usage over time per GPU
- Same time window options as Screen 2
- Y-axis: MiB, X-axis: timestamps

## Non-Functional Requirements

- **Graceful degradation**: If `nvidia-smi` or `pynvml` is unavailable, show a clear error — don't crash
- **GPU hot-plug tolerance**: If GPU count changes between samples, log a warning and adapt
- **Low overhead**: Sampling must not block the TUI render loop — use async or threaded collection
- **Portable config**: Sample interval and retention period stored in a `config.toml` (or similar), with sensible defaults baked in

## Architecture Plan Deliverable

In `nmonArchitecture.md`, include ALL of the following:

1. **Project structure** — full directory tree with every file path
2. **Data model** — SQLite schema, Python dataclasses/TypedDicts for in-memory representations
3. **Module breakdown** — one section per module/file:
   - Purpose
   - Classes and function signatures (name, parameters with types, return type)
   - Pseudocode logic for each function
   - Error handling approach for that module
4. **Sampling pipeline** — how data flows from GPU → collector → DB → UI
5. **TUI layout** — which Rich components map to which screen regions
6. **Configuration** — schema for `config.toml`, defaults, validation rules
7. **Testing strategy**:
   - For each module, list the specific test cases (not just "test this function")
   - Mocking strategy for `nvidia-smi` / `pynvml` (fixture data for 1-GPU and multi-GPU)
   - Integration test approach for the sampling → storage → query pipeline
8. **Dependency list** — exact PyPI packages with version constraints
9. **Build / run instructions** — how to install, configure, and launch nmon

Think deeply and systematically. Resolve ambiguities by choosing the simplest correct approach and documenting your rationale. Do not write any implementation code — only the plan.
