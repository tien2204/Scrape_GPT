import os
from playwright.sync_api import sync_playwright

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(BASE_DIR, "chrome_profile")


def main() -> None:
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(PROFILE_DIR, headless=False)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://platform.openai.com/settings/organization/billing/overview")
        input(
            "A browser window has opened. Log in to OpenAI, navigate until you see "
            "the billing overview page, then press Enter here to save the session..."
        )
        context.close()
        print(f"Session saved to {PROFILE_DIR}")


if __name__ == "__main__":
    main()
