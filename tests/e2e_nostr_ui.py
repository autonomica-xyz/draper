#!/usr/bin/env python3
"""Playwright E2E for the nostr pipeline integration.

Drives a real dashboard server in a real browser through the full nostr
scheduling flow:

    login -> pipeline card -> approve w/ schedule -> "Nostr signature
    required" banner -> Sign with extension (NIP-07) -> "Signed" banner ->
    Calendar event -> Settings signing-mode display.

The fake NIP-07 extension is a faithful one: ``window.nostr.signEvent``
bridges to Python, which computes the real event id + schnorr signature with
nostr-sdk exactly like nos2x does (the extension's crypto is not under test;
the dashboard/verifier flow is).

Run directly:

    .venv/bin/python tests/e2e_nostr_ui.py

Or via pytest (auto-skips when playwright/browser is unavailable).
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

BASE_URL = None  # set by server fixture
DASHBOARD_TOKEN = None


# ----------------------------------------------------------------------
# Server management
# ----------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start_server(data_dir: str, port: int, token: str) -> subprocess.Popen:
    env = dict(os.environ)
    env.pop("NOSTR_PRIVATE_KEY", None)
    env.pop("NOSTR_PUBKEY", None)
    env["DRAPER_DASHBOARD_TOKEN"] = token
    env["DRAPER_PROJECT_ID"] = ""
    proc = subprocess.Popen(
        [
            str(PROJECT_ROOT / ".venv/bin/python"),
            "-m",
            "dashboard.unified_dashboard",
            "--run-server",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--data-dir",
            data_dir,
        ],
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return proc
        except OSError:
            if proc.poll() is not None:
                output = proc.stdout.read().decode() if proc.stdout else ""
                raise RuntimeError(f"dashboard died during startup:\n{output}")
            time.sleep(0.3)
    proc.kill()
    raise RuntimeError("dashboard did not start within 30s")


def seed_data(data_dir: str) -> dict:
    """Create a project + nostr review records before the server boots."""
    from feedback.manager import FeedbackManager
    from projects.manager import ProjectManager

    pm = ProjectManager(data_dir=data_dir)
    project = pm.create_project("E2E Nostr", description="playwright flow")
    project_id = project.project_id

    fm = FeedbackManager(data_dir=data_dir)
    scheduled = fm.add_for_review(
        {
            "content": "E2E scheduled nostr post about sign-now-publish-later #e2e",
            "platform": "nostr",
            "pillar": "growth",
            "content_type": "single_post",
            "project_id": project_id,
        },
        channel="API",
    )
    undated = fm.add_for_review(
        {
            "content": "E2E undated nostr post #cancelme",
            "platform": "nostr",
            "pillar": "growth",
            "content_type": "single_post",
            "project_id": project_id,
        },
        channel="API",
    )
    long_post = fm.add_for_review(
        {
            "content": (
                "E2E long-form nostr post line one\n"
                "line two of the long post\n"
                "line three of the long post\n"
                "line four of the long post\n"
                "line five of the long post\n"
                "line six of the long post #longform"
            ),
            "platform": "nostr",
            "pillar": "growth",
            "content_type": "single_post",
            "project_id": project_id,
        },
        channel="API",
    )
    return {
        "project_id": project_id,
        "scheduled_review_id": scheduled["review_id"],
        "undated_review_id": undated["review_id"],
        "long_review_id": long_post["review_id"],
    }


# ----------------------------------------------------------------------
# Fake NIP-07 extension (real crypto, Python-backed)
# ----------------------------------------------------------------------

FAKE_EXTENSION_JS = """
(() => {
    if (window.nostr) return;
    window.nostr = {
        getPublicKey: async () => window.__nostrGetPubkey(),
        signEvent: async (event) => JSON.parse(await window.__nostrSign(JSON.stringify(event))),
    };
})();
"""


def make_extension_signer():
    """Return (init_js, expose_bindings) implementing nos2x-equivalent signing."""
    from nostr_sdk import EventBuilder, Keys, Kind, Tag, Timestamp

    keys = Keys.generate()

    def get_pubkey() -> str:
        return keys.public_key().to_bech32()

    def sign(unsigned_json: str) -> str:
        unsigned = json.loads(unsigned_json)
        builder = EventBuilder(Kind(int(unsigned["kind"])), str(unsigned.get("content", "")))
        builder = builder.tags([Tag.parse([str(v) for v in tag]) for tag in unsigned.get("tags", [])])
        created_at = int(unsigned.get("created_at", 0))
        if created_at > 0:
            builder = builder.custom_created_at(Timestamp.from_secs(created_at))
        signed = builder.finalize(keys)
        return json.dumps(
            {
                "id": signed.id().to_hex(),
                "pubkey": signed.author().to_hex(),
                "created_at": signed.created_at().as_secs(),
                "kind": signed.kind().as_u16(),
                "tags": [tag.to_vec() for tag in signed.tags()],
                "content": signed.content(),
                "sig": signed.signature(),
            }
        )

    return FAKE_EXTENSION_JS, {"__nostrGetPubkey": get_pubkey, "__nostrSign": sign}


# ----------------------------------------------------------------------
# The E2E flow
# ----------------------------------------------------------------------


def expect(condition, message, page=None):
    if not condition:
        if page is not None:
            page.screenshot(path="/tmp/e2e_nostr_failure.png")
            print(f"FAIL: {message} (screenshot: /tmp/e2e_nostr_failure.png)")
        raise AssertionError(message)
    print(f"  ok: {message}")


def run_flow() -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context()
        page = context.new_page()

        init_js, bindings = make_extension_signer()
        page.add_init_script(init_js)
        for name, fn in bindings.items():
            page.expose_function(name, fn)

        console_errors = []
        alerts = []
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda err: console_errors.append(str(err)))
        page.on("dialog", lambda dialog: (alerts.append(f"{dialog.type}: {dialog.message}"), dialog.accept()))

        # --- login -----------------------------------------------------
        page.goto(f"{BASE_URL}/login")
        page.fill('input[name="token"]', DASHBOARD_TOKEN)
        page.click('button[type="submit"]')
        page.wait_for_url(f"{BASE_URL}/")
        expect(True, "login redirects to dashboard", page)

        project_id = os.environ["E2E_PROJECT_ID"]
        page.goto(f"{BASE_URL}/?project={project_id}")

        # --- pipeline card ---------------------------------------------
        page.wait_for_selector("#generate-content-btn")
        card = page.locator(".card.platform-nostr", has_text="E2E scheduled nostr post")
        card.wait_for(state="visible")
        expect(card.is_visible(), "nostr review card visible in Pipeline", page)
        expect("E2E scheduled nostr post" in card.inner_text(), "card shows content", page)

        # --- approve with a schedule date ------------------------------
        card.get_by_role("button", name="Approve").first.click()
        page.wait_for_selector("#feedback-dialog.open")
        page.fill("#feedback-dialog-scheduled-date", "2030-06-01T12:00")
        page.locator("#feedback-dialog-submit").click()
        page.wait_for_load_state("networkidle")

        banner = page.locator(".msg-warning", has_text="Nostr signature required")
        banner.wait_for(state="visible", timeout=10000)
        expect("publishes 2030-06-01 12:00" in banner.inner_text(), "banner shows chosen schedule", page)
        expect(page.get_by_role("button", name="Sign with extension").first.is_visible(), "sign button present", page)

        # --- sign with the (fake) extension -----------------------------
        page.get_by_role("button", name="Sign with extension").first.click()
        try:
            signed_banner = page.locator(".msg-info", has_text="Nostr: signed")
            signed_banner.wait_for(state="visible", timeout=15000)
        except Exception:
            page.screenshot(path="/tmp/e2e_nostr_failure.png")
            print(f"FAIL: signed banner never appeared\n  alerts: {alerts}\n  console: {console_errors[:5]}")
            raise
        expect("Publishes 2030-06-01 12:00" in signed_banner.inner_text(), "signed banner shows schedule", page)
        expect(signed_banner.get_by_role("button", name="Publish now").is_visible(), "publish-now button present", page)

        # --- review no longer pending ----------------------------------
        pending_cards = page.locator(".card.platform-nostr .btn-success", has_text="Approve")
        expect(pending_cards.count() == 2, "only the two pending nostr cards still have Approve", page)

        # --- approve the undated card, then cancel its request ----------
        undated_card = page.locator(".card.platform-nostr", has_text="E2E undated nostr post")
        undated_card.get_by_role("button", name="Approve").first.click()
        page.wait_for_selector("#feedback-dialog.open")
        page.locator("#feedback-dialog-submit").click()
        page.wait_for_load_state("networkidle")
        cancel_banner = page.locator(".msg-warning", has_text="Nostr signature required")
        cancel_banner.wait_for(state="visible", timeout=10000)

        cancel_banner.get_by_role("button", name="Cancel").click()
        try:
            page.wait_for_selector(
                ".msg-warning:has-text('Nostr signature required')",
                state="detached",
                timeout=10000,
            )
        except Exception:
            page.screenshot(path="/tmp/e2e_nostr_failure.png")
            print(f"FAIL: cancel did not remove banner\n  alerts: {alerts}\n  url: {page.url}")
            raise
        expect(
            page.locator(".msg-warning", has_text="Nostr signature required").count() == 0,
            "cancel removes the signature banner",
            page,
        )

        # --- collapsible content blocks (5+ lines only) -----------------
        short_block = (
            page.locator(".card.platform-nostr", has_text="E2E scheduled nostr post")
            .locator(".content-block")
            .first
        )
        long_block = (
            page.locator(".card.platform-nostr", has_text="E2E long-form nostr post")
            .locator(".content-block")
            .first
        )
        short_state = short_block.evaluate(
            "el => ({collapsible: el.classList.contains('collapsible'),"
            " max: getComputedStyle(el).maxHeight,"
            " overlay: getComputedStyle(el, '::after').content})"
        )
        long_state = long_block.evaluate(
            "el => ({collapsible: el.classList.contains('collapsible'),"
            " max: getComputedStyle(el).maxHeight,"
            " overlay: getComputedStyle(el, '::after').content})"
        )
        expect(short_state["collapsible"] is False, "short post is not collapsible", page)
        expect(short_state["max"] == "none", "short post not clamped", page)
        expect(short_state["overlay"] in ("none", "normal"), "short post has no expand overlay", page)
        expect(long_state["collapsible"] is True, "6-line post is collapsible", page)
        expect(long_state["max"] == "140px", "6-line post clamped to 140px", page)
        assert "Click to expand" in long_state["overlay"], long_state

        # click expands, click again collapses
        long_block.click()
        expanded_max = long_block.evaluate("el => getComputedStyle(el).maxHeight")
        expect(expanded_max == "none", "clicking a long post expands it", page)
        long_block.click()
        collapsed_max = long_block.evaluate("el => getComputedStyle(el).maxHeight")
        expect(collapsed_max == "140px", "clicking again collapses it", page)

        # --- calendar ---------------------------------------------------
        page.goto(f"{BASE_URL}/?project={project_id}&tab=calendar")
        page.wait_for_selector(".fc", timeout=20000)
        # The event is scheduled years out; page forward month by month.
        found_event = False
        for _ in range(60):
            if page.locator(".fc-event").count() > 0:
                found_event = True
                break
            page.locator(".fc-next-button").click()
            page.wait_for_timeout(150)
        expect(found_event, "calendar paged forward to the scheduled month", page)
        event_text = page.locator(".fc-event").first.inner_text()
        expect("Nostr (signed)" in event_text, f"calendar shows signed nostr event (got: {event_text!r})", page)

        # --- settings ---------------------------------------------------
        page.goto(f"{BASE_URL}/?project={project_id}&tab=settings")
        page.wait_for_selector("#nostr-mode-text")
        mode_text = page.locator("#nostr-mode-text").inner_text()
        expect("browser extension" in mode_text, "settings shows extension signing mode", page)
        relays_text = page.locator("#nostr-relays-text").inner_text()
        expect("relay.damus.io" in relays_text, "settings shows relay list", page)

        # --- standalone signing page still functional --------------------
        page.goto(f"{BASE_URL}/nostr/sign?project={project_id}")
        page.wait_for_selector("#requests")
        expect("Extension connected" in page.locator("#ext-banner").inner_text(), "standalone page detects extension", page)

        real_errors = [
            error
            for error in console_errors
            if "favicon" not in error and "401" not in error and "net::" not in error.lower()
        ]
        expect(not real_errors, f"no unexpected console errors (got: {real_errors[:3]})", page)

        browser.close()


def main() -> int:
    global BASE_URL, DASHBOARD_TOKEN

    with tempfile.TemporaryDirectory(prefix="draper-e2e-") as data_dir:
        seeded = seed_data(data_dir)
        print(f"seeded project: {seeded['project_id']}")

        port = _free_port()
        DASHBOARD_TOKEN = secrets.token_hex(16)
        proc = start_server(data_dir, port, DASHBOARD_TOKEN)
        BASE_URL = f"http://127.0.0.1:{port}"
        os.environ["E2E_PROJECT_ID"] = seeded["project_id"]

        try:
            run_flow()
            print("\nE2E PASS: full nostr scheduling flow works")
            return 0
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    sys.exit(main())
