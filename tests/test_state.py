import json
from state import read_state, write_state


def test_read_state_returns_default_when_file_missing(tmp_path):
    state_path = tmp_path / "state.json"
    assert read_state(str(state_path)) == {"last_balance": None, "last_status": "success"}


def test_write_state_creates_file_with_correct_content(tmp_path):
    state_path = tmp_path / "state.json"
    write_state(str(state_path), "7.99", "success")
    with open(state_path, encoding="utf-8") as f:
        content = json.load(f)
    assert content == {"last_balance": "7.99", "last_status": "success"}


def test_read_state_returns_parsed_json_when_file_exists(tmp_path):
    state_path = tmp_path / "state.json"
    write_state(str(state_path), "8.99", "failure")
    assert read_state(str(state_path)) == {"last_balance": "8.99", "last_status": "failure"}


def test_write_state_overwrites_existing_file(tmp_path):
    state_path = tmp_path / "state.json"
    write_state(str(state_path), "7.99", "success")
    write_state(str(state_path), "6.50", "success")
    assert read_state(str(state_path)) == {"last_balance": "6.50", "last_status": "success"}


def test_write_state_accepts_none_balance(tmp_path):
    state_path = tmp_path / "state.json"
    write_state(str(state_path), None, "failure")
    assert read_state(str(state_path)) == {"last_balance": None, "last_status": "failure"}
