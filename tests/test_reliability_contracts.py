import asyncio
import tempfile

import pytest

from data.sqlite_store import SQLiteStore
from dashboard.middleware.rate_limit import expensive_route_limit_for_path
from dashboard.routes._helpers import (
    MAX_CONTENT_PLAN_CHARS,
    MAX_CONTENT_PLAN_UPLOAD_BYTES,
    read_limited_utf8_upload,
)
from dashboard.routes.generation import GenerateContentRequest
from dashboard.routes.projects import ContentPlanRequest, ProviderMappingRequest
from integrations.publishing_provider import (
    PublishErrorCode,
    PublishResult,
    PublishStatus,
)
from projects import ProjectManager
from services.secrets import ProjectSecretService


class FakeUpload:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.requested_size = None

    async def read(self, size: int = -1):
        self.requested_size = size
        return self.payload[:size] if size >= 0 else self.payload


def test_publish_result_derives_enum_status_and_error_code():
    failed = PublishResult(
        success=False,
        error="No configured publishing provider available",
        error_code=PublishErrorCode.NOT_CONFIGURED,
    )
    succeeded = PublishResult(success=True, provider="late")

    assert failed.status is PublishStatus.FAILED
    assert failed.error_code is PublishErrorCode.NOT_CONFIGURED
    assert succeeded.status is PublishStatus.SUCCEEDED


def test_secret_service_updates_provider_without_exposing_other_providers():
    with tempfile.TemporaryDirectory() as tmp:
        manager = ProjectManager(data_dir=tmp)
        project = manager.create_project("Secret Project")
        service = ProjectSecretService(manager)

        service.update_provider_config(
            project.project_id,
            "late",
            {"api_key": "late-secret", "auto_schedule": True, "ignored": "x"},
            allowed_keys={"api_key", "auto_schedule"},
        )

        assert service.get_api_key(project.project_id, "late", env_fallback=False) == "late-secret"
        assert service.get_provider_config(project.project_id, "late")["auto_schedule"] is True
        assert "ignored" not in service.get_provider_config(project.project_id, "late")
        assert service.masked_suffix("late-secret") == "cret"


def test_generate_request_bounds_and_provider_mapping_whitelist():
    assert GenerateContentRequest(count=25, platform="x").platform == "twitter"

    with pytest.raises(Exception):
        GenerateContentRequest(count=26)
    with pytest.raises(Exception):
        GenerateContentRequest(platform="unknown")
    with pytest.raises(Exception):
        ProviderMappingRequest.model_validate({"twitter": "unknown"})

    mapping = ProviderMappingRequest.model_validate({"x": "typefully", "linkedin": "late"})
    assert mapping.root == {"twitter": "typefully", "linkedin": "late"}


def test_content_plan_contract_and_upload_read_cap():
    ContentPlanRequest(content="x" * MAX_CONTENT_PLAN_CHARS)
    with pytest.raises(Exception):
        ContentPlanRequest(content="x" * (MAX_CONTENT_PLAN_CHARS + 1))

    upload = FakeUpload(b"hello")
    content = asyncio.run(
        read_limited_utf8_upload(upload, max_bytes=MAX_CONTENT_PLAN_UPLOAD_BYTES)
    )
    assert content == "hello"
    assert upload.requested_size == MAX_CONTENT_PLAN_UPLOAD_BYTES + 1

    too_large = FakeUpload(b"x" * (MAX_CONTENT_PLAN_UPLOAD_BYTES + 1))
    with pytest.raises(ValueError, match="too large"):
        asyncio.run(read_limited_utf8_upload(too_large, max_bytes=MAX_CONTENT_PLAN_UPLOAD_BYTES))


def test_throttle_limits_cover_scheduling_and_content_plan_upload():
    assert expensive_route_limit_for_path("/schedule/review_1") == (20, 60)
    assert expensive_route_limit_for_path("/api/content/review_1/schedule") == (20, 60)
    assert expensive_route_limit_for_path("/api/calendar/events/s1/reschedule") == (20, 60)
    assert expensive_route_limit_for_path("/api/projects/project-a/content-plan/upload") == (3, 300)
    assert expensive_route_limit_for_path("/api/status") is None


def test_sqlite_store_threaded_review_writes_are_safe(tmp_path):
    db_path = tmp_path / "marketing_pipeline.sqlite3"

    def save_review(index: int) -> None:
        store = SQLiteStore(data_dir=tmp_path, db_path=db_path, migrate=False)
        store.save_review_record(
            {
                "review_id": f"review-{index}",
                "project_id": "project-a",
                "post_data": {"content": f"Post {index}", "platform": "twitter"},
            }
        )

    async def run_concurrent_writes():
        await asyncio.gather(*(asyncio.to_thread(save_review, i) for i in range(30)))

    asyncio.run(run_concurrent_writes())

    store = SQLiteStore(data_dir=tmp_path, db_path=db_path, migrate=False)
    assert len(store.list_review_records(project_id="project-a")) == 30
