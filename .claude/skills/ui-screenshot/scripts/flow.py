"""Example flow: upload a CSV on /import, check it, apply it. Adapt for other pages."""
from playwright.sync_api import sync_playwright

CSV = b"mac,name\n00:00:5e:00:53:a0,serveur compta\nzzz,x\n"
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1200, "height": 800})
    page.goto("http://127.0.0.1:8765/import")
    page.set_input_files("input[type=file]", files=[{"name": "n.csv", "mimeType": "text/csv",
                                                     "buffer": CSV}])
    page.click("button.primary")
    page.wait_for_load_state()
    page.screenshot(path="/out/check.png", full_page=True)
    browser.close()
