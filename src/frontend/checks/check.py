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

FIXTURES = ["connecting", "idle", "busy", "requesting", "queued", "starting", "active", "ending", "ended", "project", "fault", "offline", "reconnecting", "error", "longname", "failed"]
WIDTHS = [320, 390, 768, 1280, 1440, 1920, 2560]
OUT = Path(__file__).resolve().parent / "out"


def open_page(page: Page, url: str, errors: list[str]) -> None:
    page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type in ("error",) else None)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.goto(url, wait_until="networkidle")
    page.wait_for_timeout(1200)
    # the sections switch on as the trace reaches them: scroll through the page so a full-page capture shows everything
    height = page.evaluate("document.documentElement.scrollHeight")
    step = max(500, int(page.evaluate("innerHeight") * 0.8))
    for y in range(0, height + step, step):
        page.evaluate(f"window.scrollTo(0, {y})")
        page.wait_for_timeout(90)
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

    # the footer, as on njason.dev: a full-width band off the trace, its content aligned with the page's column
    foot = page.evaluate("""(() => { const f = document.querySelector('.foot'), i = document.querySelector('.foot-in'), m = document.querySelector('main');
      if (!f || !m) return null; return { inWrap: !!f.closest('.wrap'), pad: f.hasAttribute('data-pad'), width: f.getBoundingClientRect().width,
      vw: document.documentElement.clientWidth, inner: i && i.firstElementChild ? i.firstElementChild.getBoundingClientRect().left - m.getBoundingClientRect().left : null } })()""")
    if foot is None:
        failures.append(f"{name}@{width}: no footer")
    else:
        if foot["inWrap"] or foot["pad"]:
            failures.append(f"{name}@{width}: the footer is on the trace (inside .wrap: {foot['inWrap']}, data-pad: {foot['pad']})")
        if abs(foot["width"] - foot["vw"]) > 1:
            failures.append(f"{name}@{width}: the footer is {foot['width']:.0f}px wide, not the full {foot['vw']}px")
        if foot["inner"] is None or abs(foot["inner"]) > 1:
            failures.append(f"{name}@{width}: the footer's content is {foot['inner']}px off the content edge")
    # the hero leads with the board until the visitor starts something, then with their session (or its stage)
    lead = {"idle": "board", "busy": "board", "project": "board", "fault": "board", "offline": "board", "connecting": "board",
            "error": "board", "longname": "board", "requesting": "session", "arrival": "session", "queued": "session",
            "starting": "session", "ending": "session", "ended": "session", "failed": "session", "active": "stage", "reconnecting": "stage"}.get(name)
    if lead:
        hero = page.evaluate("""(() => { const h = document.querySelector('.hero'); if (!h) return null; const pads = [...h.querySelectorAll('[data-pad]')];
          const first = h.firstElementChild; return { first: first ? first.className.split(' ')[0] : null, pads: pads.length, padInFirst: pads.length === 1 && first.contains(pads[0]) } })()""")
        if not hero or hero["first"] != lead:
            failures.append(f"{name}@{width}: the hero leads with {hero and hero['first']}, expected {lead}")
        elif hero["pads"] != 1 or not hero["padInFirst"]:
            failures.append(f"{name}@{width}: the hero has {hero['pads']} trace pad(s), expected one on its first element")
    # at the bottom of the page the whole trace is drawn
    page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
    page.wait_for_timeout(1500)
    dark = page.evaluate("[...document.querySelectorAll('.t-pad')].filter((p) => !p.classList.contains('on')).length")
    if dark:
        failures.append(f"{name}@{width}: {dark} pad(s) still dark at the bottom of the page")
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(300)
    # thumbnails run the full width of their card
    small = page.evaluate("[...document.querySelectorAll('.demo')].filter((r) => { const t = r.querySelector('.thumb'); return t && t.offsetWidth < 0.9 * r.clientWidth }).length")
    if small:
        failures.append(f"{name}@{width}: {small} thumbnail(s) narrower than their card")
    # cards side by side line up: the button line starts at the same height in every card of a row
    ragged = page.evaluate("""(() => { const rows = {}; for (const c of document.querySelectorAll('.demo')) {
      const b = c.querySelector('.btn'); if (!b) continue; const top = Math.round(c.getBoundingClientRect().top);
      (rows[top] ||= []).push(Math.round(b.getBoundingClientRect().top)); }
      return Object.values(rows).filter((r) => Math.max(...r) - Math.min(...r) > 1).length })()""")
    if ragged:
        failures.append(f"{name}@{width}: {ragged} row(s) of cards with buttons at different heights")
    notes = page.evaluate("document.querySelectorAll('.demo small').length")
    if notes:
        failures.append(f"{name}@{width}: {notes} note(s) under demo buttons")
    # a live interactive demo gets most of a phone's screen
    if width <= 768:
        tall = page.evaluate("(() => { const s = document.querySelector('.stage[data-kind=interactive] iframe'); return s ? s.getBoundingClientRect().height / innerHeight : null })()")
        if name in ("active", "reconnecting") and (tall is None or tall < 0.6):
            failures.append(f"{name}@{width}: the interactive demo frame is {tall if tall is None else round(tall * 100)}% of the screen height (need 60%)")
    # no line of body text past 80 characters
    long = page.evaluate(
        """(() => { const out = []; for (const p of document.querySelectorAll('main p')) {
          if (!p.offsetParent) continue; const s = document.createElement('span'); s.textContent = '0'; s.style.visibility = 'hidden'; p.appendChild(s);
          const ch = s.getBoundingClientRect().width; s.remove(); const n = p.clientWidth / ch; if (n > 80) out.push(Math.round(n)); } return out })()"""
    )
    if long:
        failures.append(f"{name}@{width}: paragraph measure {long} ch (max 80)")


def attention_flow(browser, base: str, width: int, failures: list[str]) -> None:
    """Start from the bottom of the page: the session panel comes into view, takes focus, shows the steps and names the tab."""
    ctx = browser.new_context(viewport={"width": width, "height": 900})
    page = ctx.new_page()
    errors: list[str] = []
    open_page(page, f"{base}/?mock=idle", errors)
    page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
    page.wait_for_timeout(400)
    page.locator(".demo button.btn").last.click()
    page.wait_for_timeout(900)
    tag = f"attention@{width}"
    top, bottom, vh = page.evaluate("(() => { const r = document.querySelector('.session').getBoundingClientRect(); return [r.top, r.bottom, innerHeight] })()")
    if not (0 <= top < vh):
        failures.append(f"{tag}: the session panel's top is at {top:.0f}px after Start, outside the viewport")
    if not page.evaluate("document.activeElement && document.activeElement.matches('.session h2')"):
        failures.append(f"{tag}: focus is not on the session heading")
    states = page.evaluate("[...document.querySelectorAll('.session .steps li')].map((li) => li.dataset.state)")
    if len(states) != 3 or states[0] != "current":
        failures.append(f"{tag}: steps are {states}, expected three with the first current")
    title = page.evaluate("document.title")
    if title != "Programming the board":
        failures.append(f"{tag}: tab title is '{title}'")
    failures.extend(f"{tag}: {e}" for e in errors)
    page.screenshot(path=str(OUT / f"attention-{width}.png"), full_page=False)
    ctx.close()


def _lum(rgb: str) -> float:
    parts = [float(x) for x in rgb[rgb.index("(") + 1:rgb.index(")")].split(",")[:3]]
    lin = [(c / 255 / 12.92) if c / 255 <= 0.03928 else (((c / 255) + 0.055) / 1.055) ** 2.4 for c in parts]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(fg: str, bg: str) -> float:
    a, b = _lum(fg), _lum(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


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
            # reduced motion: everything visible at once, trace fully drawn, no pulse
            ctx = browser.new_context(viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
            page = ctx.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            page.goto(f"{args.base}/?mock=idle", wait_until="networkidle")
            page.wait_for_timeout(1500)
            hidden = page.evaluate("[...document.querySelectorAll('.sec > :not(h2)')].filter((el) => getComputedStyle(el).opacity !== '1').length")
            if hidden:
                failures.append(f"reduced motion: {hidden} section children are not fully visible")
            pads = page.evaluate("[...document.querySelectorAll('.t-pad')].filter((p) => !p.classList.contains('on')).length")
            if pads:
                failures.append(f"reduced motion: {pads} pads are not lit")
            pulse = page.evaluate("getComputedStyle(document.querySelector('.t-pulse')).opacity")
            if pulse != "0":
                failures.append(f"reduced motion: the pulse is visible (opacity {pulse})")
            failures.extend(f"reduced motion: {e}" for e in errors)
            page.screenshot(path=str(OUT / "idle-1440-reduced-motion.png"), full_page=True)
            ctx.close()

            # contrast: a sample of the text styles on their real backgrounds, WCAG AA 4.5:1
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            page = ctx.new_page()
            page.goto(f"{args.base}/?mock=idle", wait_until="networkidle")
            page.wait_for_timeout(800)
            samples = page.evaluate(
                """() => {
                  const sel = ['.ro small', '.sec > .lead', '.tag', '.btn.live', '.ro.tone-cyan b', '.rec small', '.boardpill span', '.session .sub', '.demo p', '.topbar nav a', '.when'];
                  const bg = (el) => { for (let e = el; e; e = e.parentElement) { const c = getComputedStyle(e).backgroundColor; if (c && c !== 'rgba(0, 0, 0, 0)' && c !== 'transparent') return c; } return 'rgb(11, 29, 33)'; };
                  return sel.map((s) => { const el = document.querySelector(s); return el ? [s, getComputedStyle(el).color, bg(el)] : null; }).filter(Boolean);
                }"""
            )
            for selector, fg, bgc in samples:
                ratio = contrast(fg, bgc)
                print(f"contrast {selector}: {ratio:.2f} ({fg} on {bgc})")
                if ratio < 4.5:
                    failures.append(f"contrast: {selector} is {ratio:.2f}:1 ({fg} on {bgc}), below 4.5")
            ctx.close()

            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            page = ctx.new_page()
            errors = []
            open_page(page, f"{args.base}/?mock=idle", errors)
            first = page.locator(".demo button.btn").first
            first.click()
            page.wait_for_timeout(50)
            head = page.locator(".session .steps li[data-state='current']").first.text_content() if page.locator(".session .steps li[data-state='current']").count() else ""
            if "Requested" not in head:
                failures.append(f"flow: after Start the current step is '{head}' instead of 'Requested'")
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

            for width in (1440, 390):
                attention_flow(browser, args.base, width, failures)
            # the panel was already in view: no scroll at all, focus still lands on it
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            page = ctx.new_page()
            open_page(page, f"{args.base}/?mock=idle", [])
            page.evaluate("document.querySelector('.demo button.btn').click()")  # a real click would scroll the button into view first
            page.wait_for_timeout(900)
            if page.evaluate("scrollY") != 0:
                failures.append(f"attention@1440: the page scrolled to {page.evaluate('scrollY')} although the panel was in view")
            if not page.evaluate("document.activeElement && document.activeElement.matches('.session h2')"):
                failures.append("attention@1440: focus is not on the session heading when no scroll was needed")
            ctx.close()

        if not args.no_mock and "active" in fixtures:
            # the stage opens under the progress card, which reaches Live and gets out of the way once the demo loads
            for width in (1440, 390):
                ctx = browser.new_context(viewport={"width": width, "height": 900})
                page = ctx.new_page()
                page.goto(f"{args.base}/?mock=active", wait_until="domcontentloaded")
                seen = False
                for _ in range(40):
                    if page.evaluate("!!document.querySelector('.stage .cover')"):
                        seen = True
                        break
                    page.wait_for_timeout(50)
                page.wait_for_timeout(2000)
                left = page.evaluate("!!document.querySelector('.stage .cover')")
                if not seen:
                    failures.append(f"cover@{width}: the stage opened without its progress cover")
                if left:
                    failures.append(f"cover@{width}: the cover is still over the demo 2 s after it loaded")
                ctx.close()

        if not args.no_mock and "failed" in fixtures:
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            page = ctx.new_page()
            open_page(page, f"{args.base}/?mock=failed", [])
            if not page.locator(".session .steps li[data-state='failed']").count():
                failures.append("failed: no failed step in the track")
            if not page.locator(".session button", has_text="Try again").count():
                failures.append("failed: no Try again button")
            ctx.close()
        browser.close()

    for f in failures:
        print("FAIL", f)
    print("OK" if not failures else f"{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
