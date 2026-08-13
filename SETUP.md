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
