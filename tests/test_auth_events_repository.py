"""
Test script for src/data/auth_events_repository.py.

Tests, using a real temp directory as the local data root (no network calls):
1. Malformed / missing-field JSON files are skipped without breaking the rest
2. Valid events are parsed into the expected DataFrame shape
3. get_login_counts_by_user_and_status() aggregates correctly
4. An empty (but present) local events directory returns an empty DataFrame
5. No local events AND no reachable S3 backfill raises AuthEventsUnavailableError
6. record_local_event() writes the file and keeps the consolidated Parquet in sync
7. record_local_event() on a brand new environment recovers S3-only history
   before adding the new event, instead of silently dropping it
"""

import json
import sys
import tempfile
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import src.data.auth_events_repository as auth_events_repository
from src.data.auth_events_repository import (
    AuthEventsUnavailableError,
    get_login_counts_by_user_and_status,
    record_local_event,
)


def _write_event_file(base_dir: Path, relative_key: str, payload) -> None:
    path = auth_events_repository.local_event_path(relative_key, base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, (dict, list)):
        path.write_text(json.dumps(payload), encoding="utf-8")
    else:
        path.write_text(payload, encoding="utf-8")


def test_malformed_events_are_skipped():
    print("=" * 80)
    print("TEST 1: Malformed events are skipped without breaking the rest")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        valid_event = {
            "event_id": "evt-1", "username": "cda_user",
            "timestamp": "2026-08-04T10:00:00.000Z", "deploy_status": "production",
        }
        _write_event_file(base_dir, "year=2026/month=08/day=04/valid.json", valid_event)
        _write_event_file(base_dir, "year=2026/month=08/day=04/not_json.json", "{not valid json")
        _write_event_file(base_dir, "year=2026/month=08/day=04/missing_fields.json", {"event_id": "evt-2", "username": "cda_user"})
        _write_event_file(base_dir, "year=2026/month=08/day=04/not_an_object.json", [1, 2, 3])

        df = auth_events_repository.list_login_events(use_cache=False, base_dir=base_dir)

        assert len(df) == 1, f"Expected 1 valid event, got {len(df)}"
        assert df.iloc[0]["event_id"] == "evt-1"

    print("✅ Kept 1 valid event out of 4 files, skipped 3 malformed")
    return True


def test_empty_events_dir_returns_correct_columns():
    print("\n" + "=" * 80)
    print("TEST 2: Confirmed-empty local state (Parquet already built) -> empty DataFrame with expected columns")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        auth_events_repository._local_events_dir(base_dir).mkdir(parents=True, exist_ok=True)
        # Establishes the "already confirmed, genuinely zero events" marker (the
        # Parquet file itself) - without it, an empty JSON dir alone looks the
        # same as "never checked yet" and would trigger an S3 backfill attempt.
        auth_events_repository._rebuild_consolidated_parquet(base_dir)

        df = auth_events_repository.list_login_events(use_cache=False, base_dir=base_dir)

        assert df.empty
        assert list(df.columns) == ["event_id", "username", "timestamp", "deploy_status", "client_id"]

        counts = get_login_counts_by_user_and_status(df)
        assert counts.empty
        assert list(counts.columns) == ["username", "deploy_status", "count"]

    print("✅ Empty event set produces empty DataFrames with correct columns")
    return True


def test_aggregation_counts_by_user_and_status():
    print("\n" + "=" * 80)
    print("TEST 3: Aggregation counts by username + deploy_status")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        events = [
            {"event_id": "1", "username": "cda_user", "timestamp": "t1", "deploy_status": "production"},
            {"event_id": "2", "username": "cda_user", "timestamp": "t2", "deploy_status": "production"},
            {"event_id": "3", "username": "cda_user", "timestamp": "t3", "deploy_status": "staging"},
            {"event_id": "4", "username": "admin", "timestamp": "t4", "deploy_status": "production"},
        ]
        for e in events:
            _write_event_file(base_dir, f"{e['event_id']}.json", e)

        df = auth_events_repository.list_login_events(use_cache=False, base_dir=base_dir)
        counts = get_login_counts_by_user_and_status(df)

        cda_prod = counts[(counts.username == "cda_user") & (counts.deploy_status == "production")]["count"].iloc[0]
        cda_staging = counts[(counts.username == "cda_user") & (counts.deploy_status == "staging")]["count"].iloc[0]
        admin_prod = counts[(counts.username == "admin") & (counts.deploy_status == "production")]["count"].iloc[0]

        assert cda_prod == 2, f"Expected 2, got {cda_prod}"
        assert cda_staging == 1, f"Expected 1, got {cda_staging}"
        assert admin_prod == 1, f"Expected 1, got {admin_prod}"

    print("✅ Aggregation counts match expected per (username, deploy_status)")
    return True


def test_unavailable_when_no_local_events_and_no_s3():
    print("\n" + "=" * 80)
    print("TEST 4: No local events + unreachable S3 backfill raises a distinct error")
    print("=" * 80)

    auth_events_repository._get_downloader = lambda: None
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base_dir = Path(tmp_dir)  # nothing written here at all - fresh environment
            try:
                auth_events_repository.list_login_events(use_cache=False, base_dir=base_dir)
                print("❌ ERROR: expected AuthEventsUnavailableError, none raised")
                return False
            except AuthEventsUnavailableError:
                print("✅ Raised AuthEventsUnavailableError as expected (distinct from empty-but-available)")
                return True
    finally:
        import importlib
        importlib.reload(auth_events_repository)


def test_record_local_event_updates_parquet():
    print("\n" + "=" * 80)
    print("TEST 5: record_local_event() writes the file and refreshes the consolidated Parquet")
    print("=" * 80)

    # No S3 backfill in this scenario (isolated/hermetic) - record_local_event
    # must still write+rebuild locally on a best-effort basis.
    original_get_downloader = auth_events_repository._get_downloader
    auth_events_repository._get_downloader = lambda: None
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base_dir = Path(tmp_dir)
            event = {
                "event_id": "evt-new", "username": "new_user",
                "timestamp": "2026-08-06T10:00:00.000Z", "deploy_status": "production",
                "client_id": "CDA",
            }
            record_local_event(event, "year=2026/month=08/day=06/evt-new.json", base_dir=base_dir)

            assert auth_events_repository.local_event_path("year=2026/month=08/day=06/evt-new.json", base_dir).exists()
            assert auth_events_repository._consolidated_parquet_path(base_dir).exists()

            df = auth_events_repository.list_login_events(use_cache=False, base_dir=base_dir)
            assert len(df) == 1
            assert df.iloc[0]["event_id"] == "evt-new"
            assert df.iloc[0]["client_id"] == "CDA"
    finally:
        auth_events_repository._get_downloader = original_get_downloader

    print("✅ record_local_event() persisted the file and the Parquet reflects it")
    return True


def test_record_local_event_recovers_s3_history_first():
    print("\n" + "=" * 80)
    print("TEST 6: record_local_event() on a fresh env backfills prior S3 history before adding the new one")
    print("=" * 80)

    class FakeBody:
        def __init__(self, payload: bytes):
            self._payload = payload

        def read(self):
            return self._payload

    class FakeS3Client:
        def __init__(self, objects: dict):
            self._objects = objects

        def get_object(self, Bucket, Key):
            return {"Body": FakeBody(self._objects[Key])}

    class FakeDownloader:
        def __init__(self, objects: dict):
            self.bucket_name = "fake-bucket"
            self._objects = objects
            self.s3_client = FakeS3Client(objects)

        def list_objects(self, prefix):
            return list(self._objects.keys())

    prior_event = {"event_id": "old-1", "username": "old_user", "timestamp": "t0", "deploy_status": "production"}
    prefix = auth_events_repository.S3_PREFIX
    fake_objects = {f"{prefix}year=2026/month=01/day=01/old-1.json": json.dumps(prior_event).encode()}

    original_get_downloader = auth_events_repository._get_downloader
    auth_events_repository._get_downloader = lambda: FakeDownloader(fake_objects)
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base_dir = Path(tmp_dir)  # fresh environment - nothing local yet, login happens before any chart read
            new_event = {
                "event_id": "new-1", "username": "new_user",
                "timestamp": "t1", "deploy_status": "production", "client_id": "CDA",
            }
            record_local_event(new_event, "year=2026/month=08/day=06/new-1.json", base_dir=base_dir)

            df = auth_events_repository.list_login_events(use_cache=False, base_dir=base_dir)
            assert len(df) == 2, f"Expected both the recovered and the new event, got {len(df)}"
            assert set(df["event_id"]) == {"old-1", "new-1"}
    finally:
        auth_events_repository._get_downloader = original_get_downloader

    print("✅ Prior S3-only history was recovered locally instead of being silently dropped")
    return True


def main():
    tests = [
        ("Malformed events skipped", test_malformed_events_are_skipped),
        ("Empty events dir returns correct columns", test_empty_events_dir_returns_correct_columns),
        ("Aggregation by user and status", test_aggregation_counts_by_user_and_status),
        ("Unavailable when no local events and no S3", test_unavailable_when_no_local_events_and_no_s3),
        ("record_local_event updates Parquet", test_record_local_event_updates_parquet),
        ("record_local_event recovers S3 history first", test_record_local_event_recovers_s3_history_first),
    ]

    results = []
    for test_name, test_func in tests:
        try:
            results.append((test_name, test_func()))
        except Exception as e:
            print(f"\n❌ ERROR in {test_name}: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))

    print("\n" + "=" * 80)
    print("📊 TEST SUMMARY")
    print("=" * 80)
    for test_name, result in results:
        print(f"{'✅ PASS' if result else '❌ FAIL'}: {test_name}")

    total_passed = sum(1 for _, result in results if result)
    print(f"\nTotal: {total_passed}/{len(results)} tests passed")
    return 0 if total_passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
