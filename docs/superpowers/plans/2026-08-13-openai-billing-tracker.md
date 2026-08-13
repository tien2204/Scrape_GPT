# OpenAI Billing Tracker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python/Playwright bot that reads OpenAI's API credit balance and invoice history from the billing web UI and logs them to CSV on a recurring Windows Task Scheduler run.

**Architecture:** A dedicated headless Chromium profile (separate from the user's daily browser) authenticates once via a manual login script, then a scheduled script reuses that saved session to scrape two billing pages, parses the results with pure functions, and appends new data to two CSV files plus a run log.

**Tech Stack:** Python 3, Playwright (sync API), pytest, Windows Task Scheduler (`schtasks`), CSV via the standard library `csv` module.

## Global Constraints

- Language/tooling: Python + Playwright (per spec decision), not Node.js.
- Browser session: dedicated persistent Chromium profile at `./chrome_profile/`, never the user's default Chrome profile.
- `credit_balance_log.csv` columns: `timestamp, balance_usd` — one row appended per successful run (time series, never deduped/overwritten).
- `billing_history.csv` columns: `invoice_number, status, amount, created` — deduplicated by `invoice_number`, only new invoices appended.
- `bot.log` — one line per run: timestamp, SUCCESS/FAILURE, and details.
- No use of OpenAI's Admin/Usage API — browser automation only.
- No low-balance alerting/notifications — out of scope.
- Scheduling target is Windows Task Scheduler only, every 6 hours, headless execution.
- On session expiry (redirected to a login page), the run must log a clear "Session expired, run login_setup.py again" message and must not write garbage data to the CSVs.

---

## File Structure

```
d:/Download_D/Scrape_GPT/
  billing_parser.py       # pure parsing/validation functions (no I/O)
  csv_writer.py            # CSV append/merge functions (file I/O, no browser)
  browser_scraper.py        # Playwright page-reading functions (no CSV/log logic)
  check_billing.py          # orchestrator: wires scraper -> parser -> csv_writer -> log
  login_setup.py            # one-time manual login script
  run_bot.bat                # Task Scheduler entry point
  requirements.txt
  pytest.ini
  .gitignore
  SETUP.md                   # setup + Task Scheduler instructions
  tests/
    test_billing_parser.py
    test_csv_writer.py
    test_check_billing.py
```

Rationale: parsing logic (`billing_parser.py`) and CSV logic (`csv_writer.py`) are pure/file-only and fully unit-testable without a browser. `browser_scraper.py` isolates all Playwright page interaction so it's the only module that can't be exercised by fast automated tests — it's covered instead by the manual end-to-end task at the end of this plan. `check_billing.py` only wires these together plus logging.

---

### Task 1: Project scaffolding

**Files:**
- Create: `requirements.txt`
- Create: `pytest.ini`
- Create: `.gitignore`

**Interfaces:**
- Produces: an installed environment with `playwright` and `pytest` available, and a Chromium browser installed for Playwright.

- [ ] **Step 1: Create `requirements.txt`**

```
playwright>=1.40
pytest>=7.4
```

- [ ] **Step 2: Create `pytest.ini`**

```ini
[pytest]
pythonpath = .
```

- [ ] **Step 3: Create `.gitignore`**

```
chrome_profile/
*.csv
bot.log
__pycache__/
*.pyc
.venv/
venv/
```

- [ ] **Step 4: Install dependencies**

Run: `pip install -r requirements.txt`
Expected: playwright and pytest install without errors.

- [ ] **Step 5: Install Playwright's Chromium browser**

Run: `playwright install chromium`
Expected: download completes without errors.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt pytest.ini .gitignore
git commit -m "chore: scaffold project dependencies and config"
```

---

### Task 2: `billing_parser.py` — pure parsing functions

**Files:**
- Create: `billing_parser.py`
- Test: `tests/test_billing_parser.py`

**Interfaces:**
- Produces:
  - `extract_balance(raw_text: str) -> str` — returns the numeric dollar amount (e.g. `"7.99"`) found in `raw_text`; raises `ValueError` if none found.
  - `normalize_invoice_row(cells: list[str]) -> dict` — returns `{"invoice_number": str, "status": str, "amount": str, "created": str}`; raises `ValueError` if fewer than 4 cells or invoice number is empty.
  - `is_login_page(url: str) -> bool` — True if `url` looks like an OpenAI auth/login page.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_billing_parser.py`:

```python
import pytest
from billing_parser import extract_balance, normalize_invoice_row, is_login_page


def test_extract_balance_simple():
    assert extract_balance("$7.99") == "7.99"


def test_extract_balance_with_label():
    assert extract_balance("API credit balance\n$7.99") == "7.99"


def test_extract_balance_with_thousands_separator():
    assert extract_balance("$1,234.56") == "1,234.56"


def test_extract_balance_raises_when_missing():
    with pytest.raises(ValueError):
        extract_balance("no dollar amount here")


def test_normalize_invoice_row_strips_whitespace():
    row = normalize_invoice_row(
        [" 0FCE475C-0004 ", " Paid ", " $8.80 ", " 6:46 27 thg 5, 2026 "]
    )
    assert row == {
        "invoice_number": "0FCE475C-0004",
        "status": "Paid",
        "amount": "$8.80",
        "created": "6:46 27 thg 5, 2026",
    }


def test_normalize_invoice_row_raises_on_missing_invoice_number():
    with pytest.raises(ValueError):
        normalize_invoice_row(["", "Paid", "$8.80", "2026-05-27"])


def test_normalize_invoice_row_raises_on_too_few_cells():
    with pytest.raises(ValueError):
        normalize_invoice_row(["0FCE475C-0004", "Paid"])


def test_is_login_page_detects_auth_domain():
    assert is_login_page("https://auth.openai.com/log-in") is True


def test_is_login_page_detects_login_path():
    assert is_login_page("https://platform.openai.com/login") is True


def test_is_login_page_false_for_billing_page():
    assert is_login_page(
        "https://platform.openai.com/settings/organization/billing/overview"
    ) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_billing_parser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'billing_parser'`

- [ ] **Step 3: Write the implementation**

Create `billing_parser.py`:

```python
import re


def extract_balance(raw_text: str) -> str:
    match = re.search(r"\$([\d,]+\.\d{2})", raw_text)
    if not match:
        raise ValueError(f"Could not find a dollar amount in: {raw_text!r}")
    return match.group(1)


def normalize_invoice_row(cells: list[str]) -> dict:
    if len(cells) < 4:
        raise ValueError(f"Expected at least 4 cells, got {cells!r}")
    invoice_number, status, amount, created = (c.strip() for c in cells[:4])
    if not invoice_number:
        raise ValueError("Invoice row missing invoice number")
    return {
        "invoice_number": invoice_number,
        "status": status,
        "amount": amount,
        "created": created,
    }


def is_login_page(url: str) -> bool:
    return "auth.openai.com" in url or "/login" in url or "/auth/" in url
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_billing_parser.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add billing_parser.py tests/test_billing_parser.py
git commit -m "feat: add billing text parsing functions"
```

---

### Task 3: `csv_writer.py` — CSV append/merge functions

**Files:**
- Create: `csv_writer.py`
- Test: `tests/test_csv_writer.py`

**Interfaces:**
- Consumes: `dict` rows shaped like `normalize_invoice_row`'s return value from Task 2 (`invoice_number`, `status`, `amount`, `created` keys).
- Produces:
  - `append_balance_row(csv_path: str, timestamp: str, balance_usd: str) -> None`
  - `merge_invoice_rows(csv_path: str, new_rows: list[dict]) -> int` — returns count of newly added rows.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_csv_writer.py`:

```python
import csv
from csv_writer import append_balance_row, merge_invoice_rows


def test_append_balance_row_creates_file_with_header(tmp_path):
    csv_path = tmp_path / "balance.csv"
    append_balance_row(str(csv_path), "2026-08-13T10:00:00", "7.99")
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows == [{"timestamp": "2026-08-13T10:00:00", "balance_usd": "7.99"}]


def test_append_balance_row_appends_without_duplicate_header(tmp_path):
    csv_path = tmp_path / "balance.csv"
    append_balance_row(str(csv_path), "2026-08-13T10:00:00", "7.99")
    append_balance_row(str(csv_path), "2026-08-13T16:00:00", "6.50")
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2
    assert rows[1]["balance_usd"] == "6.50"


def test_merge_invoice_rows_creates_file(tmp_path):
    csv_path = tmp_path / "history.csv"
    new_rows = [
        {"invoice_number": "INV-1", "status": "Paid", "amount": "$5.00", "created": "2026-01-01"}
    ]
    added = merge_invoice_rows(str(csv_path), new_rows)
    assert added == 1
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows == new_rows


def test_merge_invoice_rows_skips_duplicates(tmp_path):
    csv_path = tmp_path / "history.csv"
    row = {"invoice_number": "INV-1", "status": "Paid", "amount": "$5.00", "created": "2026-01-01"}
    merge_invoice_rows(str(csv_path), [row])
    added = merge_invoice_rows(str(csv_path), [row])
    assert added == 0
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1


def test_merge_invoice_rows_adds_only_new_rows(tmp_path):
    csv_path = tmp_path / "history.csv"
    row1 = {"invoice_number": "INV-1", "status": "Paid", "amount": "$5.00", "created": "2026-01-01"}
    row2 = {"invoice_number": "INV-2", "status": "Paid", "amount": "$6.00", "created": "2026-02-01"}
    merge_invoice_rows(str(csv_path), [row1])
    added = merge_invoice_rows(str(csv_path), [row1, row2])
    assert added == 1
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_csv_writer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'csv_writer'`

- [ ] **Step 3: Write the implementation**

Create `csv_writer.py`:

```python
import csv
import os

BALANCE_FIELDS = ["timestamp", "balance_usd"]
INVOICE_FIELDS = ["invoice_number", "status", "amount", "created"]


def append_balance_row(csv_path: str, timestamp: str, balance_usd: str) -> None:
    file_exists = os.path.exists(csv_path)
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=BALANCE_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow({"timestamp": timestamp, "balance_usd": balance_usd})


def _read_existing_invoice_numbers(csv_path: str) -> set:
    if not os.path.exists(csv_path):
        return set()
    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return {row["invoice_number"] for row in reader}


def merge_invoice_rows(csv_path: str, new_rows: list[dict]) -> int:
    existing = _read_existing_invoice_numbers(csv_path)
    to_add = [row for row in new_rows if row["invoice_number"] not in existing]
    file_exists = os.path.exists(csv_path)
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=INVOICE_FIELDS)
        if not file_exists:
            writer.writeheader()
        for row in to_add:
            writer.writerow(row)
    return len(to_add)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_csv_writer.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add csv_writer.py tests/test_csv_writer.py
git commit -m "feat: add CSV append and dedup-merge functions"
```

---

### Task 4: `browser_scraper.py` — Playwright page-reading functions

**Files:**
- Create: `browser_scraper.py`

**Interfaces:**
- Consumes: a Playwright `Page` object (from a launched persistent context, wired in Task 6).
- Produces:
  - `fetch_balance_text(page) -> str` — raw text scraped from the billing overview page, to be passed into `extract_balance` from Task 2.
  - `fetch_invoice_rows(page) -> list[list[str]]` — one list of raw cell strings per invoice row, to be passed into `normalize_invoice_row` from Task 2.

No automated test for this task: it requires a real authenticated Playwright browser session, which is exercised manually in Task 8. Selectors below are a best-effort first pass based on the visible page text (`API credit balance`, `Showing invoices within the past 12 months`, table rows with invoice/status/amount/created columns) and are expected to need tuning against the live DOM in Task 8.

- [ ] **Step 1: Write `browser_scraper.py`**

```python
from playwright.sync_api import Page

OVERVIEW_URL = "https://platform.openai.com/settings/organization/billing/overview"
HISTORY_URL = "https://platform.openai.com/settings/organization/billing/history"


def fetch_balance_text(page: Page) -> str:
    page.goto(OVERVIEW_URL, wait_until="networkidle")
    balance_label = page.get_by_text("API credit balance", exact=False)
    balance_label.wait_for(timeout=15000)
    container = balance_label.locator("xpath=..")
    return container.inner_text()


def fetch_invoice_rows(page: Page) -> list[list[str]]:
    page.goto(HISTORY_URL, wait_until="networkidle")
    page.get_by_text("Showing invoices", exact=False).wait_for(timeout=15000)
    rows = page.locator("table tbody tr")
    count = rows.count()
    result = []
    for i in range(count):
        row = rows.nth(i)
        cells = row.locator("td")
        cell_count = cells.count()
        texts = [cells.nth(j).inner_text() for j in range(cell_count)]
        result.append(texts)
    return result
```

- [ ] **Step 2: Commit**

```bash
git add browser_scraper.py
git commit -m "feat: add Playwright page-reading functions for billing pages"
```

---

### Task 5: `login_setup.py` — one-time manual login script

**Files:**
- Create: `login_setup.py`

**Interfaces:**
- Produces: an authenticated session persisted to `./chrome_profile/`, consumed by `check_billing.py` in Task 6.

- [ ] **Step 1: Write `login_setup.py`**

```python
import os
from playwright.sync_api import sync_playwright

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(BASE_DIR, "chrome_profile")


def main() -> None:
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(PROFILE_DIR, headless=False)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://platform.openai.com/settings/organization/billing/overview")
        input(
            "A browser window has opened. Log in to OpenAI, navigate until you see "
            "the billing overview page, then press Enter here to save the session..."
        )
        context.close()
        print(f"Session saved to {PROFILE_DIR}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it manually and confirm login persists**

Run: `python login_setup.py`
Expected: a Chromium window opens; log in to OpenAI manually; after pressing Enter, the window closes and `chrome_profile/` now exists in the project directory.

- [ ] **Step 3: Commit**

```bash
git add login_setup.py
git commit -m "feat: add one-time manual login script"
```

---

### Task 6: `check_billing.py` — orchestrator

**Files:**
- Create: `check_billing.py`
- Test: `tests/test_check_billing.py`

**Interfaces:**
- Consumes:
  - `fetch_balance_text(page)`, `fetch_invoice_rows(page)` from Task 4
  - `extract_balance(raw_text)`, `normalize_invoice_row(cells)`, `is_login_page(url)` from Task 2
  - `append_balance_row(csv_path, timestamp, balance_usd)`, `merge_invoice_rows(csv_path, new_rows)` from Task 3
- Produces:
  - `log_run(log_path: str, success: bool, message: str) -> None`
  - `run() -> int` — exit code, 0 only if both balance and history fetches succeed.

Only `log_run` is unit-tested here since it's pure file I/O; `run()` requires a real browser session and is covered manually in Task 8.

- [ ] **Step 1: Write the failing test for `log_run`**

Create `tests/test_check_billing.py`:

```python
from check_billing import log_run


def test_log_run_appends_line(tmp_path):
    log_path = tmp_path / "bot.log"
    log_run(str(log_path), True, "balance=$7.99")
    content = log_path.read_text(encoding="utf-8")
    assert "[SUCCESS]" in content
    assert "balance=$7.99" in content


def test_log_run_appends_multiple_lines(tmp_path):
    log_path = tmp_path / "bot.log"
    log_run(str(log_path), True, "first")
    log_run(str(log_path), False, "second")
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert "[FAILURE]" in lines[1]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_check_billing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'check_billing'`

- [ ] **Step 3: Write `check_billing.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_check_billing.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add check_billing.py tests/test_check_billing.py
git commit -m "feat: add orchestrator script wiring scraper, parser, csv writer, and logging"
```

---

### Task 7: `run_bot.bat` and Task Scheduler setup docs

**Files:**
- Create: `run_bot.bat`
- Create: `SETUP.md`

**Interfaces:**
- Consumes: `check_billing.py` from Task 6 as the process it invokes.

- [ ] **Step 1: Write `run_bot.bat`**

```bat
@echo off
cd /d "%~dp0"
python check_billing.py
```

- [ ] **Step 2: Write `SETUP.md`**

```markdown
# Setup

## 1. Install dependencies

    pip install -r requirements.txt
    playwright install chromium

## 2. One-time login

    python login_setup.py

A browser window opens. Log in to your OpenAI account, wait until you can see
the billing overview page, then return to the terminal and press Enter. This
saves your session into `chrome_profile/` so scheduled runs don't need to log
in again.

## 3. Verify a manual run works

    python check_billing.py

Check that `credit_balance_log.csv`, `billing_history.csv`, and `bot.log` were
created/updated with data matching what you see in the browser.

## 4. Schedule it to run every 6 hours

Open an elevated Command Prompt and run (adjust the path if the project lives
somewhere else):

    schtasks /create /tn "OpenAI Billing Tracker" /tr "d:\Download_D\Scrape_GPT\run_bot.bat" /sc hourly /mo 6 /st 00:00

Verify it was created:

    schtasks /query /tn "OpenAI Billing Tracker"

To remove it later:

    schtasks /delete /tn "OpenAI Billing Tracker" /f

## Troubleshooting

- If `bot.log` shows "Session expired, run login_setup.py again" — re-run step 2.
- If `bot.log` shows a selector/timeout error, OpenAI likely changed the billing
  page layout — see Task 8 in the implementation plan for how to update the
  selectors in `browser_scraper.py`.
```

- [ ] **Step 3: Commit**

```bash
git add run_bot.bat SETUP.md
git commit -m "docs: add Task Scheduler entry point and setup instructions"
```

---

### Task 8: End-to-end manual verification and selector tuning

**Files:**
- Modify: `browser_scraper.py` (only if selectors need adjustment)

**Interfaces:**
- Consumes: the full pipeline from Tasks 1–7.

This task has no automated steps — its purpose is to confirm the best-effort selectors in `browser_scraper.py` (Task 4) actually match OpenAI's live DOM, since that structure wasn't inspectable while writing this plan.

- [ ] **Step 1: Run the one-time login**

Run: `python login_setup.py`, log in, press Enter.
Expected: `chrome_profile/` is created and populated.

- [ ] **Step 2: Run the main script manually**

Run: `python check_billing.py`
Expected: exits with code 0.

- [ ] **Step 3: Inspect `bot.log`**

Expected: a line ending in `[SUCCESS]` with both `balance=$X.XX` and `history: N new invoice(s)`.

If instead it shows a failure message about the balance or history selector not being found, proceed to Step 4. Otherwise skip to Step 6.

- [ ] **Step 4: Diagnose the real page structure**

Run: `playwright codegen https://platform.openai.com/settings/organization/billing/overview` (and separately for `/billing/history`) using the same `chrome_profile/` via `--user-data-dir`, e.g.:

```bash
playwright codegen --user-data-dir=chrome_profile https://platform.openai.com/settings/organization/billing/overview
```

Use the inspector to find the correct selectors for the balance text and the invoice table rows/cells.

- [ ] **Step 5: Update `browser_scraper.py` with corrected selectors**

Edit `fetch_balance_text` and/or `fetch_invoice_rows` in `browser_scraper.py` to use the selectors found in Step 4, then re-run Step 2 until `bot.log` shows `[SUCCESS]`.

- [ ] **Step 6: Verify CSV contents match the browser**

Open `credit_balance_log.csv` and `billing_history.csv` and compare against the values visible on the two billing pages in a real logged-in browser tab. Confirm the balance matches and every visible invoice row appears.

- [ ] **Step 7: Commit any selector fixes**

```bash
git add browser_scraper.py
git commit -m "fix: tune billing page selectors against live DOM"
```

(Skip this commit if no changes were needed in Step 5.)

- [ ] **Step 8: Register the scheduled task**

Follow `SETUP.md` section 4 to create the Windows Task Scheduler entry, then confirm with `schtasks /query /tn "OpenAI Billing Tracker"`.
