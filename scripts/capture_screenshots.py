"""Capture README screenshots from a live GlassMatch instance.

Usage:
    .venv\\Scripts\\python scripts\\capture_screenshots.py

Starts Streamlit headlessly on port 8511 (never touches a running 8501),
drives it with Playwright using the locally installed Microsoft Edge
(``channel="msedge"`` — no browser download required), clicks through the
main tabs and writes PNGs to ``docs/screenshots/``.

Output is deterministic: same default state a fresh visitor sees.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots"
PORT = 8511
BASE = f"http://localhost:{PORT}"

# (filename, Streamlit tab label, optional selector to await, optional text to scroll to)
SHOTS = [
    # Anchors bring the meaningful content into frame: on a 900px viewport the
    # ranked table, the plot and the equivalency panel all start below the fold.
    # "px:N" scrolls by pixels (predictable, and the only reliable mode for
    # stDataFrame headers and Plotly SVGs, which are not DOM text); a bare string
    # scrolls to matching text.
    ("01_matching", "Matching Glasses", 'div[data-testid="stDataFrame"]', "px:700"),
    ("02_spectral", "Spectral Analysis", ".js-plotly-plot", "px:420"),
    ("03_detail", "Glass Detail", 'div[data-testid="stDataFrame"]', "px:260"),
    ("04_sources", "Data Sources", 'div[data-testid="stDataFrame"]', None),
    ("05_equivalency", "Database Explorer", 'div[data-testid="stSlider"]',
     "Equivalency candidates"),
]


def wait_http(url: str, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(1)
    return False


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, STREAMLIT_BROWSER_GATHER_USAGE_STATS="false")
    # Keep the server log: a silent startup failure previously looked like an
    # unexplained 120 s timeout because the output went to DEVNULL.
    log_path = Path(os.environ.get("TEMP", "/tmp")) / "glassmatch_capture_streamlit.log"
    log = open(log_path, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(ROOT / "app.py"),
         "--server.port", str(PORT), "--server.headless", "true"],
        cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    try:
        if not wait_http(f"{BASE}/_stcore/health", 120):
            log.flush()
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
            raise RuntimeError(
                f"streamlit did not become healthy on port {PORT}.\n"
                f"--- server log ({log_path}) ---\n{tail}")
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            # Taller viewport so each shot frames real content, not just headers.
            page = browser.new_page(viewport={"width": 1440, "height": 1080})
            page.goto(BASE, wait_until="domcontentloaded")
            # Wait for Streamlit to finish compiling the app (DB load etc.)
            # Streamlit >=1.64 renders tabs with data-testid="stTabs"/"stTab".
            page.wait_for_selector('div[data-testid="stTabs"]', timeout=180_000)
            page.wait_for_timeout(5_000)
            for fname, tab_text, extra, anchor in SHOTS:
                page.locator('[data-testid="stTab"]', has_text=tab_text).first.click()
                page.wait_for_timeout(3_000)
                if extra:
                    try:
                        page.wait_for_selector(extra, timeout=30_000)
                        page.wait_for_timeout(2_000)
                    except Exception:
                        pass
                if anchor:
                    try:
                        if anchor.startswith("px:"):
                            page.evaluate(
                                "y => window.scrollBy(0, y)", int(anchor[3:]))
                        elif anchor.startswith("css:"):
                            page.locator(anchor[4:]).first.scroll_into_view_if_needed()
                        else:
                            page.get_by_text(anchor, exact=False).first.scroll_into_view_if_needed()
                        page.wait_for_timeout(2_500)
                    except Exception:
                        print(f"warning: anchor {anchor!r} not found for {fname}")
                page.screenshot(path=str(OUT / f"{fname}.png"))
                print(f"captured {fname}.png")
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    main()
