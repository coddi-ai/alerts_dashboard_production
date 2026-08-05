"""
Test script for the four-limit Stewart output migration (data contract v2.8).

Covers:
1. classify_four_limit_value() boundary semantics with all four limits present
2. classify_four_limit_value() boundary semantics when LIC/LIM are null
3. classify_four_limit_value() never applies lower-limit evaluation when only
   one of LIC/LIM is available (defensive - contract says both or neither)
4. Exact-limit boundary equality cases (value == each of LIC/LIM/LSM/LSC)
5. get_essay_limits_four() oil-hour-range fallback hierarchy, including
   averaging that never treats a missing (null) lower limit as zero
6. load_stewart_limits_four() never coerces a null LIC/LIM to 0
"""

import sys
import tempfile
from pathlib import Path

import pandas as pd

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dashboard.components.oil_charts import (
    classify_four_limit_value,
    get_essay_limits_four,
)
from src.data.loaders import load_stewart_limits_four


def test_classify_with_lower_limits():
    print("=" * 80)
    print("TEST 1: classify_four_limit_value() with LIC/LIM/LSM/LSC all present")
    print("=" * 80)

    LIC, LIM, LSM, LSC = 10.0, 20.0, 80.0, 90.0

    cases = [
        (5.0, 'Inferior Condenatorio'),    # value < LIC
        (15.0, 'Inferior Marginal'),       # LIC <= value < LIM
        (50.0, 'Normal'),                  # LIM <= value <= LSM
        (85.0, 'Superior Marginal'),       # LSM < value <= LSC
        (95.0, 'Superior Condenatorio'),   # value > LSC
    ]
    for value, expected in cases:
        actual = classify_four_limit_value(value, LIC, LIM, LSM, LSC)
        assert actual == expected, f"value={value}: expected {expected}, got {actual}"

    print("✅ All five bands classified correctly")
    return True


def test_classify_exact_boundaries():
    print("\n" + "=" * 80)
    print("TEST 2: Exact-limit boundary equality (§8 scenario 8)")
    print("=" * 80)

    LIC, LIM, LSM, LSC = 10.0, 20.0, 80.0, 90.0

    # value == LIC -> NOT Inferior Condenatorio (strict <), falls into Inferior Marginal
    assert classify_four_limit_value(LIC, LIC, LIM, LSM, LSC) == 'Inferior Marginal'
    # value == LIM -> Normal (LIM <= value <= LSM)
    assert classify_four_limit_value(LIM, LIC, LIM, LSM, LSC) == 'Normal'
    # value == LSM -> Normal (inclusive upper bound of Normal band)
    assert classify_four_limit_value(LSM, LIC, LIM, LSM, LSC) == 'Normal'
    # value == LSC -> Superior Marginal (inclusive upper bound, not Condenatorio)
    assert classify_four_limit_value(LSC, LIC, LIM, LSM, LSC) == 'Superior Marginal'

    print("✅ Exact boundary values match the main service's closed/open interval spec")
    return True


def test_classify_without_lower_limits():
    print("\n" + "=" * 80)
    print("TEST 3: classify_four_limit_value() with LIC/LIM null (Desgaste/Aditivo groups)")
    print("=" * 80)

    LSM, LSC = 80.0, 90.0

    cases = [
        (5.0, 'Normal'),                   # value <= LSM
        (80.0, 'Normal'),                  # value == LSM -> Normal (inclusive)
        (85.0, 'Superior Marginal'),       # LSM < value <= LSC
        (90.0, 'Superior Marginal'),       # value == LSC -> Superior Marginal (inclusive)
        (95.0, 'Superior Condenatorio'),   # value > LSC
    ]
    for value, expected in cases:
        actual = classify_four_limit_value(value, None, None, LSM, LSC)
        assert actual == expected, f"value={value}: expected {expected}, got {actual}"

    print("✅ Three-tier fallback (no lower limits) classified correctly")
    return True


def test_classify_requires_both_lic_and_lim():
    print("\n" + "=" * 80)
    print("TEST 4: Lower-limit evaluation only applies when BOTH LIC and LIM are present")
    print("=" * 80)

    LSM, LSC = 80.0, 90.0

    # Only LIC present (LIM missing) -> must NOT apply lower-limit evaluation
    assert classify_four_limit_value(1.0, 10.0, None, LSM, LSC) == 'Normal'
    # Only LIM present (LIC missing) -> must NOT apply lower-limit evaluation
    assert classify_four_limit_value(1.0, None, 20.0, LSM, LSC) == 'Normal'

    print("✅ Asymmetric null LIC/LIM never triggers lower-limit classification")
    return True


def test_get_essay_limits_four_fallback_hierarchy():
    print("\n" + "=" * 80)
    print("TEST 5: get_essay_limits_four() oil-hour-range fallback hierarchy")
    print("=" * 80)

    comp_limits = {
        'Hierro': {
            'LT_1000': {'LIC': None, 'LIM': None, 'LSM': 40.0, 'LSC': 50.0},
            'GE_1000': {'LIC': None, 'LIM': None, 'LSM': 60.0, 'LSC': 70.0},
        },
        'Calcio': {
            # No exact match for 'UNKNOWN' and no 'ALL' - must average, and must
            # NOT treat the missing LIC/LIM bucket as zero.
            'LT_1000': {'LIC': 1000.0, 'LIM': 1200.0, 'LSM': 1800.0, 'LSC': 1900.0},
            'GE_1000': {'LIC': None, 'LIM': None, 'LSM': 1200.0, 'LSC': 1300.0},
        },
    }

    # Exact match
    result = get_essay_limits_four(comp_limits, 'Hierro', 'GE_1000')
    assert result == {'LIC': None, 'LIM': None, 'LSM': 60.0, 'LSC': 70.0}, result

    # Averaging fallback for an oilHourRange not present ('UNKNOWN')
    result = get_essay_limits_four(comp_limits, 'Hierro', 'UNKNOWN')
    assert result['LSM'] == 50.0, result   # avg(40, 60)
    assert result['LSC'] == 60.0, result   # avg(50, 70)
    assert result['LIC'] is None and result['LIM'] is None, result

    # Averaging must skip the None bucket for Calcio's LIC/LIM (never average as 0)
    result = get_essay_limits_four(comp_limits, 'Calcio', 'UNKNOWN')
    assert result['LIC'] == 1000.0, result   # avg over the single non-null bucket, not avg(1000, 0)
    assert result['LIM'] == 1200.0, result
    assert result['LSM'] == 1500.0, result   # avg(1800, 1200) - both buckets contribute here
    assert result['LSC'] == 1600.0, result   # avg(1900, 1300)

    # Essay not found at all
    assert get_essay_limits_four(comp_limits, 'NoSuchEssay', 'LT_1000') is None

    print("✅ Fallback hierarchy and null-safe averaging behave as specified")
    return True


def test_load_stewart_limits_four_preserves_nulls():
    print("\n" + "=" * 80)
    print("TEST 6: load_stewart_limits_four() never coerces null LIC/LIM to 0")
    print("=" * 80)

    df = pd.DataFrame([
        {
            'client': 'CDA', 'machine': 'camion', 'component': 'motor diesel',
            'essay': 'Hierro', 'oilHourRange': 'GE_1000', 'GroupElement': 'Desgaste',
            'min_value': 12.0, 'LIC': None, 'LIM': None, 'LSM': 45.0, 'LSC': 58.0,
            'sample_count': 450, 'calculation_date': '2026-08-04T10:30:00',
        },
        {
            'client': 'CDA', 'machine': 'camion', 'component': 'motor diesel',
            'essay': 'Viscocidad', 'oilHourRange': 'GE_1000', 'GroupElement': 'Fisico Quimico',
            'min_value': 5.0, 'LIC': 8.0, 'LIM': 10.0, 'LSM': 45.0, 'LSC': 58.0,
            'sample_count': 450, 'calculation_date': '2026-08-04T10:30:00',
        },
    ])

    with tempfile.TemporaryDirectory() as tmp_dir:
        parquet_path = Path(tmp_dir) / 'stewart_limits_four.parquet'
        df.to_parquet(parquet_path, index=False)

        limits = load_stewart_limits_four(parquet_path)

        hierro = limits['CDA']['camion']['motor diesel']['Hierro']['GE_1000']
        assert hierro['LIC'] is None, hierro
        assert hierro['LIM'] is None, hierro
        assert hierro['LSM'] == 45.0
        assert hierro['LSC'] == 58.0

        viscocidad = limits['CDA']['camion']['motor diesel']['Viscocidad']['GE_1000']
        assert viscocidad['LIC'] == 8.0
        assert viscocidad['LIM'] == 10.0

    print("✅ Null LIC/LIM round-trip as None, never as 0")
    return True


def main():
    tests = [
        ("classify with lower limits (5-tier)", test_classify_with_lower_limits),
        ("classify exact boundaries", test_classify_exact_boundaries),
        ("classify without lower limits (3-tier)", test_classify_without_lower_limits),
        ("classify requires both LIC and LIM", test_classify_requires_both_lic_and_lim),
        ("get_essay_limits_four fallback hierarchy", test_get_essay_limits_four_fallback_hierarchy),
        ("load_stewart_limits_four preserves nulls", test_load_stewart_limits_four_preserves_nulls),
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
