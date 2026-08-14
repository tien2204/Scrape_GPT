import sys
import os
from datetime import datetime, timedelta, timezone
import requests
from playwright.sync_api import sync_playwright

from billing_parser import extract_balance, normalize_invoice_row, is_login_page
from csv_writer import (
    append_balance_row,
    merge_invoice_rows,
    get_new_invoice_rows,
    merge_fal_event_rows,
    get_new_fal_event_rows,
)
from browser_scraper import fetch_balance_text, fetch_invoice_rows
from state import read_state, write_state
from slack_notifier import (
    post_balance_update,
    post_error_alert,
    post_recovery,
    post_status,
    post_fal_balance_update,
    post_fal_error_alert,
    post_fal_recovery,
    post_fal_status,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(BASE_DIR, "chrome_profile")
BALANCE_CSV = os.path.join(BASE_DIR, "credit_balance_log.csv")
HISTORY_CSV = os.path.join(BASE_DIR, "billing_history.csv")
LOG_PATH = os.path.join(BASE_DIR, "bot.log")
STATE_PATH = os.path.join(BASE_DIR, "state.json")

FAL_API_BASE = "https://api.fal.ai/v1"
FAL_BALANCE_CSV = os.path.join(BASE_DIR, "fal_credit_balance_log.csv")
FAL_EVENTS_CSV = os.path.join(BASE_DIR, "fal_billing_events.csv")
FAL_STATE_PATH = os.path.join(BASE_DIR, "state_fal.json")


def log_run(log_path: str, success: bool, message: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    status = "SUCCESS" if success else "FAILURE"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"{timestamp} [{status}] {message}\n")


def decide_action(overall_success: bool, state: dict, balance: str | None, new_invoice_rows: list[dict]) -> str:
    if overall_success and state["last_status"] == "failure":
        return "recovery"
    if not overall_success and state["last_status"] == "success":
        return "error"
    if overall_success and state["last_status"] == "success":
        if state["last_balance"] is not None and (balance != state["last_balance"] or new_invoice_rows):
            return "balance_update"
    return "none"


def format_fal_timestamp(dt: datetime) -> str:
    # The fal.ai billing-events endpoint rejects ISO offsets like "+00:00" —
    # it requires the literal "Z" suffix.
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_fal_event(raw: dict) -> dict:
    return {
        "request_id": raw["request_id"],
        "endpoint_id": raw["endpoint_id"],
        "cost_total": f"{raw['cost_total']:.4f}",
        "timestamp": raw["timestamp"],
    }


def fetch_fal_balance(api_key: str) -> float:
    response = requests.get(
        f"{FAL_API_BASE}/account/billing",
        headers={"Authorization": f"Key {api_key}"},
        params={"expand": "credits"},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()["credits"]["current_balance"]


def fetch_fal_billing_events(api_key: str, start: str) -> list[dict]:
    events = []
    cursor = None
    while True:
        params = {"start": start, "limit": 100}
        if cursor:
            params["cursor"] = cursor
        response = requests.get(
            f"{FAL_API_BASE}/models/billing-events",
            headers={"Authorization": f"Key {api_key}"},
            params=params,
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        events.extend(data["billing_events"])
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return events


def check_fal_billing(webhook_url: str | None) -> bool:
    api_key = os.environ.get("FAL_ADMIN_KEY")
    if not api_key:
        return True
    api_key = api_key.strip()

    try:
        balance = f"{fetch_fal_balance(api_key):.2f}"
        append_balance_row(FAL_BALANCE_CSV, datetime.now(timezone.utc).isoformat(), balance)

        start = format_fal_timestamp(datetime.now(timezone.utc) - timedelta(hours=24))
        raw_events = fetch_fal_billing_events(api_key, start)
        normalized = [normalize_fal_event(row) for row in raw_events]
        new_event_rows = get_new_fal_event_rows(FAL_EVENTS_CSV, normalized)
        merge_fal_event_rows(FAL_EVENTS_CSV, normalized)

        success = True
        message = f"balance=${balance}; {len(new_event_rows)} new event(s)"
    except Exception as exc:
        success = False
        balance = None
        new_event_rows = []
        message = f"fal.ai check failed: {exc}"

    state = read_state(FAL_STATE_PATH)

    if webhook_url:
        action = decide_action(success, state, balance, new_event_rows)
        if action == "recovery":
            post_fal_recovery(webhook_url, balance)
        elif action == "error":
            post_fal_error_alert(webhook_url, message)
        elif action == "balance_update":
            post_fal_balance_update(webhook_url, balance, state["last_balance"], new_event_rows)
        elif action == "none" and success:
            post_fal_status(webhook_url, balance)

    next_balance = balance if success else state["last_balance"]
    write_state(FAL_STATE_PATH, next_balance, "success" if success else "failure")

    log_run(LOG_PATH, success, f"[fal.ai] {message}")
    return success


def run() -> int:
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            PROFILE_DIR,
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else context.new_page()

        balance_ok = False
        history_ok = False
        balance = None
        new_invoice_rows = []
        messages = []

        try:
            raw_balance_text = fetch_balance_text(page)
            if is_login_page(page.url):
                raise RuntimeError("Session expired, run login_setup.py again")
            balance = extract_balance(raw_balance_text)
            append_balance_row(BALANCE_CSV, datetime.now(timezone.utc).isoformat(), balance)
            balance_ok = True
            messages.append(f"balance=${balance}")
        except Exception as exc:
            if is_login_page(page.url):
                messages.append("balance fetch failed: Session expired, run login_setup.py again")
            else:
                messages.append(f"balance fetch failed: {exc}")

        try:
            raw_rows = fetch_invoice_rows(page)
            if is_login_page(page.url):
                raise RuntimeError("Session expired, run login_setup.py again")
            normalized = [normalize_invoice_row(row) for row in raw_rows]
            new_invoice_rows = get_new_invoice_rows(HISTORY_CSV, normalized)
            added = merge_invoice_rows(HISTORY_CSV, normalized)
            history_ok = True
            messages.append(f"history: {added} new invoice(s)")
        except Exception as exc:
            if is_login_page(page.url):
                messages.append("history fetch failed: Session expired, run login_setup.py again")
            else:
                messages.append(f"history fetch failed: {exc}")

        context.close()

    overall_success = balance_ok and history_ok
    state = read_state(STATE_PATH)

    if webhook_url:
        action = decide_action(overall_success, state, balance, new_invoice_rows)
        if action == "recovery":
            post_recovery(webhook_url, balance)
        elif action == "error":
            post_error_alert(webhook_url, "; ".join(messages))
        elif action == "balance_update":
            post_balance_update(webhook_url, balance, state["last_balance"], new_invoice_rows)
        elif action == "none" and overall_success:
            post_status(webhook_url, balance)

    next_balance = balance if overall_success else state["last_balance"]
    write_state(STATE_PATH, next_balance, "success" if overall_success else "failure")

    log_run(LOG_PATH, overall_success, "; ".join(messages))

    fal_success = check_fal_billing(webhook_url)

    return 0 if (overall_success and fal_success) else 1


if __name__ == "__main__":
    sys.exit(run())
