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
        lines.append(f"💰 API credit balance: ${balance} (was ${previous_balance})")
    for invoice in new_invoices:
        lines.append(
            f"🧾 New invoice: {invoice['invoice_number']} — {invoice['amount']} — {invoice['status']}"
        )
    if not lines:
        return
    _post(webhook_url, "\n".join(lines))


def post_error_alert(webhook_url: str, message: str) -> None:
    _post(webhook_url, f"⚠️ Billing bot failing: {message}")


def post_recovery(webhook_url: str, balance: str) -> None:
    _post(webhook_url, f"✅ Billing bot recovered — balance: ${balance}")


def post_status(webhook_url: str, balance: str) -> None:
    _post(webhook_url, f"📊 [OpenAI] API credit balance: ${balance}")


def _fmt_usd(amount: str) -> str:
    # fal.ai balances can go negative (postpaid/overdrawn) — "-$5.61" reads
    # better than "$-5.61".
    return f"-${amount[1:]}" if amount.startswith("-") else f"${amount}"


def post_fal_balance_update(webhook_url: str, balance: str, previous_balance: str | None, new_events: list[dict]) -> None:
    lines = []
    if previous_balance is not None and balance != previous_balance:
        lines.append(f"💰 [fal.ai] Credit balance: {_fmt_usd(balance)} (was {_fmt_usd(previous_balance)})")
    for event in new_events:
        lines.append(f"🧾 [fal.ai] Usage: {event['endpoint_id']} — {_fmt_usd(event['cost_total'])}")
    if not lines:
        return
    _post(webhook_url, "\n".join(lines))


def post_fal_error_alert(webhook_url: str, message: str) -> None:
    _post(webhook_url, f"⚠️ [fal.ai] Billing bot failing: {message}")


def post_fal_recovery(webhook_url: str, balance: str) -> None:
    _post(webhook_url, f"✅ [fal.ai] Billing bot recovered — balance: {_fmt_usd(balance)}")


def post_fal_status(webhook_url: str, balance: str) -> None:
    _post(webhook_url, f"📊 [fal.ai] Credit balance: {_fmt_usd(balance)}")
