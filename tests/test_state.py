import os
import pytest
from nmon.state import state_path_for_db, load_state, save_state


def test_state_path_is_beside_db(tmp_path):
    db = str(tmp_path / "nmon.db")
    assert state_path_for_db(db) == str(tmp_path / ".nmon_state.json")


def test_load_missing_returns_defaults(tmp_path):
    out = load_state(str(tmp_path / "nope.json"), {"a": 1, "b": 2})
    assert out == {"a": 1, "b": 2}


def test_save_and_load_roundtrip(tmp_path):
    p = str(tmp_path / ".nmon_state.json")
    save_state(p, {"temp_threshold_c": 88.5, "show_temp_threshold": False})
    out = load_state(p, {"temp_threshold_c": 95.0, "show_temp_threshold": True})
    assert out["temp_threshold_c"] == 88.5
    assert out["show_temp_threshold"] is False


def test_load_merges_disk_over_defaults(tmp_path):
    p = str(tmp_path / "s.json")
    save_state(p, {"a": 10})
    out = load_state(p, {"a": 1, "b": 2})
    assert out == {"a": 10, "b": 2}  # disk wins; missing keys come from defaults


def test_load_corrupt_json_returns_defaults(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{not valid json", encoding="utf-8")
    assert load_state(str(p), {"a": 1}) == {"a": 1}


def test_load_non_dict_returns_defaults(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    assert load_state(str(p), {"a": 1}) == {"a": 1}


def test_save_is_atomic_and_leaves_no_tmp(tmp_path):
    p = str(tmp_path / "s.json")
    save_state(p, {"a": 1})
    assert os.path.exists(p)
    assert not os.path.exists(p + ".tmp")
