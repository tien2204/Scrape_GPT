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
