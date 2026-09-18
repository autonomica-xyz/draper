"""Plan 04-04 Task 1: RetryPolicy + FailureCategory contracts (ARCH-05 D-5)."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from services.retry_policy import (
    FailureCategory,
    RetryDecision,
    RetryPolicy,
    categorize_exception,
)


class TestRetryPolicyTransient:
    def test_transient_attempts_1_returns_decision_max_4(self):
        decision = RetryPolicy().compute_retry(FailureCategory.TRANSIENT, attempts=1)
        assert decision is not None
        assert isinstance(decision, RetryDecision)
        assert decision.max_attempts == 4

    def test_transient_attempts_4_returns_none(self):
        decision = RetryPolicy().compute_retry(FailureCategory.TRANSIENT, attempts=4)
        assert decision is None

    def test_transient_attempts_1_next_retry_within_5_to_7_seconds(self):
        now = datetime(2026, 7, 5, 12, 0, 0)
        decision = RetryPolicy().compute_retry(FailureCategory.TRANSIENT, attempts=1, now=now)
        assert decision is not None
        next_dt = datetime.fromisoformat(decision.next_retry_at)
        delta = next_dt - now
        assert timedelta(seconds=5) <= delta <= timedelta(seconds=7)


class TestRetryPolicyPermanent:
    def test_permanent_attempts_1_returns_none(self):
        decision = RetryPolicy().compute_retry(FailureCategory.PERMANENT, attempts=1)
        assert decision is None


class TestRetryPolicyProviderQuota:
    def test_provider_quota_attempts_1_returns_decision_max_3(self):
        decision = RetryPolicy().compute_retry(FailureCategory.PROVIDER_QUOTA, attempts=1)
        assert decision is not None
        assert decision.max_attempts == 3

    def test_provider_quota_attempts_3_returns_none(self):
        decision = RetryPolicy().compute_retry(FailureCategory.PROVIDER_QUOTA, attempts=3)
        assert decision is None

    def test_provider_quota_attempts_1_next_retry_within_60_to_62_seconds(self):
        now = datetime(2026, 7, 5, 12, 0, 0)
        decision = RetryPolicy().compute_retry(
            FailureCategory.PROVIDER_QUOTA, attempts=1, now=now
        )
        assert decision is not None
        next_dt = datetime.fromisoformat(decision.next_retry_at)
        delta = next_dt - now
        assert timedelta(seconds=60) <= delta <= timedelta(seconds=62)


class TestRetryPolicyUnknown:
    def test_unknown_attempts_1_returns_decision_max_2(self):
        decision = RetryPolicy().compute_retry(FailureCategory.UNKNOWN, attempts=1)
        assert decision is not None
        assert decision.max_attempts == 2

    def test_unknown_attempts_2_returns_none(self):
        decision = RetryPolicy().compute_retry(FailureCategory.UNKNOWN, attempts=2)
        assert decision is None


class TestRetryPolicyJitterBounded:
    def test_transient_attempts_1_jitter_is_bounded_within_2s_window(self):
        now = datetime(2026, 7, 5, 12, 0, 0)
        deltas = []
        for _ in range(100):
            decision = RetryPolicy().compute_retry(
                FailureCategory.TRANSIENT, attempts=1, now=now
            )
            assert decision is not None
            next_dt = datetime.fromisoformat(decision.next_retry_at)
            delta = (next_dt - now).total_seconds()
            deltas.append(delta)
        assert all(5.0 <= d <= 7.0 for d in deltas), (
            f"jitter exceeded bounded window: min={min(deltas)}, max={max(deltas)}"
        )


class TestCategorizeException:
    def test_connect_error_is_transient(self):
        class FakeConnectError(Exception):
            pass

        assert (
            categorize_exception(FakeConnectError("no connection"))
            == FailureCategory.TRANSIENT
        )

    def test_value_error_is_permanent(self):
        assert (
            categorize_exception(ValueError("invalid payload"))
            == FailureCategory.PERMANENT
        )

    def test_rate_limit_message_is_provider_quota(self):
        assert (
            categorize_exception(Exception("rate limit exceeded"))
            == FailureCategory.PROVIDER_QUOTA
        )

    def test_unknown_runtime_error_is_unknown(self):
        assert categorize_exception(RuntimeError("unknown")) == FailureCategory.UNKNOWN


class TestSchemaMigration:
    def test_failure_category_defaults_to_none_after_construction(self, tmp_path: Path):
        from data.sqlite_store import SQLiteStore

        store = SQLiteStore(data_dir=str(tmp_path))
        record = store.enqueue_job(
            "sync_analytics",
            payload={"project_id": "p1"},
            project_id="p1",
        )
        loaded = store.get_job_record(record["job_id"])
        assert loaded is not None
        assert loaded.get("failure_category") is None

    def test_migration_is_idempotent_when_reconstructing_store(self, tmp_path: Path):
        from data.sqlite_store import SQLiteStore

        store1 = SQLiteStore(data_dir=str(tmp_path))
        store1.enqueue_job(
            "sync_analytics",
            payload={"project_id": "p1"},
            project_id="p1",
        )

        pragma_before = _pragma_failure_category_count(store1)
        assert pragma_before == 1

        store2 = SQLiteStore(data_dir=str(tmp_path))
        pragma_after = _pragma_failure_category_count(store2)
        assert pragma_after == 1


def _pragma_failure_category_count(store) -> int:
    with store.connect() as conn:
        rows = conn.execute("PRAGMA table_info(jobs)").fetchall()
    return sum(1 for row in rows if row["name"] == "failure_category")
