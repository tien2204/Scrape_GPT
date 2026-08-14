import csv
from csv_writer import (
    append_balance_row,
    merge_invoice_rows,
    get_new_invoice_rows,
    merge_fal_event_rows,
    get_new_fal_event_rows,
)


def test_append_balance_row_creates_file_with_header(tmp_path):
    csv_path = tmp_path / "balance.csv"
    append_balance_row(str(csv_path), "2026-08-13T10:00:00", "7.99")
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows == [{"timestamp": "2026-08-13T10:00:00", "balance_usd": "7.99"}]


def test_append_balance_row_appends_without_duplicate_header(tmp_path):
    csv_path = tmp_path / "balance.csv"
    append_balance_row(str(csv_path), "2026-08-13T10:00:00", "7.99")
    append_balance_row(str(csv_path), "2026-08-13T16:00:00", "6.50")
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2
    assert rows[1]["balance_usd"] == "6.50"


def test_merge_invoice_rows_creates_file(tmp_path):
    csv_path = tmp_path / "history.csv"
    new_rows = [
        {"invoice_number": "INV-1", "status": "Paid", "amount": "$5.00", "created": "2026-01-01"}
    ]
    added = merge_invoice_rows(str(csv_path), new_rows)
    assert added == 1
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows == new_rows


def test_merge_invoice_rows_skips_duplicates(tmp_path):
    csv_path = tmp_path / "history.csv"
    row = {"invoice_number": "INV-1", "status": "Paid", "amount": "$5.00", "created": "2026-01-01"}
    merge_invoice_rows(str(csv_path), [row])
    added = merge_invoice_rows(str(csv_path), [row])
    assert added == 0
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1


def test_merge_invoice_rows_adds_only_new_rows(tmp_path):
    csv_path = tmp_path / "history.csv"
    row1 = {"invoice_number": "INV-1", "status": "Paid", "amount": "$5.00", "created": "2026-01-01"}
    row2 = {"invoice_number": "INV-2", "status": "Paid", "amount": "$6.00", "created": "2026-02-01"}
    merge_invoice_rows(str(csv_path), [row1])
    added = merge_invoice_rows(str(csv_path), [row1, row2])
    assert added == 1
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2


def test_get_new_invoice_rows_returns_all_rows_when_file_missing(tmp_path):
    csv_path = tmp_path / "history.csv"
    row = {"invoice_number": "INV-1", "status": "Paid", "amount": "$5.00", "created": "2026-01-01"}
    assert get_new_invoice_rows(str(csv_path), [row]) == [row]


def test_get_new_invoice_rows_excludes_existing_invoice_numbers(tmp_path):
    csv_path = tmp_path / "history.csv"
    row1 = {"invoice_number": "INV-1", "status": "Paid", "amount": "$5.00", "created": "2026-01-01"}
    row2 = {"invoice_number": "INV-2", "status": "Paid", "amount": "$6.00", "created": "2026-02-01"}
    merge_invoice_rows(str(csv_path), [row1])
    result = get_new_invoice_rows(str(csv_path), [row1, row2])
    assert result == [row2]


def test_get_new_invoice_rows_does_not_write_anything(tmp_path):
    csv_path = tmp_path / "history.csv"
    row = {"invoice_number": "INV-1", "status": "Paid", "amount": "$5.00", "created": "2026-01-01"}
    get_new_invoice_rows(str(csv_path), [row])
    assert not csv_path.exists()


def test_merge_fal_event_rows_creates_file(tmp_path):
    csv_path = tmp_path / "fal_events.csv"
    row = {"request_id": "REQ-1", "endpoint_id": "fal-ai/flux/dev", "cost_total": "5.5661", "timestamp": "2026-08-07T10:20:05Z"}
    added = merge_fal_event_rows(str(csv_path), [row])
    assert added == 1
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows == [row]


def test_merge_fal_event_rows_skips_duplicates_by_request_id(tmp_path):
    csv_path = tmp_path / "fal_events.csv"
    row = {"request_id": "REQ-1", "endpoint_id": "fal-ai/flux/dev", "cost_total": "5.5661", "timestamp": "2026-08-07T10:20:05Z"}
    merge_fal_event_rows(str(csv_path), [row])
    added = merge_fal_event_rows(str(csv_path), [row])
    assert added == 0
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1


def test_get_new_fal_event_rows_returns_all_rows_when_file_missing(tmp_path):
    csv_path = tmp_path / "fal_events.csv"
    row = {"request_id": "REQ-1", "endpoint_id": "fal-ai/flux/dev", "cost_total": "5.5661", "timestamp": "2026-08-07T10:20:05Z"}
    assert get_new_fal_event_rows(str(csv_path), [row]) == [row]


def test_get_new_fal_event_rows_excludes_existing_request_ids(tmp_path):
    csv_path = tmp_path / "fal_events.csv"
    row1 = {"request_id": "REQ-1", "endpoint_id": "fal-ai/flux/dev", "cost_total": "5.5661", "timestamp": "2026-08-07T10:20:05Z"}
    row2 = {"request_id": "REQ-2", "endpoint_id": "openai/gpt-image-2", "cost_total": "0.0444", "timestamp": "2026-08-07T10:11:24Z"}
    merge_fal_event_rows(str(csv_path), [row1])
    result = get_new_fal_event_rows(str(csv_path), [row1, row2])
    assert result == [row2]
