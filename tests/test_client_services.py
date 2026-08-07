"""
Test script for the Client Service Register (config/client_services.py).

Tests:
1. is_service_enabled() default-deny for unknown clients/services
2. is_service_enabled() true/false for known configured clients
3. is_service_dummy() defaults to False when absent, true when configured
4. get_enabled_services() ordering
5. validate_startup_config() flags unknown ids / clients with nothing displayed
6. load_config() raises on structurally invalid JSON
7. load_config() correctly parses display/dummy flags
"""

import json
import sys
import tempfile
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import config.client_services as client_services
from config.client_services import (
    InvalidClientServicesConfig,
    get_enabled_services,
    is_service_dummy,
    is_service_enabled,
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


def test_known_client_service_from_config():
    print("\n" + "=" * 80)
    print("TEST 2: Known client/service against the real client_services.json")
    print("=" * 80)

    assert is_service_enabled("CDA", "predictive") is True
    assert is_service_enabled("EMIN", "predictive") is False
    assert is_service_enabled("cda", "overview-general") is True  # case-insensitive client

    print("✅ CDA has predictive, EMIN does not, client lookup is case-insensitive")
    return True


def test_is_service_dummy_defaults_and_lookup():
    print("\n" + "=" * 80)
    print("TEST 3: is_service_dummy() defaults to False, independent of display")
    print("=" * 80)

    # Nothing in the real config is marked dummy yet - both a configured
    # (display=true) and an absent (display=false) service default to False.
    assert is_service_dummy("CDA", "overview-general") is False
    assert is_service_dummy("EMIN", "predictive") is False
    assert is_service_dummy("NOT_A_CLIENT", "overview-general") is False

    print("✅ is_service_dummy() defaults to False for both configured and absent services")
    return True


def test_get_enabled_services_ordering():
    print("\n" + "=" * 80)
    print("TEST 4: get_enabled_services() preserves canonical order")
    print("=" * 80)

    services = get_enabled_services("EMIN")
    assert services == sorted(services, key=client_services.KNOWN_SERVICE_IDS.index)
    assert "predictive" not in services

    print(f"✅ EMIN services in canonical order: {services}")
    return True


def test_validate_startup_config_flags_problems():
    print("\n" + "=" * 80)
    print("TEST 5: validate_startup_config() flags unknown ids and clients with nothing displayed")
    print("=" * 80)

    bad_config = {
        "UNKNOWN_CLIENT": {"overview-general": {"display": True, "dummy": False}},
        "CDA": {"not-a-real-service": {"display": True, "dummy": False}},
        "EMIN": {},
    }
    problems = validate_startup_config(config=bad_config)

    assert any("UNKNOWN_CLIENT" in p for p in problems)
    assert any("not-a-real-service" in p for p in problems)
    assert any("EMIN" in p and "no displayed services" in p for p in problems)

    print(f"✅ Found {len(problems)} expected problems")
    return True


def test_load_config_raises_on_invalid_structure():
    print("\n" + "=" * 80)
    print("TEST 6: load_config() raises on structurally invalid JSON")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as tmp_dir:
        bad_path = Path(tmp_dir) / "bad.json"
        bad_path.write_text(json.dumps({"some_client": {"some_service": "not_a_mapping"}}), encoding="utf-8")

        try:
            load_config(path=bad_path)
            print("❌ ERROR: expected InvalidClientServicesConfig, none raised")
            return False
        except InvalidClientServicesConfig:
            print("✅ Raised InvalidClientServicesConfig as expected")
            return True


def test_load_config_parses_display_and_dummy_flags():
    print("\n" + "=" * 80)
    print("TEST 7: load_config() correctly parses display/dummy flags")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "custom.json"
        path.write_text(
            json.dumps({
                "cda": {
                    "overview-general": {"display": True, "dummy": False},
                    "monitoring-telemetry": {"display": True, "dummy": True},
                }
            }),
            encoding="utf-8",
        )
        config = load_config(path=path)

        assert config["CDA"]["overview-general"] == {"display": True, "dummy": False}
        assert config["CDA"]["monitoring-telemetry"] == {"display": True, "dummy": True}

    print("✅ display/dummy flags parsed correctly, client id normalized")
    return True


def main():
    tests = [
        ("Default deny unknown client/service", test_default_deny_unknown_client_or_service),
        ("Known client/service from config", test_known_client_service_from_config),
        ("is_service_dummy defaults and lookup", test_is_service_dummy_defaults_and_lookup),
        ("get_enabled_services ordering", test_get_enabled_services_ordering),
        ("validate_startup_config flags problems", test_validate_startup_config_flags_problems),
        ("load_config raises on invalid structure", test_load_config_raises_on_invalid_structure),
        ("load_config parses display/dummy flags", test_load_config_parses_display_and_dummy_flags),
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
