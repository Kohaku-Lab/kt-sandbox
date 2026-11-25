- Chromium is `/usr/bin/chromium`; Playwright has no browser of its own here, so pass the path:

      from playwright.sync_api import sync_playwright
      with sync_playwright() as p:
          browser = p.chromium.launch(executable_path="/usr/bin/chromium")
          page = browser.new_page()
          page.goto("file:///work/page.html")
          page.screenshot(path="/work/shot.png")
          browser.close()

- Without Playwright: `chromium --headless --no-sandbox --screenshot=/work/shot.png --window-size=800,600 file:///work/page.html`.
- Chromium needs more than the 64 processes of `strict`; it runs at `standard`, `open`, or `strict` opened with `--pids 256`.
