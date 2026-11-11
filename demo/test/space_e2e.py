"""End-to-end check of the published demo in a real browser (headless Chromium).

Opens the Space, waits for the model to load, masks the page's own fictitious example twice
(cold, then warm) and checks:

- no personal value of the example is left in clear, apart from the detector's known
  leaks (`KNOWN_LEAKS`, reported); a value masked under another type is only noted;
- the page made requests to Hugging Face and jsDelivr only, and none of them carried the text;
- no error in the console and no content security policy violation.

It writes a screenshot and a JSON report (timings, aliases, hosts) for the workflow artifact.
The model runs in Chromium on a GitHub machine (.github/workflows/space-e2e.yml), never on a
laptop.

    python demo/test/space_e2e.py --url <page of the Space> --out e2e
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import unquote_plus, urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

ALLOWED_HOSTS = ("huggingface.co", ".huggingface.co", ".hf.co", "cdn.jsdelivr.net", ".hf.space")

# Values of the example in demo/app.js (fictitious: reserved domain, fiction phone range,
# specification IBAN, invented NIR) and the alias each must become.
EXPECTED = {
    "Jean Dupont": "[PERSON_",
    "12/03/1985": "[BIRTH_DATE_",
    "14 rue des Lilas, 69003 Lyon": "[ADDRESS_",
    "01 99 00 12 34": "[PHONE_",
    "jean.dupont@example.com": "[EMAIL_",
    "1 85 05 78 006 084 91": "[NATIONAL_ID_",
    "FR76 3000 6000 0112 3456 7890 189": "[IBAN_",
    "2024/00421": "[IDENTIFIER_",
}

# Leaks of the detector itself, the same in the Python package: they are reported, not failed on.
# None on this example since variant 3 (docs/DETECTOR.md) masks the file number after "dossier n°".
KNOWN_LEAKS: dict[str, str] = {}


def allowed(host: str) -> bool:
    return any(host == h or (h.startswith(".") and host.endswith(h)) for h in ALLOWED_HOSTS)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--load-timeout", type=int, default=900, help="seconds for the model")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    console_errors: list[str] = []
    requests: list[dict] = []
    report: dict = {"url": args.url}
    problems: list[str] = []
    text = masked = ""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1100, "height": 900})
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on(
            "request",
            lambda r: requests.append(
                {
                    "host": urlparse(r.url).hostname,
                    "method": r.method,
                    "sent": unquote_plus(r.url) + (r.post_data or ""),
                }
            ),
        )
        page.add_init_script(
            "window.__csp = []; document.addEventListener('securitypolicyviolation',"
            " e => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI));"
        )
        try:
            masked, text = run(page, args, report)
        except PlaywrightError as error:  # timeouts included: keep the screenshot and report
            problems.append(f"browser step failed: {str(error).splitlines()[0]}")
            report["status_at_failure"] = page.text_content("#status")
        report["csp_violations"] = page.evaluate("window.__csp")
        page.screenshot(path=str(args.out / "demo.png"), full_page=True)
        browser.close()

    # The example in the page must still hold the values checked here, or the check is empty.
    problems += [
        f"not in the page's example any more: {v}" for v in EXPECTED if text and v not in text
    ]
    # A value left in clear fails the check; a value masked under another type is only noted
    # (the type is the model's call, measured elsewhere).
    leaks = [value for value in EXPECTED if masked and value in masked]
    problems += [f"left in clear: {value}" for value in leaks if value not in KNOWN_LEAKS]
    report["known_leaks"] = [f"{v}: {KNOWN_LEAKS[v]}" for v in leaks if v in KNOWN_LEAKS]
    report["known_leaks_fixed"] = [v for v in KNOWN_LEAKS if masked and v not in masked]
    report["notes"] = [
        f"{value!r}: no {alias}…] alias" for value, alias in EXPECTED.items() if alias not in masked
    ]
    hosts = sorted({r["host"] for r in requests if r["host"]})
    report["hosts"] = hosts
    problems += [f"request to an unexpected host: {h}" for h in hosts if not allowed(h)]
    probe = text[:40]
    problems += [
        f"the text was sent in a {r['method']} to {r['host']}"
        for r in requests
        if probe and probe in r["sent"]
    ]
    problems += [f"CSP violation: {v}" for v in report["csp_violations"]]
    problems += [f"console error: {e}" for e in console_errors]
    report["problems"] = problems
    (args.out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("E2E OK" if not problems else "E2E FAILED")
    return 0 if not problems else 1


def run(page, args, report: dict) -> tuple[str, str]:
    """Load the page and the model, mask the example twice; returns (masked text, input text)."""
    started = time.monotonic()
    page.goto(args.url)
    page.wait_for_function(
        "() => !document.getElementById('mask').disabled || "
        "document.getElementById('status').classList.contains('warn')",
        timeout=args.load_timeout * 1000,
    )
    report["load_seconds"] = round(time.monotonic() - started, 1)
    report["status_after_load"] = page.text_content("#status")
    if page.is_disabled("#mask"):
        raise PlaywrightError(f"model did not load: {report['status_after_load']}")
    page.click("#example")
    text = page.input_value("#input")
    timings = []
    for _ in range(2):  # cold, then warm
        page.evaluate("document.getElementById('status').textContent = ''")
        page.click("#mask")
        page.wait_for_function(
            "() => document.getElementById('status').textContent.startsWith('Masked in')",
            timeout=300_000,
        )
        timings.append(page.text_content("#status"))
        page.wait_for_function("() => !document.getElementById('mask').disabled")
    report["mask_status"] = timings
    masked = page.input_value("#masked")
    report["masked"] = masked
    report["counts"] = {
        cells[0].text_content(): cells[1].text_content()
        for cells in (
            row.query_selector_all("td") for row in page.query_selector_all("#report tbody tr")
        )
    }
    return masked, text


if __name__ == "__main__":
    sys.exit(main())
