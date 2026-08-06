"""
Test script for the Client Service Register (config/client_services.py).

Tests:
1. is_service_enabled() default-deny for unknown clients/services
2. is_service_enabled() true/false for known configured clients
3. get_enabled_services() ordering
4. validate_startup_config() flags unknown ids / duplicates / empty clients
5. load_config() raises on structurally invalid YAML
"""

import sys
import tempfile
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import config.client_services as client_services
from config.client_services import (
    InvalidClientServicesConfig,
    is_service_enabled,
    get_enabled_services,
    load_config,
    validate_startup_config,
)


def test_default_deny_unknown_client_or_service():
    print("=" * 80)
    print("TEST 1: Default-deny for unknown client/service")
    print("=" * 80)

    assert is_service_enabled("NOT_A_CLIENT", "overview-general") is False
    assert is_service_enabled("CDA", "not-a-service") is False
    assert is_service_enabled("", "overview-general") is False
    assert is_service_enabled("CDA", "") is False

    print("✅ Unknown client/service correctly default-denied")
    return True


def test_known_client_service_from_yaml():
    print("\n" + "=" * 80)
    print("TEST 2: Known client/service against the real client_services.yaml")
    print("=" * 80)

    assert is_service_enabled("CDA", "predictive") is True
    assert is_service_enabled("EMIN", "predictive") is False
    assert is_service_enabled("cda", "overview-general") is True  # case-insensitive client

    print("✅ CDA has predictive, EMIN does not, client lookup is case-insensitive")
    return True


def test_get_enabled_services_ordering():
    print("\n" + "=" * 80)
    print("TEST 3: get_enabled_services() preserves canonical order")
    print("=" * 80)

    services = get_enabled_services("EMIN")
    assert services == sorted(services, key=client_services.KNOWN_SERVICE_IDS.index)
    assert "predictive" not in services

    print(f"✅ EMIN services in canonical order: {services}")
    return True


def test_validate_startup_config_flags_problems():
    print("\n" + "=" * 80)
    print("TEST 4: validate_startup_config() flags unknown ids and empty clients")
    print("=" * 80)

    bad_config = {
        "UNKNOWN_CLIENT": {"overview-general"},
        "CDA": {"not-a-real-service"},
        "EMIN": set(),
    }
    problems = validate_startup_config(config=bad_config)

    assert any("UNKNOWN_CLIENT" in p for p in problems)
    assert any("not-a-real-service" in p for p in problems)
    assert any("EMIN" in p and "no enabled services" in p for p in problems)

    print(f"✅ Found {len(problems)} expected problems")
    return True


def test_load_config_raises_on_invalid_structure():
    print("\n" + "=" * 80)
    print("TEST 5: load_config() raises on structurally invalid YAML")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as tmp_dir:
        bad_path = Path(tmp_dir) / "bad.yaml"
        bad_path.write_text("not_clients_key:\n  foo: bar\n", encoding="utf-8")

        try:
            load_config(path=bad_path)
            print("❌ ERROR: expected InvalidClientServicesConfig, none raised")
            return False
        except InvalidClientServicesConfig:
            print("✅ Raised InvalidClientServicesConfig as expected")
            return True


def main():
    tests = [
        ("Default deny unknown client/service", test_default_deny_unknown_client_or_service),
        ("Known client/service from yaml", test_known_client_service_from_yaml),
        ("get_enabled_services ordering", test_get_enabled_services_ordering),
        ("validate_startup_config flags problems", test_validate_startup_config_flags_problems),
        ("load_config raises on invalid structure", test_load_config_raises_on_invalid_structure),
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
