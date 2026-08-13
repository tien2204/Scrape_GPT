from check_billing import log_run


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
