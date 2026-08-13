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
    assert "New invoice: 0FCE475C-0005 — $8.80 — Paid" in text


@patch("slack_notifier.requests.post")
def test_post_balance_update_sends_both_lines(mock_post):
    mock_post.return_value = _mock_response()
    invoice = {"invoice_number": "0FCE475C-0005", "status": "Paid", "amount": "$8.80", "created": "2026-06-01"}
    post_balance_update("https://hooks.example.com/x", "7.99", "8.99", [invoice])
    text = mock_post.call_args.kwargs["json"]["text"]
    assert "API credit balance: $7.99 (was $8.99)" in text
    assert "New invoice: 0FCE475C-0005 — $8.80 — Paid" in text


@patch("slack_notifier.requests.post")
def test_post_balance_update_sends_nothing_when_no_changes(mock_post):
    post_balance_update("https://hooks.example.com/x", "7.99", "7.99", [])
    mock_post.assert_not_called()


@patch("slack_notifier.requests.post")
def test_post_error_alert_sends_correct_message(mock_post):
    mock_post.return_value = _mock_response()
    post_error_alert("https://hooks.example.com/x", "Session expired, run login_setup.py again")
    text = mock_post.call_args.kwargs["json"]["text"]
    assert text == "⚠️ Billing bot failing: Session expired, run login_setup.py again"


@patch("slack_notifier.requests.post")
def test_post_recovery_sends_correct_message(mock_post):
    mock_post.return_value = _mock_response()
    post_recovery("https://hooks.example.com/x", "7.99")
    text = mock_post.call_args.kwargs["json"]["text"]
    assert text == "✅ Billing bot recovered — balance: $7.99"


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


@patch("slack_notifier.requests.post")
def test_post_balance_update_invoice_line_uses_receipt_emoji(mock_post):
    mock_post.return_value = _mock_response()
    invoice = {"invoice_number": "INV-1", "status": "Paid", "amount": "$5.00", "created": "2026-01-01"}
    post_balance_update("https://hooks.example.com/x", "7.99", "7.99", [invoice])
    text = mock_post.call_args.kwargs["json"]["text"]
    assert "\U0001F9FE New invoice: INV-1 — $5.00 — Paid" in text
