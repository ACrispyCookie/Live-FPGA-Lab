"""Browser checks for the lab's frontend, run from a workstation against the deployed site.

    .venv-checks/bin/python src/frontend/checks/check.py [--base https://fpga.njason.dev] [--only idle,busy] [--widths 390,1440]

For every fixture (needs a build with VITE_MOCK_STATES=1) and width: no horizontal overflow, no console or page
errors, the trace stays clear of the content, and a screenshot lands in src/frontend/checks/out/. Then a flow
check on the idle fixture: pressing Start changes the session panel within a frame and sends one request.
Exit code 1 when anything fails; the failures are printed at the end.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

FIXTURES = ["connecting", "idle", "busy", "requesting", "queued", "starting", "active", "ending", "ended", "project", "fault", "offline", "reconnecting", "error"]
WIDTHS = [360, 390, 768, 1100, 1440]
OUT = Path(__file__).resolve().parent / "out"


def open_page(page: Page, url: str, errors: list[str]) -> None:
    page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type in ("error",) else None)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.goto(url, wait_until="networkidle")
    page.wait_for_timeout(1200)
    # the sections switch on as the trace reaches them: scroll through the page so a full-page capture shows everything
    height = page.evaluate("document.documentElement.scrollHeight")
    for y in range(0, height + 600, 500):
        page.evaluate(f"window.scrollTo(0, {y})")
        page.wait_for_timeout(120)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(600)


def check_layout(page: Page, name: str, width: int, failures: list[str]) -> None:
    overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    if overflow > 0:
        failures.append(f"{name}@{width}: horizontal overflow of {overflow}px")
    gap = page.evaluate(
        """() => {
          const svg = document.querySelector('svg.trace'); const main = document.querySelector('main');
          if (!svg || !main) return null;
          const x = parseFloat(getComputedStyle(svg.parentElement).getPropertyValue('--trace-x')) || 18.5;
          return main.getBoundingClientRect().left - (svg.getBoundingClientRect().left + x);
        }"""
    )
    if gap is None:
        failures.append(f"{name}@{width}: no trace or main element")
    elif gap < 28:
        failures.append(f"{name}@{width}: trace only {gap:.0f}px from the content (need 28)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="https://fpga.njason.dev")
    ap.add_argument("--only", default="")
    ap.add_argument("--widths", default=",".join(map(str, WIDTHS)))
    ap.add_argument("--no-mock", action="store_true", help="only load the real page, no fixtures")
    ap.add_argument("--chrome", default="", help="path to a Chrome binary to use instead of Playwright's bundled browser")
    args = ap.parse_args()
    fixtures = [f for f in FIXTURES if not args.only or f in args.only.split(",")]
    widths = [int(w) for w in args.widths.split(",")]
    OUT.mkdir(exist_ok=True)
    failures: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=args.chrome or None)
        targets = [("real", f"{args.base}/")] + ([] if args.no_mock else [(f, f"{args.base}/?mock={f}") for f in fixtures])
        for name, url in targets:
            for width in widths:
                ctx = browser.new_context(viewport={"width": width, "height": 900}, device_scale_factor=1)
                page = ctx.new_page()
                errors: list[str] = []
                open_page(page, url, errors)
                failures.extend(f"{name}@{width}: {e}" for e in errors)
                headline = page.evaluate("(document.querySelector('.session .big, .session .demo-name, .sbar .who') || {}).textContent || ''")
                pill = page.evaluate("(document.querySelector('.boardpill') || {}).textContent || ''")
                print(f"{name}@{width}: pill='{pill.strip()}' headline='{headline.strip()}'")
                check_layout(page, name, width, failures)
                page.screenshot(path=str(OUT / f"{name}-{width}.png"), full_page=True)
                ctx.close()

        if not args.no_mock and "idle" in fixtures:
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            page = ctx.new_page()
            errors = []
            open_page(page, f"{args.base}/?mock=idle", errors)
            first = page.locator(".demo button.btn").first
            first.click()
            page.wait_for_timeout(50)
            head = page.locator(".session .demo-name").first.text_content() or ""
            if "Requesting the board" not in head:
                failures.append(f"flow: after Start the session panel says '{head}' instead of 'Requesting the board'")
            if not first.is_disabled():
                failures.append("flow: the pressed Start button is still enabled")
            second = page.locator(".demo button.btn").nth(1)
            if not second.is_disabled():
                failures.append("flow: another demo's Start is still enabled while requesting")
            first.dblclick(force=True)
            page.wait_for_timeout(50)
            sends = page.evaluate("(window.__labDispatches || []).filter((t) => t === 'start.requested').length")
            print(f"flow: headline='{head.strip()}' start requests={sends}")
            if sends != 1:
                failures.append(f"flow: {sends} start requests were dispatched for one click and one double click, expected 1")
            failures.extend(f"flow: {e}" for e in errors)
            page.screenshot(path=str(OUT / "flow-after-start.png"), full_page=True)
            ctx.close()
        browser.close()

    for f in failures:
        print("FAIL", f)
    print("OK" if not failures else f"{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
