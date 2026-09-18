"""Route contract tests for dashboard/routes/nostr.py (NIP-07 signing flow)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

nostr_sdk = pytest.importorskip("nostr_sdk")

from nostr_sdk import Keys  # noqa: E402

from nostr import signing as nostr_signing  # noqa: E402


@pytest.fixture
def container(project_data_dir: Any, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("DRAPER_DASHBOARD_TOKEN", raising=False)
    monkeypatch.delenv("NOSTR_PRIVATE_KEY", raising=False)
    monkeypatch.setenv("DRAPER_ALLOW_UNAUTHENTICATED_LOCAL", "1")
    from dashboard.app_container import AppContainer

    return AppContainer(data_dir=str(project_data_dir))


@pytest.fixture
def app(container):
    from dashboard.app_factory import build_app

    return build_app(container)


@pytest.fixture
def client(app, container):
    test_client = TestClient(app, raise_server_exceptions=False)
    test_client.headers.update({"x-csrf-token": container.csrf.current_token()})
    return test_client


EXPECTED_NOSTR_PATHS = {
    "/nostr/sign",
    "/api/projects/{project_id}/nostr/status",
    "/api/projects/{project_id}/nostr/signing-requests",
    "/api/projects/{project_id}/nostr/signing-requests/{request_id}/signed",
    "/api/projects/{project_id}/nostr/signing-requests/{request_id}/cancel",
    "/api/projects/{project_id}/nostr/publish-due",
}


@pytest.fixture
def review_with_project(container, fixture_project):
    """A pending nostr review record in the fixture project."""
    post_data = {
        "content": "Route test note #fixture",
        "platform": "nostr",
        "pillar": "educational",
        "project_id": fixture_project["project_id"],
    }
    record = container.feedback_manager.add_for_review(post_data, channel="API")
    return record["review_id"], fixture_project["project_id"]


class TestRouteRegistration:
    def test_router_registers_every_nostr_path(self):
        from dashboard.routes import nostr

        assert isinstance(nostr.router, APIRouter)
        paths = {route.path for route in nostr.router.routes}
        missing = EXPECTED_NOSTR_PATHS - paths
        assert not missing, f"Missing paths in nostr.router: {sorted(missing)}"


class TestSigningFlow:
    def test_signing_page_renders(self, client, review_with_project, fixture_project):
        response = client.get("/nostr/sign", params={"project": fixture_project["project_id"]})
        assert response.status_code == 200
        assert "window.nostr" in response.text  # NIP-07 usage documented in page
        assert "Nostr Signing" in response.text

    def test_status_reports_extension_mode(self, client, fixture_project):
        response = client.get(f"/api/projects/{fixture_project['project_id']}/nostr/status")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["server_key_configured"] is False
        assert data["relays"]

    def test_create_list_and_accept_signature(self, client, container, review_with_project):
        review_id, project_id = review_with_project

        created = client.post(
            f"/api/projects/{project_id}/nostr/signing-requests",
            json={"review_id": review_id},
        )
        assert created.status_code == 200
        request_record = created.json()["request"]
        assert request_record["status"] == "pending_signature"
        assert request_record["unsigned_events"][0]["content"] == "Route test note #fixture"

        listed = client.get(f"/api/projects/{project_id}/nostr/signing-requests").json()
        assert any(r["request_id"] == request_record["request_id"] for r in listed["requests"])

        # "Extension" signs exactly like window.nostr.signEvent would.
        keys = Keys.generate()
        signed_events = nostr_signing.sign_event_chain(request_record["unsigned_events"], keys)
        accepted = client.post(
            f"/api/projects/{project_id}/nostr/signing-requests/"
            f"{request_record['request_id']}/signed",
            json={"events": signed_events},
        )
        assert accepted.status_code == 200
        assert accepted.json()["request"]["status"] == "signed"

        # Review record is mirrored to scheduled.
        review = container.feedback_manager._load_review_record(review_id)
        assert review["status"] == "scheduled"

    def test_accept_rejects_tampered_signature(self, client, review_with_project):
        review_id, project_id = review_with_project
        request_record = client.post(
            f"/api/projects/{project_id}/nostr/signing-requests",
            json={"review_id": review_id},
        ).json()["request"]

        keys = Keys.generate()
        signed_events = nostr_signing.sign_event_chain(request_record["unsigned_events"], keys)
        signed_events[0] = {**signed_events[0], "content": "swapped"}

        response = client.post(
            f"/api/projects/{project_id}/nostr/signing-requests/"
            f"{request_record['request_id']}/signed",
            json={"events": signed_events},
        )
        assert response.status_code == 400
        assert "rejected" in response.json()["error"]

    def test_create_requires_review_id(self, client, fixture_project):
        response = client.post(
            f"/api/projects/{fixture_project['project_id']}/nostr/signing-requests",
            json={},
        )
        assert response.status_code == 400

    def test_cancel_request(self, client, review_with_project):
        review_id, project_id = review_with_project
        request_record = client.post(
            f"/api/projects/{project_id}/nostr/signing-requests",
            json={"review_id": review_id},
        ).json()["request"]

        response = client.post(
            f"/api/projects/{project_id}/nostr/signing-requests/"
            f"{request_record['request_id']}/cancel"
        )
        assert response.status_code == 200
        assert response.json()["request"]["status"] == "cancelled"


class TestPipelineIntegration:
    def test_signature_waiting_review_stays_in_pipeline(
        self, client, container, review_with_project, fixture_project
    ):
        """Approved nostr review + pending request must stay visible in the Pipeline."""
        review_id, project_id = review_with_project
        request_record = client.post(
            f"/api/projects/{project_id}/nostr/signing-requests",
            json={"review_id": review_id, "scheduled_at": "2030-06-01T10:00:00Z"},
        ).json()["request"]

        # Approve the review so it leaves get_pending_reviews().
        container.feedback_manager.approve(review_id, "ok")

        response = client.get("/", params={"project": project_id, "tab": "pipeline"})
        assert response.status_code == 200
        html = response.text
        assert "Nostr signature required" in html
        assert f"signNostrReview('{review_id}'" in html
        assert request_record["request_id"] in html

    def test_pending_review_shows_no_banner_without_request(
        self, client, review_with_project, fixture_project
    ):
        review_id, project_id = review_with_project
        response = client.get("/", params={"project": project_id})
        assert "Nostr signature required" not in response.text

    def test_calendar_includes_nostr_requests(self, client, review_with_project, fixture_project):
        review_id, project_id = review_with_project
        request_record = client.post(
            f"/api/projects/{project_id}/nostr/signing-requests",
            json={"review_id": review_id, "scheduled_at": "2030-06-01T10:00:00Z"},
        ).json()["request"]

        response = client.get(
            "/api/calendar/events",
            params={"start": "2030-01-01", "end": "2031-01-01", "project": project_id},
        )
        assert response.status_code == 200
        events = response.json()["events"]
        nostr_events = [e for e in events if e["extendedProps"]["source"] == "nostr"]
        assert len(nostr_events) == 1
        assert nostr_events[0]["extendedProps"]["status"] == "pending_signature"
        assert nostr_events[0]["extendedProps"]["request_id"] == request_record["request_id"]
        assert nostr_events[0]["start"].startswith("2030-06-01")

    def test_list_filters_by_review_id(self, client, review_with_project, fixture_project):
        review_id, project_id = review_with_project
        client.post(
            f"/api/projects/{project_id}/nostr/signing-requests",
            json={"review_id": review_id},
        )
        listed = client.get(
            f"/api/projects/{project_id}/nostr/signing-requests",
            params={"review_id": review_id},
        ).json()["requests"]
        assert len(listed) == 1
        assert listed[0]["review_id"] == review_id

        other = client.get(
            f"/api/projects/{project_id}/nostr/signing-requests",
            params={"review_id": "does-not-exist"},
        ).json()["requests"]
        assert other == []


class TestApproveCreatesSigningRequest:
    def test_approving_nostr_content_creates_linked_request(
        self, client, container, review_with_project, fixture_project
    ):
        """The dashboard approve path must reach the nostr provider and leave
        a signing request linked to the review + project (regression: the
        request used to be orphaned, so the Pipeline never showed it)."""
        review_id, project_id = review_with_project
        csrf = container.csrf.current_token()

        response = client.post(
            f"/approve/{review_id}?project={project_id}",
            data={
                "feedback": "",
                "tags": "",
                "channel": "nostr",
                "scheduled_date": "2030-06-01T12:00",
                "csrf_token": csrf,
            },
        )
        assert response.status_code == 200

        review = container.feedback_manager._load_review_record(review_id)
        # Schedule-failure visibility: SIGNING_REQUIRED resets the review to
        # pending_review (with scheduling_error) so it stays visible in the
        # Pipeline tab until the extension signature arrives.
        assert review["status"] == "pending_review"
        assert "Nostr signature required" in (review.get("scheduling_error") or "")
        assert "Pipeline tab" in (review.get("scheduling_error") or "")

        requests = container.store.list_nostr_request_records(project_id=project_id)
        assert len(requests) == 1
        record = requests[0]
        assert record["review_id"] == review_id
        assert record["project_id"] == project_id
        assert record["status"] == "pending_signature"
        assert record["scheduled_at"] is not None
        assert record["scheduled_at"].startswith("2030-06-01")
