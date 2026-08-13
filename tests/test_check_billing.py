from check_billing import log_run
from check_billing import decide_action


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
