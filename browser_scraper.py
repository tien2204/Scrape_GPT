import re

from playwright.sync_api import Page

OVERVIEW_URL = "https://platform.openai.com/settings/organization/billing/overview"
HISTORY_URL = "https://platform.openai.com/settings/organization/billing/history"


def fetch_balance_text(page: Page) -> str:
    page.goto(OVERVIEW_URL, wait_until="domcontentloaded")
    balance_label = page.get_by_text("API credit balance", exact=False).first
    balance_label.wait_for(timeout=45000)
    container = balance_label.locator("xpath=ancestor::div[1]")
    # The label renders before the balance amount (async), so wait for the
    # dollar figure itself rather than just the label to avoid a race.
    container.get_by_text(re.compile(r"\$[\d,]+\.\d{2}")).first.wait_for(timeout=45000)
    return container.inner_text()


def fetch_invoice_rows(page: Page) -> list[list[str]]:
    page.goto(HISTORY_URL, wait_until="domcontentloaded")
    page.get_by_text("Showing invoices", exact=False).wait_for(timeout=45000)
    rows = page.locator("table tbody tr")
    count = rows.count()
    result = []
    for i in range(count):
        row = rows.nth(i)
        cells = row.locator("td")
        cell_count = cells.count()
        texts = [cells.nth(j).inner_text() for j in range(cell_count)]
        result.append(texts)
    return result
