#!/usr/bin/env python3
"""Headless screenshot harness — give the frontend some eyes.

Screenshots a set of routes at desktop (1440) and mobile (390) widths so UI
changes can actually be looked at (the frontend rules require this; a browser
isn't always around, so this makes the loop runnable anywhere).

Prereqs:
    pip install playwright && python -m playwright install chromium

Run against an already-running instance (the add-on, `python run.py`, etc.):
    python scripts/screenshots.py http://127.0.0.1:7745

Routes default to the app's key surfaces; override with SHOT_ROUTES, e.g.
    SHOT_ROUTES="items=/items,detail=/items/<id>" python scripts/screenshots.py URL

Output: PNGs under screenshots/ (git-ignored), named <route>-<width>.png.
"""
import os
import sys
import pathlib

from playwright.sync_api import sync_playwright

WIDTHS = {"desktop": 1440, "mobile": 390}
DEFAULT_ROUTES = {
    "dashboard": "/",
    "items": "/items",
    "scan": "/scan",
    "tools": "/tools",
    "report": "/report",
}


def _routes():
    raw = os.environ.get("SHOT_ROUTES", "").strip()
    if not raw:
        return DEFAULT_ROUTES
    out = {}
    for pair in raw.split(","):
        if "=" in pair:
            name, path = pair.split("=", 1)
            out[name.strip()] = path.strip()
    return out


def main():
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:7745").rstrip("/")
    out_dir = pathlib.Path(os.environ.get("SHOT_DIR", "screenshots"))
    out_dir.mkdir(exist_ok=True)
    routes = _routes()

    with sync_playwright() as p:
        browser = p.chromium.launch()
        shots = 0
        for name, path in routes.items():
            for label, width in WIDTHS.items():
                page = browser.new_page(viewport={"width": width, "height": 900},
                                        device_scale_factor=2)
                page.goto(base + path, wait_until="networkidle", timeout=20000)
                page.wait_for_timeout(400)  # let one-shot transitions settle
                dest = out_dir / f"{name}-{label}.png"
                page.screenshot(path=str(dest), full_page=True)
                page.close()
                shots += 1
                print(f"  {dest}")
        browser.close()
        print(f"{shots} screenshots → {out_dir}/")


if __name__ == "__main__":
    main()
