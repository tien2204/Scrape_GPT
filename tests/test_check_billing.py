from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from check_billing import log_run
from check_billing import decide_action
from check_billing import format_fal_timestamp, normalize_fal_event, fetch_fal_balance, fetch_fal_billing_events
from check_billing import get_low_balance_threshold, check_low_balance


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


def test_decide_action_returns_recovery_when_transitioning_from_failure_to_success():
    state = {"last_balance": "7.99", "last_status": "failure"}
    assert decide_action(True, state, "7.99", []) == "recovery"


def test_decide_action_returns_error_when_transitioning_from_success_to_failure():
    state = {"last_balance": "7.99", "last_status": "success"}
    assert decide_action(False, state, None, []) == "error"


def test_decide_action_returns_none_when_still_failing():
    state = {"last_balance": "7.99", "last_status": "failure"}
    assert decide_action(False, state, None, []) == "none"


def test_decide_action_returns_none_on_first_run_with_no_prior_balance():
    state = {"last_balance": None, "last_status": "success"}
    assert decide_action(True, state, "7.99", []) == "none"


def test_decide_action_returns_balance_update_when_balance_changed():
    state = {"last_balance": "8.99", "last_status": "success"}
    assert decide_action(True, state, "7.99", []) == "balance_update"


def test_decide_action_returns_balance_update_when_new_invoices_present():
    state = {"last_balance": "7.99", "last_status": "success"}
    invoice = {"invoice_number": "INV-1", "status": "Paid", "amount": "$5.00", "created": "2026-01-01"}
    assert decide_action(True, state, "7.99", [invoice]) == "balance_update"


def test_decide_action_returns_none_when_nothing_changed():
    state = {"last_balance": "7.99", "last_status": "success"}
    assert decide_action(True, state, "7.99", []) == "none"


def test_format_fal_timestamp_uses_z_suffix():
    dt = datetime(2026, 8, 13, 5, 30, 0, tzinfo=timezone.utc)
    assert format_fal_timestamp(dt) == "2026-08-13T05:30:00Z"


def test_normalize_fal_event_extracts_and_formats_fields():
    raw = {
        "request_id": "REQ-1",
        "endpoint_id": "fal-ai/flux/dev",
        "timestamp": "2026-08-07T10:20:05.446594000Z",
        "cost_total": 5.56614,
        "cost_subtotal": 5.56614,
        "output_units": 260.1,
    }
    assert normalize_fal_event(raw) == {
        "request_id": "REQ-1",
        "endpoint_id": "fal-ai/flux/dev",
        "cost_total": "5.5661",
        "timestamp": "2026-08-07T10:20:05.446594000Z",
    }


def _mock_get_response(json_data):
    response = MagicMock()
    response.json.return_value = json_data
    response.raise_for_status = MagicMock()
    return response


@patch("check_billing.requests.get")
def test_fetch_fal_balance_returns_current_balance(mock_get):
    mock_get.return_value = _mock_get_response({"username": "u", "credits": {"current_balance": -5.61, "currency": "USD"}})
    balance = fetch_fal_balance("test-key")
    assert balance == -5.61
    call = mock_get.call_args
    assert call.args[0] == "https://api.fal.ai/v1/account/billing"
    assert call.kwargs["headers"] == {"Authorization": "Key test-key"}
    assert call.kwargs["params"] == {"expand": "credits"}


@patch("check_billing.requests.get")
def test_fetch_fal_billing_events_single_page(mock_get):
    mock_get.return_value = _mock_get_response({
        "billing_events": [{"request_id": "REQ-1"}],
        "next_cursor": None,
        "has_more": False,
    })
    events = fetch_fal_billing_events("test-key", "2026-08-01T00:00:00Z")
    assert events == [{"request_id": "REQ-1"}]
    assert mock_get.call_count == 1
    assert mock_get.call_args.kwargs["params"]["start"] == "2026-08-01T00:00:00Z"


@patch("check_billing.requests.get")
def test_fetch_fal_billing_events_follows_pagination(mock_get):
    mock_get.side_effect = [
        _mock_get_response({"billing_events": [{"request_id": "REQ-1"}], "next_cursor": "page2", "has_more": True}),
        _mock_get_response({"billing_events": [{"request_id": "REQ-2"}], "next_cursor": None, "has_more": False}),
    ]
    events = fetch_fal_billing_events("test-key", "2026-08-01T00:00:00Z")
    assert events == [{"request_id": "REQ-1"}, {"request_id": "REQ-2"}]
    assert mock_get.call_count == 2
    assert mock_get.call_args_list[1].kwargs["params"]["cursor"] == "page2"


def test_get_low_balance_threshold_defaults_to_ten(monkeypatch):
    monkeypatch.delenv("ALERT_ZERO_BALANCE", raising=False)
    assert get_low_balance_threshold() == 10.0


def test_get_low_balance_threshold_reads_env(monkeypatch):
    monkeypatch.setenv("ALERT_ZERO_BALANCE", "25.0")
    assert get_low_balance_threshold() == 25.0


@patch("check_billing.post_low_balance_warning")
def test_check_low_balance_warns_when_below_threshold(mock_post, monkeypatch):
    monkeypatch.setenv("ALERT_ZERO_BALANCE", "10.0")
    check_low_balance("https://hooks.example.com/x", "OpenAI", "7.99")
    mock_post.assert_called_once_with("https://hooks.example.com/x", "OpenAI", "7.99", 10.0)


@patch("check_billing.post_low_balance_warning")
def test_check_low_balance_silent_when_above_threshold(mock_post, monkeypatch):
    monkeypatch.setenv("ALERT_ZERO_BALANCE", "10.0")
    check_low_balance("https://hooks.example.com/x", "OpenAI", "15.00")
    mock_post.assert_not_called()


@patch("check_billing.post_low_balance_warning")
def test_check_low_balance_warns_for_negative_fal_balance(mock_post, monkeypatch):
    monkeypatch.setenv("ALERT_ZERO_BALANCE", "10.0")
    check_low_balance("https://hooks.example.com/x", "fal.ai", "-5.61")
    mock_post.assert_called_once_with("https://hooks.example.com/x", "fal.ai", "-5.61", 10.0)
