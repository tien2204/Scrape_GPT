# Linux 24/7 Billing Bot with Slack Alerts — Design

**Date:** 2026-08-13
**Status:** Approved

## Purpose

Pivot the OpenAI billing tracker (originally built for Windows Task Scheduler, polling every 6 hours, CSV-only) to run unattended 24/7 on a GPU Linux server, polling every 15 minutes, and pushing balance/invoice changes to a Slack channel via webhook. The Windows implementation (Task Scheduler, `run_bot.bat`, `SETUP.md`) is left as-is on the `openai-billing-tracker` branch; this work happens on a new branch, `linux-billing-bot`, branched off it.

## Background: the Cloudflare problem

OpenAI's billing pages sit behind Cloudflare bot protection. Testing on Windows found:
- Headless Chromium (bundled or real Chrome channel), with or without `--disable-blink-features=AutomationControlled`, with or without `playwright-stealth` — always blocked ("Just a moment..." interstitial).
- A headed window positioned off-screen (`--window-position=-32000,-32000`) passes Cloudflare's check but Chrome throttles rendering for occluded/off-screen windows, so the page content never fully loads.
- A genuinely on-screen headed window with `--disable-blink-features=AutomationControlled` reliably passes and fully renders.

On the Linux GPU server, the equivalent of "genuinely on-screen headed" is a real X display for Chrome to render into — `Xvfb` (virtual framebuffer) provides that display without a physical monitor, and Chrome runs in normal (non-`--headless`) mode against it, using the server's real GPU for rendering. This is a different code path from software `--headless` and is expected to pass the same checks that a real headed window passed on Windows. This must still be verified once against the live site (see Testing) before being trusted for unattended 24/7 operation.

## Architecture

`cron` fires every 15 minutes. Each run:
1. `xvfb-run` starts a fresh `Xvfb` virtual display and launches `check_billing.py` inside it.
2. `check_billing.py` opens the persistent Chromium context (headed, `--disable-blink-features=AutomationControlled`, no `--headless`), reusing session cookies from `chrome_profile/` — which was `scp`'d over from the already-authenticated Windows machine (no fresh login flow on the server itself; the server has no display of its own for one).
3. Scrapes both billing pages, writes to `credit_balance_log.csv` and `billing_history.csv` exactly as before.
4. Compares the new balance and invoice count against `state.json` (the last run's recorded balance and status) to decide whether anything changed.
5. If something changed (balance moved, or new invoices appeared), posts a message to Slack. If the run failed and the previous run had succeeded, posts an error alert. If the run succeeded and the previous run had failed, posts a recovery message. Otherwise, sends nothing.
6. Updates `state.json` with this run's balance and status for the next comparison.

CSV files remain the durable historical record, written on every run regardless of Slack activity. Slack is a notification layer on top, not a replacement — a failed Slack POST never blocks or invalidates the CSV write.

## Reused Components (unchanged from the Windows branch)

- `billing_parser.py` — `extract_balance`, `normalize_invoice_row`, `is_login_page`
- `csv_writer.py` — `append_balance_row`, `merge_invoice_rows`
- `browser_scraper.py` — `fetch_balance_text`, `fetch_invoice_rows`, including the `ancestor::div[1]` balance-container selector fix and 30-second wait timeouts already found necessary during Windows testing

## New Components

### `state.py`

Pure file I/O, mirrors `csv_writer.py`'s style:
- `read_state(state_path: str) -> dict` — returns `{"last_balance": None, "last_status": "success"}` if the file doesn't exist yet (first-ever run); otherwise parses the JSON.
- `write_state(state_path: str, balance: str | None, status: str) -> None` — overwrites `state.json` with `{"last_balance": balance, "last_status": status}`.

### `slack_notifier.py`

- `post_balance_update(webhook_url: str, balance: str, previous_balance: str | None, new_invoices: list[dict]) -> None`
- `post_error_alert(webhook_url: str, message: str) -> None`
- `post_recovery(webhook_url: str, balance: str) -> None`

Each function builds a plain-text Slack message (see Message Format below) and does a single `requests.post(webhook_url, json={"text": ...})`. Failures (network error, non-2xx response) are caught inside these functions and logged to `cron.log` via a passed-in logger/print — they never raise, so a Slack outage can't break the scraping run.

### `check_billing.py` (modified)

After the existing balance/history fetch-and-write logic (unchanged), add:
1. Read `state.json` via `state.read_state`.
2. Determine `overall_success = balance_ok and history_ok` (as today).
3. **Failure edge:** if `not overall_success` and `state["last_status"] == "success"`: call `slack_notifier.post_error_alert` with the failure message(s).
4. **Recovery edge:** if `overall_success` and `state["last_status"] == "failure"`: call `slack_notifier.post_recovery` with the new balance.
5. **Change notification:** if `overall_success` and `state["last_status"] == "success"` (steady-state, not an edge): if `balance != state["last_balance"]` or `added > 0` new invoices, call `slack_notifier.post_balance_update` with old/new balance and the new invoice dicts.
6. Write the new state via `state.write_state`.

`SLACK_WEBHOOK_URL` is read from an environment variable (never hardcoded or committed).

## Message Format

**Balance/invoice change:**
```
💰 API credit balance: $7.99 (was $8.99)
🧾 New invoice: 0FCE475C-0005 — $8.80 — Paid
```
The balance line is omitted if only invoices changed; the invoice line(s) are omitted if only the balance changed. At least one line is always present when this function is called (it's only called when something changed).

**Error alert (failure edge only):**
```
⚠️ Billing bot failing: Session expired, run login_setup.py again
```

**Recovery (success edge only):**
```
✅ Billing bot recovered — balance: $7.99
```

**First-ever run** (no `state.json` yet): treated as `last_status: "success"`, `last_balance: None`. State is written normally but no Slack message is sent — there's nothing to compare against yet.

## Deployment Files

### `deploy/crontab.txt`
```
*/15 * * * * cd /path/to/project && xvfb-run -a python3 check_billing.py >> cron.log 2>&1
```

### `deploy/SETUP_LINUX.md`
Documents, in order:
1. `apt install xvfb` plus Chromium's runtime dependencies.
2. `scp` command to copy `chrome_profile/` from the Windows machine to the Linux server.
3. `pip install -r requirements.txt` and `playwright install chromium`.
4. Setting `SLACK_WEBHOOK_URL` (via `.env` or shell profile — not committed to git).
5. Installing the crontab line (`crontab deploy/crontab.txt` or appending it to the user's existing crontab).
6. A `logrotate` snippet (or manual truncate-on-schedule cron entry) for `cron.log`, since 96 runs/day will otherwise grow it indefinitely.
7. **Known limitation:** when the copied session eventually expires, the server has no display to re-authenticate with. The runbook step is: log in again on the Windows machine (or any machine with a display) via `login_setup.py`, then `scp` the refreshed `chrome_profile/` over again.

## Error Handling

- **Xvfb fails to start:** `xvfb-run` exits non-zero, Chrome never launches, this surfaces as a normal exception in `check_billing.py`'s existing try/except blocks — logged and Slack-alerted via the failure edge like any other failure.
- **Cloudflare still blocks despite Xvfb:** indistinguishable from a selector timeout in the existing error handling — logged, alerted once on the edge, silent on repeat. Sustained failures here indicate Xvfb+GPU isn't sufficient and needs further investigation, not a deeper workaround baked into this design.
- **Slack webhook POST fails:** caught inside `slack_notifier.py`, logged locally, never raises — doesn't block CSV writes or crash the run.
- **`cron.log` growth:** handled by `logrotate` (ops tooling), not custom Python log-rotation code.
- **Session expiry with no display on the server:** documented runbook (re-copy profile from Windows), not solved in code.

## Testing

1. Copy `chrome_profile/` to the Linux server, install `xvfb` and Python deps, run `xvfb-run python3 check_billing.py` manually once. Confirm CSVs update and — since this is the first-ever run — no Slack message fires (only `state.json` gets created).
2. Manually edit `state.json`'s `last_balance` to a different value, re-run, and confirm a "balance changed" Slack message fires with the correct old/new values.
3. Temporarily point `PROFILE_DIR` at an empty/invalid directory to force two consecutive failures, and confirm only the *first* posts a Slack error alert (edge-triggered silence on the second). Then restore `PROFILE_DIR` and confirm the next successful run posts a recovery message.
4. Install the crontab line and observe `cron.log` through one real 15-minute cycle before leaving the server unattended.

## Out of Scope

- Solving session re-authentication remotely (documented as a manual runbook step instead).
- Custom log rotation code (delegated to `logrotate`).
- Running both Windows Task Scheduler and the Linux cron job simultaneously against the same CSV files — this design assumes the Linux server becomes the sole 24/7 runner; the Windows branch remains available for manual/ad-hoc use but is not scheduled in parallel.
- Rate-limit or ToS risk analysis for 15-minute polling frequency — not raised as a concern by the user, not addressed further here.
