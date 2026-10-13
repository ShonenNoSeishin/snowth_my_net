"""Screenshot pages at desktop and phone width: python shot.py /path /other (SCHEME=light|dark)."""
import os
import sys

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    for width, height in ((1440, 900), (400, 800)):
        context = browser.new_context(viewport={"width": width, "height": height},
                                      color_scheme=os.environ.get("SCHEME", "light"))
        if os.environ.get("COOKIE"):          # "name=value", the session of the sample server
            name, _, value = os.environ["COOKIE"].partition("=")
            context.add_cookies([{"name": name, "value": value, "url": "http://127.0.0.1:8765"}])
        page = context.new_page()
        for path in sys.argv[1:]:
            page.goto("http://127.0.0.1:8765" + path)
            page.wait_for_timeout(300)
            name = path.strip("/").replace("/", "_").replace("?", "_").replace("=", "_") or "home"
            page.screenshot(path=f"/out/{name}_{width}.png", full_page=True)
    browser.close()
