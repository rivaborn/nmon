import pytest
import tempfile
import os
from nmon.config import load_config, ConfigError
from nmon.models import AppConfig

def test_load_defaults(tmp_path):
    # Ensure no config file exists
    with tempfile.TemporaryDirectory() as tmpdir:
        original_dir = os.getcwd()
        os.chdir(tmpdir)
        try:
            cfg = load_config(None)
            assert cfg.interval_seconds == 2
            assert cfg.db_path == "nmon.db"
            assert cfg.retention_hours == 24
            assert cfg.default_tab == "dashboard"
            assert cfg.default_time_window_hours == 1
        finally:
            os.chdir(original_dir)

def test_load_valid_file(tmp_path):
    toml_content = """
[sampling]
interval_seconds = 5
min_interval = 1
max_interval = 60

[storage]
db_path = "test.db"
retention_hours = 48

[display]
default_tab = "temp"
default_time_window_hours = 4
"""
    config_file = tmp_path / "config.toml"
    config_file.write_text(toml_content)

    cfg = load_config(str(config_file))
    assert cfg.interval_seconds == 5
    assert cfg.db_path == "test.db"
    assert cfg.retention_hours == 48
    assert cfg.default_tab == "temp"
    assert cfg.default_time_window_hours == 4

def test_partial_file_merges_defaults(tmp_path):
    toml_content = """
[sampling]
interval_seconds = 5
"""
    config_file = tmp_path / "config.toml"
    config_file.write_text(toml_content)

    cfg = load_config(str(config_file))
    assert cfg.interval_seconds == 5
    assert cfg.db_path == "nmon.db"
    assert cfg.retention_hours == 24
    assert cfg.default_tab == "dashboard"
    assert cfg.default_time_window_hours == 1

def test_invalid_interval_raises(tmp_path):
    toml_content = """
[sampling]
interval_seconds = 0
"""
    config_file = tmp_path / "config.toml"
    config_file.write_text(toml_content)

    with pytest.raises(ConfigError):
        load_config(str(config_file))

def test_invalid_tab_raises(tmp_path):
    toml_content = """
[display]
default_tab = "foo"
"""
    config_file = tmp_path / "config.toml"
    config_file.write_text(toml_content)

    with pytest.raises(ConfigError):
        load_config(str(config_file))

def test_cli_override_wins():
    cfg = load_config(None)
    original_interval = cfg.interval_seconds
    cfg.interval_seconds = 10
    assert cfg.interval_seconds == 10
