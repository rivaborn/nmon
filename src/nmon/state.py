"""Runtime state persistence for values the user adjusts at runtime.

Unlike config.toml (which holds user-edited defaults), the state file
is written by nmon itself whenever the user changes a tunable value
from the TUI. It overrides the config defaults on the next startup,
so the threshold line position, toggle state, and similar settings
persist across restarts without clobbering the user's config.toml.

The file is a small JSON document alongside the SQLite database:

    <db_dir>/.nmon_state.json

Failures to read or write are swallowed silently — persistence is
best-effort and never blocks the TUI from running.
"""

import json
import os


def state_path_for_db(db_path: str) -> str:
    db_dir = os.path.dirname(os.path.abspath(db_path)) or "."
    return os.path.join(db_dir, ".nmon_state.json")


def load_state(path: str, defaults: dict) -> dict:
    """Read the state file and merge it over defaults. Returns a dict
    containing every key from defaults plus any extra keys from disk."""
    merged = dict(defaults)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return merged
    if isinstance(data, dict):
        merged.update(data)
    return merged


def save_state(path: str, data: dict) -> None:
    """Atomically write the state dict to disk. Best effort — exceptions
    are swallowed so the TUI never dies because of a failed save."""
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
