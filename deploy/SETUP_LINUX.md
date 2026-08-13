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
