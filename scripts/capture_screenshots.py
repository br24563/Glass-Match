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

# (filename, Streamlit tab label, optional extra selector to await)
SHOTS = [
    ("01_matching", "Matching Glasses", 'div[data-baseweb="table"]'),
    ("02_spectral", "Spectral Analysis", ".js-plotly-plot"),
    ("03_detail", "Glass Detail", None),
    ("04_sources", "Data Sources", None),
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
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(ROOT / "app.py"),
         "--server.port", str(PORT), "--server.headless", "true"],
        cwd=str(ROOT), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
    )
    try:
        if not wait_http(f"{BASE}/_stcore/health", 120):
            raise RuntimeError("streamlit did not become healthy")
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(BASE, wait_until="domcontentloaded")
            # Wait for Streamlit to finish compiling the app (DB load etc.)
            # Streamlit >=1.64 renders tabs with data-testid="stTabs"/"stTab".
            page.wait_for_selector('div[data-testid="stTabs"]', timeout=180_000)
            page.wait_for_timeout(5_000)
            for fname, tab_text, extra in SHOTS:
                page.locator('[data-testid="stTab"]', has_text=tab_text).first.click()
                page.wait_for_timeout(3_000)
                if extra:
                    try:
                        page.wait_for_selector(extra, timeout=30_000)
                        page.wait_for_timeout(2_000)
                    except Exception:
                        pass
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
