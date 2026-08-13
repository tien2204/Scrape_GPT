import json
import os

DEFAULT_STATE = {"last_balance": None, "last_status": "success"}


def read_state(state_path: str) -> dict:
    if not os.path.exists(state_path):
        return dict(DEFAULT_STATE)
    with open(state_path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_state(state_path: str, balance: str | None, status: str) -> None:
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump({"last_balance": balance, "last_status": status}, f)
