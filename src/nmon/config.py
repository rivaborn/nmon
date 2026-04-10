try:
    import tomllib
except ImportError:
    import tomli as tomllib

from nmon.models import AppConfig
import pathlib

DEFAULTS = {
    "sampling": {"interval_seconds": 2, "min_interval": 1, "max_interval": 60},
    "storage": {"db_path": "nmon.db", "retention_hours": 24},
    "display": {
        "default_tab": "dashboard",
        "default_time_window_hours": 1,
        "temp_threshold_c": 95.0,
        "show_temp_threshold": True,
    },
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
    d = cfg["display"]
    if d["default_tab"] not in {"dashboard", "temp", "power", "memory"}:
        raise ConfigError(f"invalid default_tab: {d['default_tab']}")
    if d["default_time_window_hours"] not in {1, 4, 12, 24}:
        raise ConfigError("default_time_window_hours must be 1, 4, 12, or 24")
    if not (0 <= float(d["temp_threshold_c"]) <= 150):
        raise ConfigError("temp_threshold_c must be between 0 and 150")

def load_config(path: str | None = None) -> AppConfig:
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
        default_temp_threshold_c=float(d["temp_threshold_c"]),
        default_show_temp_threshold=bool(d["show_temp_threshold"]),
    )
