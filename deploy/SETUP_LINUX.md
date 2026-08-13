# Linux Deployment

This runs the billing bot every 15 minutes on a headless Linux server using
a virtual display (Xvfb) so Chrome renders normally (not `--headless`,
which is reliably blocked by Cloudflare on OpenAI's billing pages).

## 1. Install system dependencies

    sudo apt update
    sudo apt install -y xvfb
    playwright install-deps chromium

**Note on `xvfb-run`:** the `apt` package above includes the `xvfb-run`
wrapper script. If Xvfb was instead installed into a conda environment
(e.g. `conda install -c conda-forge xorg-xvfb-server`, as on this
project's GPU server), only the `Xvfb` binary is present — `xvfb-run` is
a separate Debian shell script, not part of X.org, and conda-forge does
not ship it. In that case use `deploy/run_with_xvfb.sh` in place of
`xvfb-run` everywhere below; it starts/stops an Xvfb display by hand and
activates the `billing-bot` conda env before running the given command.

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

Cron does not read your shell profile by default, so `SLACK_WEBHOOK_URL`
needs to be made available to the cron command explicitly. Two options:

**Option A — `.env` file (what `deploy/crontab.txt` uses):** create a
`.env` file in the project root (never commit it — it's gitignored):

    SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."

and source it in the cron command itself:

    */15 * * * * cd /path/to/project && set -a && . ./.env && set +a && ./deploy/run_with_xvfb.sh python3 check_billing.py >> cron.log 2>&1

(matches `deploy/crontab.txt` verbatim — edit only the `cd` path)

**Option B — shell profile:** add `export SLACK_WEBHOOK_URL="..."` to
`~/.bashrc` and prefix the cron command with sourcing it instead:

    */15 * * * * cd /path/to/project && . ~/.bashrc && xvfb-run -a python3 check_billing.py >> cron.log 2>&1

## 5. Verify a manual run works

    xvfb-run python3 check_billing.py

Or, if using `deploy/run_with_xvfb.sh` (see the note in step 1):

    ./deploy/run_with_xvfb.sh python3 check_billing.py

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
- If runs fail or take ~60s and finish with a timeout error even inside
  Xvfb: confirm Chrome is *not* being launched with `--headless` anywhere
  in `check_billing.py`'s `launch_persistent_context` call (this branch
  was found live to be reliably blocked by a Cloudflare "Just a moment..."
  interstitial when `headless=True`, even inside Xvfb — a true headed
  launch against the virtual display passes), and that
  `--disable-blink-features=AutomationControlled` is present.
- To diagnose a block manually: run a small script that calls
  `page.goto(...)`, `page.wait_for_timeout(8000)`, then checks
  `page.title()` (a Cloudflare block shows `"Just a moment..."`),
  `"API credit balance" in page.content()`, and `page.screenshot(path=...)`.
  A WebGL renderer string containing `SwiftShader` (via
  `gl.getParameter(dbgInfo.UNMASKED_RENDERER_WEBGL)`) is not by itself
  proof of a block on this server — Xvfb sessions here report SwiftShader
  even when headed mode passes cleanly; treat the page title and content
  check as authoritative, not the renderer string.
- If `.env` sourcing silently fails under cron only (works fine when you
  paste the same command into an interactive `bash` shell): cron runs jobs
  under `/bin/sh` (often `dash`), and POSIX `.`/source only searches
  `$PATH` for a bare filename — unlike bash's `source`, it does not fall
  back to the current directory. `. .env` finds nothing under dash even
  though the file is right there; the fix is the explicit relative path
  `. ./.env`, which works under both. This is easy to test in isolation:
  `/bin/sh -c 'cd /path/to/project && . .env'` fails with `not found`
  even when `.env` exists, while `. ./.env` succeeds.
- If the balance amount comes back missing (e.g. `extract_balance` raises
  "Could not find a dollar amount"), this is not a Cloudflare block — the
  "API credit balance" label renders slightly before the dollar figure
  next to it. `browser_scraper.fetch_balance_text` waits for the `$X.XX`
  text itself (not just the label) to avoid this race; if it recurs, the
  page's DOM structure likely changed.
