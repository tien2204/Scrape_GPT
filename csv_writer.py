import csv
import os

BALANCE_FIELDS = ["timestamp", "balance_usd"]
INVOICE_FIELDS = ["invoice_number", "status", "amount", "created"]


def append_balance_row(csv_path: str, timestamp: str, balance_usd: str) -> None:
    file_exists = os.path.exists(csv_path)
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=BALANCE_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow({"timestamp": timestamp, "balance_usd": balance_usd})


def _read_existing_invoice_numbers(csv_path: str) -> set:
    if not os.path.exists(csv_path):
        return set()
    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return {row["invoice_number"] for row in reader}


def merge_invoice_rows(csv_path: str, new_rows: list[dict]) -> int:
    existing = _read_existing_invoice_numbers(csv_path)
    to_add = [row for row in new_rows if row["invoice_number"] not in existing]
    file_exists = os.path.exists(csv_path)
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=INVOICE_FIELDS)
        if not file_exists:
            writer.writeheader()
        for row in to_add:
            writer.writerow(row)
    return len(to_add)
