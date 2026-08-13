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
