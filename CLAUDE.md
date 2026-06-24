# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

`README.md` is the authoritative reference for features, CLI flags, config keys, keybindings, and the data-source layering. Read it for user-facing detail; this file covers what's needed to develop in the repo.

## Commands

```powershell
pip install -e ".[dev]"     # editable install + pytest/coverage/pytest-mock
nmon                        # run the TUI (entry point: nmon.__main__:main)

pytest                      # full suite
pytest tests/test_storage.py::test_name   # single test
python -m nmon.gpu.nvapi    # NVAPI channel-dump diagnostic (Windows + NVIDIA only)
```

Tests run cross-platform and need no GPU: `pynvml` is monkeypatched into `sys.modules` (`mock_pynvml` fixture) and the `nvidia-smi` path is fed XML from `tests/fixtures/`. `Storage(":memory:")` gives an isolated in-memory DB per test. See `tests/conftest.py` for the shared fixtures (`in_memory_storage`, `fake_gpu_info`, `fake_sample`).

## Architecture

Three layers run concurrently; the key invariant is that **the TUI never blocks on hardware or network I/O**.

- **`Collector`** (`collector.py`) — owns a daemon thread (`_loop`). Each tick it calls `GPUSource.sample_all()`, writes to `Storage`, prunes old rows, and polls the LLM servers. It holds the latest sample under a `threading.Lock`; the TUI reads via `get_latest()` / `get_latest_ollama()` / `get_latest_vllm()` without ever touching the source or sockets itself.
- **`GPUSource`** (`gpu/`) — abstract base with two implementations chosen at startup in `__main__.py`: `NvmlSource` (preferred, direct `pynvml`) then `SmiSource` (`nvidia-smi --xml-format` fallback). On Windows, `gpu/nvapi.py` supplements NVML with hotspot + GDDR6X memory-junction temps read from `nvapi64.dll` — NVML doesn't expose these on consumer cards. Sensor channel indices (`_SENSOR_INDEX_HOTSPOT`, `_SENSOR_INDEX_MEMORY`) are hardware-specific; the `nvapi` diagnostic exists to re-verify them.
- **`Storage`** (`storage.py`) — SQLite with WAL, `check_same_thread=False` so the collector writes and the TUI reads concurrently. Two tables: `gpu_samples`, `ollama_samples` (vLLM is intentionally not persisted). Schema is created on startup and legacy DBs are migrated in place.
- **`NmonApp`** (`tui/app.py`) — drives `rich.live.Live(auto_refresh=False)` so render exceptions surface on the main thread (logged to `nmon_debug.log` with a fallback error panel) instead of dying silently. Keyboard input runs on a separate thread using **`msvcrt`** — this is why the interactive TUI is Windows-only even though the collector/storage layers are portable.

Data shapes are dataclasses in `models.py` (`GPUSample`, `OllamaSample`, `VLLMSample`, `GPUInfo`, `AppConfig`). LLM clients (`ollama.py`, `vllm.py`) are stdlib-`urllib` only with 0.5 s timeouts that swallow all exceptions.

## Conventions worth keeping

- **Hardware and network failures must never crash the loop.** The collector catches `GPUSourceError`/`StorageError`/`Exception` per tick and pushes human-readable strings onto `self.warnings`. LLM polls swallow everything.
- **LLM server re-detection:** if a server is absent, the collector backs off `REDETECT_INTERVAL_SECONDS` (60 s) then retries — it picks up servers that come online mid-session, no restart needed.
- **Config and runtime state are separate.** `config.py` loads `config.toml` (CLI `--config` → `./config.toml` → `~/.nmon/config.toml`, partial files fall through to defaults). User-tweaked TUI state (threshold value/visibility) is written by `state.py` to `<db_dir>/.nmon_state.json` and overrides the `[display]` defaults on next launch.
- Config plumbs through `AppConfig`; add new tunables there and in `config.py`'s loader/defaults, not as ad-hoc reads.
