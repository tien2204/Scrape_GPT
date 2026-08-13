# Linux 24/7 Billing Bot with Slack Alerts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Slack-notifying, state-tracking layer on top of the existing OpenAI billing scraper so it can run unattended every 15 minutes on a 24/7 Linux GPU server via `cron` + `Xvfb`, instead of Windows Task Scheduler.

**Architecture:** Two small new pure-function modules (`state.py` for persisted last-run state, `slack_notifier.py` for webhook posts) plus one new pure decision function in `check_billing.py` (`decide_action`) that maps `(overall_success, state, balance, new_invoice_rows)` to one of `"recovery" | "error" | "balance_update" | "none"`. `run()` calls `decide_action` and dispatches to the matching `slack_notifier` function, keeping all the edge-triggered alerting logic unit-testable without a browser. Deployment docs (`deploy/crontab.txt`, `deploy/SETUP_LINUX.md`) describe running each 15-minute check inside a fresh `Xvfb` virtual display via `xvfb-run`, reusing a `chrome_profile/` copied over from the already-authenticated Windows machine.

**Tech Stack:** Python 3, Playwright (sync API, already in place), `requests` (new, for Slack webhook POSTs), pytest, `unittest.mock` for HTTP mocking, `cron` + `xvfb-run` (Linux deployment, not Python).

## Global Constraints

- Reuse `billing_parser.py`, `browser_scraper.py`, and `csv_writer.py`'s existing functions unchanged — `csv_writer.py` gets exactly one new function added (`get_new_invoice_rows`), no changes to existing ones.
- `SLACK_WEBHOOK_URL` is read from an environment variable only — never hardcoded, never committed to git.
- `state.json` schema: `{"last_balance": <str or null>, "last_status": "success" | "failure"}`. When the file doesn't exist yet, treat it as `{"last_balance": None, "last_status": "success"}`.
- CSV files (`credit_balance_log.csv`, `billing_history.csv`) remain the durable record, written on every run regardless of Slack activity or outcome.
- A failed Slack webhook POST must be caught and logged, never raised — it must never crash the run or block CSV writes.
- Message formats (exact wording, emoji, em dashes) as specified below in Task 3 — these are the spec's literal text, not placeholders to improvise.
- No custom log-rotation code for `cron.log` — that's `logrotate`, documented in `deploy/SETUP_LINUX.md` only.
- No code to solve remote re-authentication when the copied session expires — documented as a manual runbook step in `deploy/SETUP_LINUX.md` only.
- Chrome must run headed (no `--headless`) with `--disable-blink-features=AutomationControlled`, inside `Xvfb` on Linux — this repeats the Windows branch's finding that headless is reliably blocked by Cloudflare on this site.

---

## File Structure

```
d:/Download_D/Scrape_GPT/
  state.py                    # new: read_state/write_state, pure file I/O
  slack_notifier.py            # new: post_balance_update/post_error_alert/post_recovery
  csv_writer.py                 # modified: + get_new_invoice_rows
  check_billing.py               # modified: + decide_action, wired into run()
  requirements.txt                # modified: + requests
  deploy/
    crontab.txt                   # new: the cron line
    SETUP_LINUX.md                  # new: Linux deployment runbook
  tests/
    test_state.py                  # new
    test_slack_notifier.py          # new
    test_csv_writer.py               # modified: + tests for get_new_invoice_rows
    test_check_billing.py             # modified: + tests for decide_action
```

Rationale: `state.py` and `slack_notifier.py` stay pure/isolated exactly like `billing_parser.py` and `csv_writer.py` did in the original plan — `state.py` is file I/O only, `slack_notifier.py` is HTTP-call-plus-message-formatting only (tested via mocked `requests.post`, no real network). `decide_action` is extracted as a standalone pure function inside `check_billing.py` specifically so the edge-triggered alerting logic (the trickiest part of this design) is unit-testable without launching a browser — only `run()` itself, which wires everything to Playwright, remains untested by automation and is covered by the live verification task at the end.

---

### Task 1: `csv_writer.py` — add `get_new_invoice_rows`

**Files:**
- Modify: `csv_writer.py`
- Test: `tests/test_csv_writer.py`

**Interfaces:**
- Consumes: nothing new — reuses the existing private `_read_existing_invoice_numbers(csv_path)` helper already in this file.
- Produces: `get_new_invoice_rows(csv_path: str, candidate_rows: list[dict]) -> list[dict]` — returns the subset of `candidate_rows` whose `invoice_number` is not already present in the CSV at `csv_path`. Later tasks (`check_billing.py`) call this *before* calling the existing `merge_invoice_rows` on the same `candidate_rows`, so both see the same "before write" CSV state.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_csv_writer.py` (append to the existing file, don't remove anything):

```python
from csv_writer import get_new_invoice_rows


def test_get_new_invoice_rows_returns_all_rows_when_file_missing(tmp_path):
    csv_path = tmp_path / "history.csv"
    row = {"invoice_number": "INV-1", "status": "Paid", "amount": "$5.00", "created": "2026-01-01"}
    assert get_new_invoice_rows(str(csv_path), [row]) == [row]


def test_get_new_invoice_rows_excludes_existing_invoice_numbers(tmp_path):
    csv_path = tmp_path / "history.csv"
    row1 = {"invoice_number": "INV-1", "status": "Paid", "amount": "$5.00", "created": "2026-01-01"}
    row2 = {"invoice_number": "INV-2", "status": "Paid", "amount": "$6.00", "created": "2026-02-01"}
    merge_invoice_rows(str(csv_path), [row1])
    result = get_new_invoice_rows(str(csv_path), [row1, row2])
    assert result == [row2]


def test_get_new_invoice_rows_does_not_write_anything(tmp_path):
    csv_path = tmp_path / "history.csv"
    row = {"invoice_number": "INV-1", "status": "Paid", "amount": "$5.00", "created": "2026-01-01"}
    get_new_invoice_rows(str(csv_path), [row])
    assert not csv_path.exists()
```

Note: `merge_invoice_rows` is already imported at the top of `tests/test_csv_writer.py` from the existing test file — no new import needed for it, only add `from csv_writer import get_new_invoice_rows` alongside the existing `csv_writer` imports.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_csv_writer.py -v`
Expected: the three new tests FAIL with `ImportError: cannot import name 'get_new_invoice_rows'`

- [ ] **Step 3: Write the implementation**

Add to `csv_writer.py` (after `merge_invoice_rows`, at the end of the file):

```python
def get_new_invoice_rows(csv_path: str, candidate_rows: list[dict]) -> list[dict]:
    existing = _read_existing_invoice_numbers(csv_path)
    return [row for row in candidate_rows if row["invoice_number"] not in existing]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_csv_writer.py -v`
Expected: PASS (8 passed — the 5 existing plus 3 new)

- [ ] **Step 5: Commit**

```bash
git add csv_writer.py tests/test_csv_writer.py
git commit -m "feat: add get_new_invoice_rows to identify unseen invoices before writing"
```

---

### Task 2: `state.py` — persisted last-run state

**Files:**
- Create: `state.py`
- Test: `tests/test_state.py`

**Interfaces:**
- Produces:
  - `read_state(state_path: str) -> dict` — returns `{"last_balance": None, "last_status": "success"}` if `state_path` doesn't exist; otherwise the parsed JSON dict from that file.
  - `write_state(state_path: str, balance: str | None, status: str) -> None` — overwrites `state_path` with `{"last_balance": balance, "last_status": status}` as JSON.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_state.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_state.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'state'`

- [ ] **Step 3: Write the implementation**

Create `state.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_state.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add state.py tests/test_state.py
git commit -m "feat: add state.py for persisting last-run balance and status"
```

---

### Task 3: `slack_notifier.py` — webhook message posting

**Files:**
- Create: `slack_notifier.py`
- Test: `tests/test_slack_notifier.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: `dict` rows shaped like `normalize_invoice_row`'s return value (keys `invoice_number`, `status`, `amount`, `created`) for the `new_invoices` parameter of `post_balance_update`.
- Produces:
  - `post_balance_update(webhook_url: str, balance: str, previous_balance: str | None, new_invoices: list[dict]) -> None`
  - `post_error_alert(webhook_url: str, message: str) -> None`
  - `post_recovery(webhook_url: str, balance: str) -> None`

- [ ] **Step 1: Add `requests` to `requirements.txt`**

Update `requirements.txt` to:

```
playwright>=1.40
pytest>=7.4
requests>=2.31
```

- [ ] **Step 2: Install the new dependency**

Run: `pip install -r requirements.txt`
Expected: `requests` installs without errors.

- [ ] **Step 3: Write the failing tests**

Create `tests/test_slack_notifier.py`:

```python
from unittest.mock import patch, MagicMock
import requests
from slack_notifier import post_balance_update, post_error_alert, post_recovery


def _mock_response(status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.text = ""
    return response


@patch("slack_notifier.requests.post")
def test_post_balance_update_sends_balance_change_only(mock_post):
    mock_post.return_value = _mock_response()
    post_balance_update("https://hooks.example.com/x", "7.99", "8.99", [])
    text = mock_post.call_args.kwargs["json"]["text"]
    assert "API credit balance: $7.99 (was $8.99)" in text
    assert "New invoice" not in text


@patch("slack_notifier.requests.post")
def test_post_balance_update_sends_invoice_only_when_balance_unchanged(mock_post):
    mock_post.return_value = _mock_response()
    invoice = {"invoice_number": "0FCE475C-0005", "status": "Paid", "amount": "$8.80", "created": "2026-06-01"}
    post_balance_update("https://hooks.example.com/x", "7.99", "7.99", [invoice])
    text = mock_post.call_args.kwargs["json"]["text"]
    assert "API credit balance" not in text
    assert "New invoice: 0FCE475C-0005 \u2014 $8.80 \u2014 Paid" in text


@patch("slack_notifier.requests.post")
def test_post_balance_update_sends_both_lines(mock_post):
    mock_post.return_value = _mock_response()
    invoice = {"invoice_number": "0FCE475C-0005", "status": "Paid", "amount": "$8.80", "created": "2026-06-01"}
    post_balance_update("https://hooks.example.com/x", "7.99", "8.99", [invoice])
    text = mock_post.call_args.kwargs["json"]["text"]
    assert "API credit balance: $7.99 (was $8.99)" in text
    assert "New invoice: 0FCE475C-0005 \u2014 $8.80 \u2014 Paid" in text


@patch("slack_notifier.requests.post")
def test_post_balance_update_sends_nothing_when_no_changes(mock_post):
    post_balance_update("https://hooks.example.com/x", "7.99", "7.99", [])
    mock_post.assert_not_called()


@patch("slack_notifier.requests.post")
def test_post_error_alert_sends_correct_message(mock_post):
    mock_post.return_value = _mock_response()
    post_error_alert("https://hooks.example.com/x", "Session expired, run login_setup.py again")
    text = mock_post.call_args.kwargs["json"]["text"]
    assert text == "\u26A0\uFE0F Billing bot failing: Session expired, run login_setup.py again"


@patch("slack_notifier.requests.post")
def test_post_recovery_sends_correct_message(mock_post):
    mock_post.return_value = _mock_response()
    post_recovery("https://hooks.example.com/x", "7.99")
    text = mock_post.call_args.kwargs["json"]["text"]
    assert text == "\u2705 Billing bot recovered \u2014 balance: $7.99"


@patch("slack_notifier.requests.post")
def test_post_swallows_request_exception(mock_post, capsys):
    mock_post.side_effect = requests.RequestException("boom")
    post_error_alert("https://hooks.example.com/x", "some failure")
    captured = capsys.readouterr()
    assert "boom" in captured.out


@patch("slack_notifier.requests.post")
def test_post_logs_non_2xx_response(mock_post, capsys):
    mock_post.return_value = _mock_response(status_code=500)
    post_recovery("https://hooks.example.com/x", "7.99")
    captured = capsys.readouterr()
    assert "500" in captured.out
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pytest tests/test_slack_notifier.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'slack_notifier'`

- [ ] **Step 5: Write the implementation**

Create `slack_notifier.py`:

```python
import requests


def _post(webhook_url: str, text: str) -> None:
    try:
        response = requests.post(webhook_url, json={"text": text}, timeout=10)
        if response.status_code >= 300:
            print(f"Slack webhook returned {response.status_code}: {response.text}")
    except requests.RequestException as exc:
        print(f"Slack webhook POST failed: {exc}")


def post_balance_update(webhook_url: str, balance: str, previous_balance: str | None, new_invoices: list[dict]) -> None:
    lines = []
    if previous_balance is not None and balance != previous_balance:
        lines.append(f"\U0001F4B0 API credit balance: ${balance} (was ${previous_balance})")
    for invoice in new_invoices:
        lines.append(
            f"\U0001F9FE New invoice: {invoice['invoice_number']} \u2014 {invoice['amount']} \u2014 {invoice['status']}"
        )
    if not lines:
        return
    _post(webhook_url, "\n".join(lines))


def post_error_alert(webhook_url: str, message: str) -> None:
    _post(webhook_url, f"\u26A0\uFE0F Billing bot failing: {message}")


def post_recovery(webhook_url: str, balance: str) -> None:
    _post(webhook_url, f"\u2705 Billing bot recovered \u2014 balance: ${balance}")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_slack_notifier.py -v`
Expected: PASS (8 passed)

- [ ] **Step 7: Commit**

```bash
git add slack_notifier.py tests/test_slack_notifier.py requirements.txt
git commit -m "feat: add slack_notifier.py for balance, error, and recovery webhook messages"
```

---

### Task 4: `check_billing.py` — `decide_action` and wiring

**Files:**
- Modify: `check_billing.py`
- Test: `tests/test_check_billing.py`

**Interfaces:**
- Consumes:
  - `read_state(state_path)`, `write_state(state_path, balance, status)` from Task 2
  - `post_balance_update(webhook_url, balance, previous_balance, new_invoices)`, `post_error_alert(webhook_url, message)`, `post_recovery(webhook_url, balance)` from Task 3
  - `get_new_invoice_rows(csv_path, candidate_rows)` from Task 1
- Produces: `decide_action(overall_success: bool, state: dict, balance: str | None, new_invoice_rows: list[dict]) -> str` — returns one of `"recovery"`, `"error"`, `"balance_update"`, `"none"`. This is a pure function (no I/O), used by `run()` to decide which `slack_notifier` function (if any) to call.

Only `log_run` (existing) and `decide_action` (new) are unit-tested here — both are pure. `run()` itself wires Playwright, file I/O, and network calls together and is covered by the live verification in Task 6, matching how `run()` was already handled on the Windows branch.

- [ ] **Step 1: Write the failing tests for `decide_action`**

Add to `tests/test_check_billing.py` (append to the existing file — keep the existing `log_run` tests and their `from check_billing import log_run` import; add a second import line):

```python
from check_billing import decide_action


def test_decide_action_returns_recovery_when_transitioning_from_failure_to_success():
    state = {"last_balance": "7.99", "last_status": "failure"}
    assert decide_action(True, state, "7.99", []) == "recovery"


def test_decide_action_returns_error_when_transitioning_from_success_to_failure():
    state = {"last_balance": "7.99", "last_status": "success"}
    assert decide_action(False, state, None, []) == "error"


def test_decide_action_returns_none_when_still_failing():
    state = {"last_balance": "7.99", "last_status": "failure"}
    assert decide_action(False, state, None, []) == "none"


def test_decide_action_returns_none_on_first_run_with_no_prior_balance():
    state = {"last_balance": None, "last_status": "success"}
    assert decide_action(True, state, "7.99", []) == "none"


def test_decide_action_returns_balance_update_when_balance_changed():
    state = {"last_balance": "8.99", "last_status": "success"}
    assert decide_action(True, state, "7.99", []) == "balance_update"


def test_decide_action_returns_balance_update_when_new_invoices_present():
    state = {"last_balance": "7.99", "last_status": "success"}
    invoice = {"invoice_number": "INV-1", "status": "Paid", "amount": "$5.00", "created": "2026-01-01"}
    assert decide_action(True, state, "7.99", [invoice]) == "balance_update"


def test_decide_action_returns_none_when_nothing_changed():
    state = {"last_balance": "7.99", "last_status": "success"}
    assert decide_action(True, state, "7.99", []) == "none"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_check_billing.py -v`
Expected: the 7 new tests FAIL with `ImportError: cannot import name 'decide_action'` (the existing `log_run` tests still pass)

- [ ] **Step 3: Write the implementation**

Replace the full contents of `check_billing.py` with:

```python
import sys
import os
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

from billing_parser import extract_balance, normalize_invoice_row, is_login_page
from csv_writer import append_balance_row, merge_invoice_rows, get_new_invoice_rows
from browser_scraper import fetch_balance_text, fetch_invoice_rows
from state import read_state, write_state
from slack_notifier import post_balance_update, post_error_alert, post_recovery

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(BASE_DIR, "chrome_profile")
BALANCE_CSV = os.path.join(BASE_DIR, "credit_balance_log.csv")
HISTORY_CSV = os.path.join(BASE_DIR, "billing_history.csv")
LOG_PATH = os.path.join(BASE_DIR, "bot.log")
STATE_PATH = os.path.join(BASE_DIR, "state.json")


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


def run() -> int:
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            PROFILE_DIR,
            headless=True,
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

    next_balance = balance if overall_success else state["last_balance"]
    write_state(STATE_PATH, next_balance, "success" if overall_success else "failure")

    log_run(LOG_PATH, overall_success, "; ".join(messages))
    return 0 if overall_success else 1


if __name__ == "__main__":
    sys.exit(run())
```

Note on `next_balance`: a failed run keeps the previously-known-good balance in `state.json` rather than overwriting it with `None` — this preserves the last real balance for the eventual recovery/comparison logic instead of losing it during an outage.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_check_billing.py -v`
Expected: PASS (9 passed — the 2 existing `log_run` tests plus 7 new `decide_action` tests)

- [ ] **Step 5: Run the full test suite**

Run: `pytest -v`
Expected: all tests across `tests/test_billing_parser.py`, `tests/test_csv_writer.py`, `tests/test_slack_notifier.py`, `tests/test_state.py`, `tests/test_check_billing.py` pass, pristine output.

- [ ] **Step 6: Commit**

```bash
git add check_billing.py tests/test_check_billing.py
git commit -m "feat: wire state tracking and Slack notifications into check_billing.py"
```

---

### Task 5: Linux deployment files

**Files:**
- Create: `deploy/crontab.txt`
- Create: `deploy/SETUP_LINUX.md`

**Interfaces:**
- Consumes: `check_billing.py` from Task 4 as the process the cron job invokes.

- [ ] **Step 1: Create `deploy/crontab.txt`**

```
*/15 * * * * cd /path/to/project && xvfb-run -a python3 check_billing.py >> cron.log 2>&1
```

- [ ] **Step 2: Create `deploy/SETUP_LINUX.md`**

```markdown
# Linux Deployment

This runs the billing bot every 15 minutes on a headless Linux server using
a virtual display (Xvfb) so Chrome renders normally (not `--headless`,
which is reliably blocked by Cloudflare on OpenAI's billing pages).

## 1. Install system dependencies

    sudo apt update
    sudo apt install -y xvfb
    playwright install-deps chromium

## 2. Copy the project and the authenticated session

From your Windows machine, where you've already run `login_setup.py` and
confirmed `check_billing.py` works:

    scp -r chrome_profile/ user@your-server:/path/to/project/

Copy the rest of the project (all the `.py` files, `requirements.txt`) the
same way, or `git clone` the `linux-billing-bot` branch directly on the
server and `scp` only `chrome_profile/` over separately (it's gitignored).

## 3. Install Python dependencies

    cd /path/to/project
    pip install -r requirements.txt
    playwright install chromium

## 4. Set the Slack webhook URL

Add to your shell profile (e.g. `~/.bashrc`) so it's available to cron too
(cron does not read your shell profile by default — export it in the
crontab line itself, or source it explicitly):

    export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."

If setting it only in `~/.bashrc`, prefix the cron command with sourcing
that file, e.g.:

    */15 * * * * cd /path/to/project && . ~/.bashrc && xvfb-run -a python3 check_billing.py >> cron.log 2>&1

## 5. Verify a manual run works

    xvfb-run python3 check_billing.py

Check `credit_balance_log.csv`, `billing_history.csv`, `state.json`, and
`bot.log` were created/updated. Since this is the first-ever run, no Slack
message should fire (nothing to compare against yet).

## 6. Install the crontab

    crontab deploy/crontab.txt

(Edit the `cd /path/to/project` portion first to match where you actually
placed the project, and add the `SLACK_WEBHOOK_URL` export as described in
step 4 if you're not sourcing it from `~/.bashrc`.)

Verify it's installed:

    crontab -l

## 7. Rotate `cron.log`

At 96 runs/day, `cron.log` grows indefinitely if left alone. Add a
`logrotate` config, e.g. `/etc/logrotate.d/billing-bot`:

    /path/to/project/cron.log {
        weekly
        rotate 4
        compress
        missingok
        notifempty
    }

## Troubleshooting

- If `bot.log` shows "Session expired, run login_setup.py again" repeatedly:
  the copied session has expired. The server has no display to log in
  again itself — go back to the Windows machine, run `login_setup.py`
  again, and `scp` the refreshed `chrome_profile/` over once more.
- If runs fail with a Cloudflare-style timeout even inside Xvfb: confirm
  Chrome is *not* being launched with `--headless` anywhere, and that
  `--disable-blink-features=AutomationControlled` is present in
  `check_billing.py`'s `launch_persistent_context` call.
```

- [ ] **Step 3: Commit**

```bash
git add deploy/crontab.txt deploy/SETUP_LINUX.md
git commit -m "docs: add Linux cron deployment files and runbook"
```

---

### Task 6: End-to-end live verification on the Linux GPU server

**Files:**
- Modify: `browser_scraper.py` (only if further selector/timing tuning is needed)

**Interfaces:**
- Consumes: the full pipeline from Tasks 1–5.

This task has no automated steps — it requires real SSH access to the user's Linux GPU server, the real Slack webhook, and the real `chrome_profile/` session, none of which any subagent has. It mirrors Task 8 from the Windows branch's plan.

- [x] **Step 1: Follow `deploy/SETUP_LINUX.md` steps 1–4**

Install `xvfb`, copy the project and `chrome_profile/` to the server, install Python dependencies, set `SLACK_WEBHOOK_URL`.

`chrome_profile/` was already present on the server (not scp'd this session). `Xvfb` is present via the `billing-bot` conda env but without the `xvfb-run` wrapper script — worked around with `deploy/run_with_xvfb.sh`. `SLACK_WEBHOOK_URL` is **not yet set** anywhere on this server — Steps 4–5 below are blocked on that.

- [x] **Step 2: Run the manual verification from `deploy/SETUP_LINUX.md` step 5**

Run: `xvfb-run python3 check_billing.py`
Expected: exits 0, `bot.log` shows `[SUCCESS]`, `state.json` is created, and — since it's the first-ever run — no Slack message appears in the channel.

First attempt failed (see Step 3). After the fix, confirmed: exit 0, `bot.log` shows `[SUCCESS] balance=$7.99; history: 3 new invoice(s)`, `state.json` and CSVs written correctly.

If it fails with a Cloudflare-style block or timeout even inside Xvfb, proceed to Step 3. Otherwise skip to Step 4.

- [x] **Step 3: Diagnose and fix if Xvfb doesn't pass Cloudflare on this server**

This is the one open risk flagged in the design: Xvfb + real GPU rendering is expected to behave like a genuinely headed browser (which passed reliably on Windows), but it must be confirmed on the actual server. If it's still blocked, capture a screenshot (`page.screenshot(path="debug.png")`) and the page title after a `page.goto` + `wait_for_timeout(20000)`, the same way the Windows blocker was diagnosed, to see whether it's the Cloudflare interstitial or something else (e.g., Xvfb not actually attached, GPU not available to the virtual display). Fix `check_billing.py`'s `launch_persistent_context` call or the `Xvfb`/GPU driver setup based on what's found, then repeat Step 2.

Found two bugs, not related to Xvfb/GPU capability itself:
1. `check_billing.py` had `headless=True` (contradicting the plan's own constraint) — this alone caused every run to hit Cloudflare's "Just a moment..." interstitial, confirmed via page title/content and a WebGL renderer check. Fixed to `headless=False`.
2. Separately, `fetch_balance_text` raced the async-rendered dollar amount (read the container right after the label appeared, before the `$X.XX` text existed). Fixed to wait for the `$X.XX` text itself.

Both fixed and verified with 3 consecutive successful runs; see commit `9c3e5f4`.

- [x] **Step 4: Verify the change-detection and Slack messages**

Manually edit `state.json`'s `last_balance` to a different value (e.g. subtract 1 from the real balance), then re-run `xvfb-run python3 check_billing.py`. Confirm a "balance changed" Slack message appears in the channel with the correct old/new values, matching the format in Task 3.

Confirmed live in `#alert-imghub-credits`: edited `last_balance` to `"6.99"` then `"5.99"` across two runs, both times the real balance ($7.99) was re-fetched and `decide_action` returned `balance_update`. Slack messages posted and verified via search: "💰 API credit balance: $7.99 (was $6.99)" and "💰 API credit balance: $7.99 (was $5.99)", exact format match.

- [x] **Step 5: Verify the failure/recovery edge behavior**

Temporarily rename `chrome_profile/` (e.g. to `chrome_profile_bak/`) to force a failure (the new empty profile will hit a login page), and run `xvfb-run python3 check_billing.py` twice in a row. Confirm the *first* run posts a Slack error alert and the *second* posts nothing (edge-triggered silence — `bot.log` still logs `[FAILURE]` both times, only Slack is silenced on the repeat). Then rename `chrome_profile_bak/` back to `chrome_profile/` and run once more — confirm it posts a recovery message to Slack.

Confirmed live: run 1 with the renamed profile took ~64s (fresh Chrome profile has more first-run overhead than the double-30s selector-timeout baseline — not an infinite hang, just needed >60s) and logged `[FAILURE] ... Session expired, run login_setup.py again`, posting exactly one "⚠️ Billing bot failing: ..." to `#alert-imghub-credits`. Run 2 (still failing) also logged `[FAILURE]` but posted nothing — edge-triggered silence confirmed via Slack search (only one failing-alert message exists in the window). After restoring `chrome_profile/`, run 3 succeeded in ~12s and posted "✅ Billing bot recovered — balance: $7.99", exact match.

- [x] **Step 6: Commit any fixes found in Step 3**

```bash
git add browser_scraper.py check_billing.py
git commit -m "fix: adjust browser launch for Linux/Xvfb Cloudflare behavior"
```

(Skip this commit if no changes were needed.)

Committed as `9c3e5f4` (also includes `deploy/run_with_xvfb.sh` and the doc/crontab updates from the `xvfb-run`-wrapper gap found in Step 1).

- [x] **Step 7: Install the crontab and observe one real cycle**

Follow `deploy/SETUP_LINUX.md` steps 6–7 (install crontab, set up `logrotate`). Watch `cron.log` through at least one real 15-minute cycle to confirm unattended operation works before considering this done.

While wiring this up, found and fixed a real (not just theoretical) blocker: cron runs jobs under `/bin/sh` (dash on this box), and dash's `.`/source only searches `$PATH` for a bare filename — unlike bash's `source`, it doesn't fall back to the current directory. `. .env` silently failed under actual cron (worked fine when the same line was pasted into interactive bash, which is why it wasn't caught by earlier manual testing) — no output at all appeared in `bot.log` or `cron.log` for ~7 minutes despite cron being confirmed running. Root-caused by running the exact crontab line manually under `/bin/sh -c`. Fixed to `. ./.env` in `deploy/crontab.txt` and `deploy/SETUP_LINUX.md`.

Per user request, verified the fix at an accelerated `* * * * *` (every-minute) schedule instead of waiting a full 15 minutes: 3 consecutive cron-triggered runs all logged `[SUCCESS]` (`05:44:11`, `05:45:11`, `05:46:31` UTC) with correct balance/history output and no manual intervention. Then switched to the real `*/15 * * * * cd /home/intern/Scrape_GPT && ...` line and confirmed `crontab -l` shows it installed.

**Not done:** `logrotate` setup (`/etc/logrotate.d/billing-bot`) requires root and this session only has the unprivileged `intern` user (`sudo` demands a password) — needs to be added by whoever has root on this server. A full real 15-minute-interval cycle hasn't been separately observed (only the every-minute accelerated version and the schedule swap) — the executed command is identical either way, only the cron cadence field differs, but flagging this in case anyone wants to watch `cron.log` once more at the real interval before fully trusting it unattended.
