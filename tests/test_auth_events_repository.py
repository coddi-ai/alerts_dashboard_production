"""
Test script for src/data/auth_events_repository.py.

Tests, using a fake S3 downloader (no real network calls):
1. Malformed / missing-field JSON objects are skipped without breaking the rest
2. Valid events are parsed into the expected DataFrame shape
3. get_login_counts_by_user_and_status() aggregates correctly
4. An empty event set returns an empty DataFrame with the right columns
"""

import json
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import src.data.auth_events_repository as auth_events_repository
from src.data.auth_events_repository import get_login_counts_by_user_and_status


class FakeBody:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self):
        return self._payload


class FakeS3Client:
    def __init__(self, objects: dict):
        self._objects = objects  # key -> bytes

    def get_object(self, Bucket, Key):
        return {"Body": FakeBody(self._objects[Key])}


class FakeDownloader:
    def __init__(self, objects: dict):
        self.bucket_name = "fake-bucket"
        self._keys = list(objects.keys())
        self.s3_client = FakeS3Client(objects)

    def list_objects(self, prefix):
        return self._keys


def _install_fake_downloader(objects: dict):
    auth_events_repository._get_downloader = lambda: FakeDownloader(objects)


def test_malformed_events_are_skipped():
    print("=" * 80)
    print("TEST 1: Malformed events are skipped without breaking the rest")
    print("=" * 80)

    valid_event = {
        "event_id": "evt-1", "username": "cda_user",
        "timestamp": "2026-08-04T10:00:00.000Z", "deploy_status": "production",
    }
    objects = {
        "authentication_register/year=2026/month=08/day=04/valid.json": json.dumps(valid_event).encode(),
        "authentication_register/year=2026/month=08/day=04/not_json.json": b"{not valid json",
        "authentication_register/year=2026/month=08/day=04/missing_fields.json": json.dumps(
            {"event_id": "evt-2", "username": "cda_user"}
        ).encode(),
        "authentication_register/year=2026/month=08/day=04/not_an_object.json": json.dumps([1, 2, 3]).encode(),
    }
    _install_fake_downloader(objects)

    df = auth_events_repository.list_login_events(use_cache=False)

    assert len(df) == 1, f"Expected 1 valid event, got {len(df)}"
    assert df.iloc[0]["event_id"] == "evt-1"

    print(f"✅ Kept 1 valid event out of {len(objects)} objects, skipped 3 malformed")
    return True


def test_empty_events_return_correct_columns():
    print("\n" + "=" * 80)
    print("TEST 2: No events -> empty DataFrame with expected columns")
    print("=" * 80)

    _install_fake_downloader({})
    df = auth_events_repository.list_login_events(use_cache=False)

    assert df.empty
    assert list(df.columns) == ["event_id", "username", "timestamp", "deploy_status"]

    counts = get_login_counts_by_user_and_status(df)
    assert counts.empty
    assert list(counts.columns) == ["username", "deploy_status", "count"]

    print("✅ Empty event set produces empty DataFrames with correct columns")
    return True


def test_aggregation_counts_by_user_and_status():
    print("\n" + "=" * 80)
    print("TEST 3: Aggregation counts by username + deploy_status")
    print("=" * 80)

    events = [
        {"event_id": "1", "username": "cda_user", "timestamp": "t1", "deploy_status": "production"},
        {"event_id": "2", "username": "cda_user", "timestamp": "t2", "deploy_status": "production"},
        {"event_id": "3", "username": "cda_user", "timestamp": "t3", "deploy_status": "staging"},
        {"event_id": "4", "username": "admin", "timestamp": "t4", "deploy_status": "production"},
    ]
    objects = {f"authentication_register/{e['event_id']}.json": json.dumps(e).encode() for e in events}
    _install_fake_downloader(objects)

    df = auth_events_repository.list_login_events(use_cache=False)
    counts = get_login_counts_by_user_and_status(df)

    cda_prod = counts[(counts.username == "cda_user") & (counts.deploy_status == "production")]["count"].iloc[0]
    cda_staging = counts[(counts.username == "cda_user") & (counts.deploy_status == "staging")]["count"].iloc[0]
    admin_prod = counts[(counts.username == "admin") & (counts.deploy_status == "production")]["count"].iloc[0]

    assert cda_prod == 2, f"Expected 2, got {cda_prod}"
    assert cda_staging == 1, f"Expected 1, got {cda_staging}"
    assert admin_prod == 1, f"Expected 1, got {admin_prod}"

    print("✅ Aggregation counts match expected per (username, deploy_status)")
    return True


def main():
    tests = [
        ("Malformed events skipped", test_malformed_events_are_skipped),
        ("Empty events return correct columns", test_empty_events_return_correct_columns),
        ("Aggregation by user and status", test_aggregation_counts_by_user_and_status),
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
