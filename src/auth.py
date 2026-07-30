from playwright.sync_api import sync_playwright

def login_and_save(base_url, storage_path):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(base_url)

        print("\nA browser window has opened.")
        print("Log in to Canvas there. Complete any SSO and OTP steps.")
        input("Once you can see your Canvas dashboard, press Enter here...")

        context.storage_state(path=storage_path)
        browser.close()
        print(f"Session saved to {storage_path}")