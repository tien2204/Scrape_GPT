import sys
import os
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

from billing_parser import extract_balance, normalize_invoice_row, is_login_page
from csv_writer import append_balance_row, merge_invoice_rows
from browser_scraper import fetch_balance_text, fetch_invoice_rows

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(BASE_DIR, "chrome_profile")
BALANCE_CSV = os.path.join(BASE_DIR, "credit_balance_log.csv")
HISTORY_CSV = os.path.join(BASE_DIR, "billing_history.csv")
LOG_PATH = os.path.join(BASE_DIR, "bot.log")


def log_run(log_path: str, success: bool, message: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    status = "SUCCESS" if success else "FAILURE"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"{timestamp} [{status}] {message}\n")


def run() -> int:
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(PROFILE_DIR, headless=True)
        page = context.pages[0] if context.pages else context.new_page()

        balance_ok = False
        history_ok = False
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
            messages.append(f"balance fetch failed: {exc}")

        try:
            raw_rows = fetch_invoice_rows(page)
            if is_login_page(page.url):
                raise RuntimeError("Session expired, run login_setup.py again")
            normalized = [normalize_invoice_row(row) for row in raw_rows]
            added = merge_invoice_rows(HISTORY_CSV, normalized)
            history_ok = True
            messages.append(f"history: {added} new invoice(s)")
        except Exception as exc:
            messages.append(f"history fetch failed: {exc}")

        context.close()

        success = balance_ok and history_ok
        log_run(LOG_PATH, success, "; ".join(messages))
        return 0 if success else 1


if __name__ == "__main__":
    sys.exit(run())
