# OpenAI Billing Tracker — Design

**Date:** 2026-08-13
**Status:** Approved

## Purpose

Automatically capture two pieces of data from the OpenAI platform web UI on a recurring schedule, since neither is exposed through a public OpenAI API:

- **API credit balance** — from `platform.openai.com/settings/organization/billing/overview`
- **Billing history (invoices)** — from `platform.openai.com/settings/organization/billing/history`

Both pages are session/cookie-gated web UI with no public REST equivalent (OpenAI's Admin/Usage API exposes usage-cost data, not credit balance or Stripe invoice records), so the only viable approach is browser automation reading the rendered page.

## Architecture

Python + Playwright, driving a **dedicated Chromium profile** stored in `./chrome_profile/` — separate from the user's everyday Chrome profile, so scheduled runs never conflict with an already-open browser window.

### Components

1. **`login_setup.py`** — one-time, manual-run script.
   - Launches headed Chromium using the persistent profile at `./chrome_profile/`
   - Navigates to the OpenAI login page
   - Waits for the user to log in manually (polls for arrival on a billing page, or waits for Enter keypress confirmation)
   - Closes the browser, leaving the authenticated session stored in the profile directory for reuse

2. **`check_billing.py`** — main script, run headless on every scheduled invocation.
   - Opens a persistent context from `./chrome_profile/`
   - Navigates to `billing/overview`, reads the credit balance value (the dollar amount under "API credit balance")
   - Navigates to `billing/history`, reads the invoice table (invoice number, status, amount, created date) for all rows shown
   - Detects session expiry: if navigation lands on a login page or the expected billing elements aren't found, treat as a failed run
   - Writes results to CSV, appends a run entry to the log file
   - Closes the browser context

3. **CSV outputs:**
   - `credit_balance_log.csv` — columns: `timestamp, balance_usd`. One row appended per successful run — a time series of balance over time.
   - `billing_history.csv` — columns: `invoice_number, status, amount, created`. `invoice_number` is the dedup key: only newly-seen invoices are appended; existing rows are left untouched.

4. **`bot.log`** — one line per run: timestamp, success/failure, and either the values captured or the error encountered. Lets the user review scheduled-run history without opening the CSVs.

5. **`run_bot.bat`** — thin wrapper invoking `python check_billing.py`, used as the Windows Task Scheduler action target.

## Data Flow

```
Task Scheduler (every 6h)
  → run_bot.bat
    → check_billing.py
      → launch persistent Chromium context (chrome_profile/)
      → GET billing/overview → parse balance
      → GET billing/history → parse invoice rows
      → append credit_balance_log.csv
      → merge-append billing_history.csv (dedup by invoice_number)
      → append bot.log
      → close context
```

## Error Handling

- **Selector not found** (OpenAI changed the page layout): caught as an exception, logged to `bot.log` with timestamp and error detail, script exits non-zero. No partial/garbage data is written to CSV.
- **Session expired**: detected when navigation redirects to a login page or expected billing elements are absent. Logged clearly as "Session expired, run login_setup.py again," script exits. No retry within the same run — the next scheduled run (6h later) will surface the same failure until the user re-authenticates.
- **Network/page load timeout**: Playwright's default timeout (30s) applies; a timeout is treated as a failed run, logged, and the script exits. Recovery is left to the next scheduled run.
- **Partial success** (e.g., balance read succeeds but history table read fails): each data source is fetched and written independently — a failure in one does not block writing the other's result.

## Scheduling

Windows Task Scheduler, action = `run_bot.bat`, trigger = repeat every 6 hours. Runs headless, so no visible window appears during scheduled execution.

## Testing

Before wiring up Task Scheduler, `check_billing.py` is run manually and its CSV/log output is checked against the values visible in a real logged-in browser session, to confirm selectors and parsing are correct.

## Out of Scope

- No use of OpenAI's Admin/Usage API (rejected: doesn't expose credit balance or invoice records — only usage-cost breakdowns).
- No low-balance alerting/notifications — not requested.
- No cross-platform scheduling (Windows Task Scheduler only, matching the user's environment).
