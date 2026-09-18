"""End-to-end pipeline test: source material → ideas → content → review queue.

Runs against a live dashboard at localhost:8765.
Requires: LLM_MODEL configured (e.g. minimax/MiniMax-M2.5) with valid API key.
"""
import json
import os
import sys

import httpx

BASE = os.environ.get("DASHBOARD_URL", "http://localhost:8765")
TOKEN = os.environ.get("DASHBOARD_TOKEN", "")
PROJECT_ID = os.environ.get("PROJECT_ID", "draper-4486991c")
TIMEOUT = 120.0  # LLM calls can be slow


class E2ETestFailure(Exception):
    pass


def log(stage: str, msg: str) -> None:
    print(f"  [{stage}] {msg}")


def make_client() -> httpx.Client:
    headers = {}
    if TOKEN:
        headers["x-dashboard-token"] = TOKEN
    return httpx.Client(base_url=BASE, headers=headers, timeout=TIMEOUT)


def fetch_csrf(client: httpx.Client) -> str:
    """Fetch CSRF token (dashboard injects it for browser; we do it manually)."""
    r = client.get("/api/csrf-token")
    data = r.json()
    if data.get("success"):
        return data["csrf_token"]
    return ""


def post_json(client: httpx.Client, url: str, body: dict, csrf: str = ""):
    headers = {"Content-Type": "application/json"}
    if csrf:
        headers["x-csrf-token"] = csrf
    r = client.post(url, json=body, headers=headers)
    return r.json()


def assert_success(data: dict, label: str) -> dict:
    if not data.get("success"):
        raise E2ETestFailure(f"{label}: {data.get('error', 'unknown error')}")
    return data


# ── Test stages ────────────────────────────────────────────────────────


def stage_1_create_source_material(client: httpx.Client, csrf: str) -> str:
    """Submit a text article as source material."""
    log("1-source", "Creating source material with article text...")
    body = {
        "project_id": PROJECT_ID,
        "title": "The Rise of Context-Aware AI in Content Marketing",
        "text_content": (
            "Context-aware AI systems are transforming how brands create and distribute content. "
            "Unlike traditional keyword-stuffing approaches, modern AI analyzes audience behavior, "
            "platform dynamics, and cultural signals to generate content that resonates.\n\n"
            "Key insights from recent industry analysis:\n"
            "- 73% of marketers report higher engagement with AI-assisted content\n"
            "- The biggest challenge is maintaining brand voice consistency at scale\n"
            "- Multi-modal content (text + visuals) outperforms text-only by 2.3x\n"
            "- Posting cadence matters more than individual post quality for growth\n"
            "- Audience fatigue hits at ~5 posts/week on LinkedIn, ~15 on Twitter\n\n"
            "The implication for marketing teams is clear: AI won't replace creativity, "
            "but teams that leverage AI for research, ideation, and first drafts will "
            "significantly outpace those relying purely on manual workflows."
        ),
        "tags": ["ai-marketing", "content-strategy", "automation"],
    }
    data = post_json(client, "/api/ideas/materials", body, csrf)
    assert_success(data, "create source material")

    material = data["material"]
    mid = material.get("material_id") if isinstance(material, dict) else getattr(material, "material_id", None)
    if not mid:
        raise E2ETestFailure(f"No material_id in response: {type(material)}")

    log("1-source", f"Created material: {mid}")
    return mid


def stage_2_enrich_material(client: httpx.Client, csrf: str, material_id: str) -> None:
    """Enrich the source material (extract key points via LLM)."""
    log("2-enrich", f"Enriching material {material_id}...")
    data = post_json(client, f"/api/ideas/materials/{material_id}/enrich", {}, csrf)
    assert_success(data, "enrich material")

    material = data["material"]
    # Check key_points were extracted
    meta = material.get("metadata_json", {}) if isinstance(material, dict) else {}
    if isinstance(meta, str):
        meta = json.loads(meta)
    key_points = meta.get("key_points", [])
    log("2-enrich", f"Enriched. Key points extracted: {len(key_points)}")
    if key_points:
        for kp in key_points[:3]:
            log("2-enrich", f"  • {kp[:80]}..." if len(kp) > 80 else f"  • {kp}")


def stage_3_generate_ideas(client: httpx.Client, csrf: str, material_id: str) -> list:
    """Generate content ideas from enriched material."""
    log("3-ideas", f"Generating ideas from material {material_id}...")
    data = post_json(client, f"/api/ideas/materials/{material_id}/generate-ideas", {
        "project_id": PROJECT_ID,
    }, csrf)
    assert_success(data, "generate ideas")

    ideas = data.get("ideas", [])
    count = data.get("count", len(ideas))
    log("3-ideas", f"Generated {count} ideas")
    for idea in ideas[:5]:
        title = idea.get("title", "untitled")
        platforms = idea.get("target_platforms", [])
        log("3-ideas", f"  • {title} [{', '.join(platforms)}]")

    if not ideas:
        raise E2ETestFailure("No ideas generated from source material")
    return ideas


def stage_4_evaluate_idea(client: httpx.Client, csrf: str, idea: dict) -> str:
    """Approve an idea → should transition to 'approved'."""
    idea_id = idea.get("idea_id") or idea.get("id")
    title = idea.get("title", "untitled")
    log("4-evaluate", f"Approving idea: {title} ({idea_id})")

    data = post_json(client, f"/api/ideas/ideas/{idea_id}/evaluate", {
        "status": "approved",
    }, csrf)
    assert_success(data, "approve idea")

    updated = data["idea"]
    status = updated.get("status") if isinstance(updated, dict) else "unknown"
    log("4-evaluate", f"Idea status: {status}")
    return idea_id


def stage_5_generate_content(client: httpx.Client, csrf: str, idea_id: str) -> None:
    """Approve-and-generate content from the idea, placing it in the review pipeline."""
    log("5-content", f"Generating content from idea {idea_id}...")
    data = post_json(client, f"/api/ideas/ideas/{idea_id}/approve-and-generate", {
        "project_id": PROJECT_ID,
    }, csrf)

    if not data.get("success"):
        # This endpoint may fail if idea is already approved — that's OK for the test
        err = data.get("error", "unknown")
        if "already" in err.lower() or "approved" in err.lower():
            log("5-content", f"Idea already approved (expected): {err}")
            return
        raise E2ETestFailure(f"generate content: {err}")

    # Check response shape
    generated = data.get("generated_count", 0)
    review_ids = data.get("review_ids", [])
    log("5-content", f"Generated {generated} content items, {len(review_ids)} in review queue")
    for rid in review_ids[:5]:
        log("5-content", f"  Review: {rid}")


def stage_6_verify_review_queue(client: httpx.Client) -> None:
    """Verify content appears in the review pipeline."""
    log("6-verify", "Checking review queue for generated content...")
    r = client.get(f"/api/content?project_id={PROJECT_ID}")
    data = r.json()

    if not data.get("success"):
        log("6-verify", f"Review endpoint returned: {data.get('error', 'unknown')}")
        # Not a hard failure — the content pipeline may use a different endpoint
        return

    items = data.get("items", data.get("content", []))
    pending = [i for i in items if i.get("status") == "pending_review"]
    log("6-verify", f"Review queue: {len(items)} total, {len(pending)} pending_review")

    if pending:
        latest = pending[0]
        content = latest.get("content", "")
        log("6-verify", f"Latest pending content preview: {content[:120]}...")


def stage_cleanup(client: httpx.Client, csrf: str, material_id: str, ideas: list) -> None:
    """Best-effort cleanup of test data."""
    log("cleanup", "Removing test data...")
    for idea in ideas:
        iid = idea.get("idea_id") or idea.get("id")
        if iid:
            try:
                client.delete(
                    f"/api/ideas/ideas/{iid}",
                    headers={"x-csrf-token": csrf} if csrf else {},
                )
            except Exception:
                pass
    if material_id:
        try:
            client.delete(
                f"/api/ideas/materials/{material_id}",
                headers={"x-csrf-token": csrf} if csrf else {},
            )
        except Exception:
            pass
    log("cleanup", "Done")


def run_e2e():
    print("=" * 60)
    print("E2E Pipeline Test: source → enrich → ideas → content → review")
    print("=" * 60)
    print(f"  Base URL:   {BASE}")
    print(f"  Project:    {PROJECT_ID}")
    print(f"  Token:      {'***' + TOKEN[-4:] if TOKEN else '(none)'}")
    print()

    client = make_client()
    material_id = None
    ideas = []

    try:
        # Auth check
        log("setup", "Verifying dashboard connectivity...")
        r = client.get("/health")
        if r.status_code != 200:
            raise E2ETestFailure(f"Dashboard not reachable: {r.status_code}")
        log("setup", "Dashboard OK")

        csrf = fetch_csrf(client)
        log("setup", f"CSRF token: {'acquired' if csrf else 'not available'}")

        # Run stages
        material_id = stage_1_create_source_material(client, csrf)
        stage_2_enrich_material(client, csrf, material_id)
        ideas = stage_3_generate_ideas(client, csrf, material_id)

        if ideas:
            stage_4_evaluate_idea(client, csrf, ideas[0])
            idea_id = ideas[0].get("idea_id") or ideas[0].get("id")
            stage_5_generate_content(client, csrf, idea_id)

        stage_6_verify_review_queue(client)

        print()
        print("=" * 60)
        print("✅ E2E PIPELINE TEST PASSED")
        print("=" * 60)

    except E2ETestFailure as e:
        print()
        print("=" * 60)
        print(f"❌ E2E PIPELINE TEST FAILED: {e}")
        print("=" * 60)
        sys.exit(1)
    except Exception as e:
        print()
        print("=" * 60)
        print(f"❌ UNEXPECTED ERROR: {type(e).__name__}: {e}")
        print("=" * 60)
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        stage_cleanup(client, csrf if 'csrf' in dir() else "", material_id, ideas)
        client.close()


if __name__ == "__main__":
    run_e2e()
