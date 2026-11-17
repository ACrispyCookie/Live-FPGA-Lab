"""Run one real session on the deployed lab and record what the visitor sees at every step.

    .venv-checks/bin/python src/frontend/checks/real_flow.py [--base https://fpga.njason.dev] [--demo gpgpu-nbody] [--chrome /usr/bin/google-chrome-stable]

Needs the board free and in demo mode. Presses Start on the chosen demo, logs each change of the session
headline with a timestamp and a screenshot (src/frontend/checks/out/real-<n>-<phase>.png), waits for the
stage, leaves the demo running for a few seconds, presses End session, and checks the ended sentence and
the recent list. Exit code 1 when the stage never arrives or the end is not reported.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent / "out"
HEADLINE = ".session .now, .session .big, .session .demo-name, .sbar .who"


def headline(page) -> str:
    return (page.evaluate(f"(document.querySelector('{HEADLINE}') || {{}}).textContent || ''") or "").strip()


def lead(page) -> str:
    return page.evaluate("((document.querySelector('.hero') || {}).firstElementChild || {}).className || ''").split(" ")[0]


def step(page) -> str:
    return (page.evaluate("(document.querySelector('.session .steps li[data-state=current], .session .steps li[data-state=failed]') || {}).textContent || ''") or "").strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="https://fpga.njason.dev")
    ap.add_argument("--demo", default="gpgpu-nbody")
    ap.add_argument("--chrome", default="")
    ap.add_argument("--run-seconds", type=int, default=12)
    ap.add_argument("--stage-timeout", type=int, default=150)
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=900)
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    failures: list[str] = []
    t0 = time.monotonic()
    shots = 0

    def log(event: str, page=None) -> None:
        nonlocal shots
        print(f"[{time.monotonic() - t0:6.1f}s] {event}")
        if page is not None:
            shots += 1
            page.screenshot(path=str(OUT / f"real-{shots:02d}-{event.split(':')[0].replace(' ', '-')}.png"), full_page=False)

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=args.chrome or None)
        mobile = args.width < 800
        ctx = browser.new_context(viewport={"width": args.width, "height": args.height}, is_mobile=mobile, has_touch=mobile)
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{args.base}/", wait_until="networkidle")
        page.wait_for_timeout(1500)
        log(f"loaded: headline='{headline(page)}' pill='{page.locator('.boardpill').text_content()}'", page)
        if "free" not in headline(page):
            print("The board is not free; aborting without starting anything.")
            browser.close()
            return 1

        row = page.locator(f".demo[data-demo='{args.demo}']")
        row.locator("button.btn").click()
        page.wait_for_timeout(60)
        log(f"clicked Start: headline='{headline(page)}' step='{step(page)}' title='{page.title()}' button='{row.locator('button.btn').text_content()}'", page)
        page.wait_for_timeout(1940)
        if page.title() != "Programming the board" and not page.locator(".stage").count():
            failures.append(f"the tab title is '{page.title()}' 2 s after Start, expected 'Programming the board'")

        last = headline(page)
        staged = False
        deadline = time.monotonic() + args.stage_timeout
        while time.monotonic() < deadline:
            page.wait_for_timeout(400)
            h = headline(page)
            if h != last:
                log(f"changed: lead={lead(page)} headline='{h}' step='{step(page)}' title='{page.title()}' pill='{page.locator('.boardpill').text_content()}'", page)
                last = h
            if page.locator(".stage").count():
                staged = True
                # the cover shows Live current while the page loads, or the finished track (Live done) during its hold
                cover = page.evaluate("(() => { const c = document.querySelector('.stage .cover'); if (!c) return null; return [...c.querySelectorAll('.steps li')].map((li) => li.textContent + ':' + li.dataset.state).join(', ') })()")
                log(f"stage opened: lead={lead(page)} cover={cover!r}", page)
                if not cover or not ("Live:current" in cover or "Live:done" in cover):
                    failures.append(f"the stage opened without its cover at Live (got {cover!r})")
                for _ in range(100):
                    if not page.locator(".stage .cover").count():
                        break
                    page.wait_for_timeout(200)
                else:
                    failures.append("the cover was still over the demo 20 s after the stage opened")
                log(f"cover gone: lead={lead(page)}", page)
                break
        if not staged:
            failures.append(f"the stage did not appear within {args.stage_timeout}s; last headline '{last}'")
        else:
            page.wait_for_timeout(args.run_seconds * 1000)
            frame_url = page.evaluate("(document.querySelector('.stage iframe') || {}).src || ''")
            loading = page.locator(".stage .cover").count()
            log(f"stage: iframe='{frame_url}' cover={loading} bar='{page.locator('.sbar').text_content()}'", page)
            page.locator(".sbar button", has_text="End session").click()
            page.wait_for_timeout(80)
            log(f"clicked End: headline='{headline(page)}'", page)
            ended = False
            deadline = time.monotonic() + 60
            last = headline(page)
            while time.monotonic() < deadline:
                page.wait_for_timeout(400)
                h = headline(page)
                if h != last:
                    log(f"changed: lead={lead(page)} headline='{h}' step='{step(page)}' title='{page.title()}' pill='{page.locator('.boardpill').text_content()}'", page)
                    last = h
                if page.locator(".session .big", has_text="Ended").count():
                    ended = True
                    break
            if not ended:
                failures.append(f"the session never reported as ended; last headline '{last}'")
            else:
                sentence = page.locator(".session .sub").first.text_content()
                recent = page.locator(".rec").first.text_content()
                log(f"ended: sentence='{sentence}' recent='{recent}' title='{page.title()}'", page)
                if page.title() != "Live FPGA Lab":
                    failures.append(f"the tab title stayed '{page.title()}' after the session ended")
        failures.extend(f"page error: {e}" for e in errors)
        browser.close()

    for f in failures:
        print("FAIL", f)
    print("OK" if not failures else f"{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
