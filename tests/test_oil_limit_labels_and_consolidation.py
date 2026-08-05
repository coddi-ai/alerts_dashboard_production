"""
Test script for the oil limit-visualization corrections (user-friendly
labels, equal/similar-value consolidation, lower-limit color, and the
isolated Tendencia oil-report-date filter).

Covers the validation scenarios from the "Oil Limit Visualization and Alert
Filtering Corrections" requirement:
1. Feature with all four limits available
2. Feature with only upper limits
4. Two limits with exactly equal values
5. Two limits within the configured similarity tolerance
6. Two limits close in value but outside the configured tolerance
7. Null lower limits (never plotted)
8. Lower limits rendered in purple
9. Generic feature label "Límite {feature}"
10. Viscosity label "Límite viscosidad"
13/14/15. Tendencia date filter: custom range, inclusive boundary, empty range
"""

import sys
import tempfile
from pathlib import Path

import pandas as pd

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dashboard.components.oil_charts import (
    consolidate_limit_entries,
    limit_values_are_equivalent,
    limit_line_color,
    LOWER_LIMIT_COLOR,
    UPPER_LIMIT_COLOR,
)
from dashboard.callbacks.alerts_callbacks import _build_oil_tendencia_view


def test_all_four_limits_no_collisions():
    print("=" * 80)
    print("TEST 1: Feature with all four limits available, none colliding")
    print("=" * 80)

    entries = [
        {'value': 8.0, 'tier': 'LIC', 'feature': 'viscosidad'},
        {'value': 12.0, 'tier': 'LIM', 'feature': 'viscosidad'},
        {'value': 45.0, 'tier': 'LSM', 'feature': 'viscosidad'},
        {'value': 58.0, 'tier': 'LSC', 'feature': 'viscosidad'},
    ]
    lines = consolidate_limit_entries(entries)
    assert len(lines) == 4, lines
    labels = {line['value']: line['label'] for line in lines}
    assert labels[8.0] == "Límite inferior viscosidad", labels
    assert labels[12.0] == "Límite inferior viscosidad", labels
    assert labels[45.0] == "Límite superior viscosidad", labels
    assert labels[58.0] == "Límite superior viscosidad", labels

    print("✅ Four distinct limits render as four lines with direction-qualified labels")
    return True


def test_only_upper_limits():
    print("\n" + "=" * 80)
    print("TEST 2: Feature with only upper limits (no sibling lower line)")
    print("=" * 80)

    entries = [{'value': 22.0, 'tier': 'LSC', 'feature': 'hierro'}]
    lines = consolidate_limit_entries(entries)
    assert len(lines) == 1
    assert lines[0]['label'] == "Límite hierro", lines

    print("✅ Single upper-only limit uses the bare 'Límite {feature}' label")
    return True


def test_exactly_equal_values_consolidate():
    print("\n" + "=" * 80)
    print("TEST 4: Two limits with exactly equal values consolidate into one line")
    print("=" * 80)

    entries = [
        {'value': 18.0, 'tier': 'LSM', 'feature': 'viscosidad'},
        {'value': 18.0, 'tier': 'LSC', 'feature': 'viscosidad'},
    ]
    lines = consolidate_limit_entries(entries)
    assert len(lines) == 1, lines
    assert lines[0]['label'] == "Límite marginal y condenatorio de viscosidad", lines
    assert lines[0]['value'] == 18.0

    print("✅ Exactly-equal limits render as one consolidated line/label")
    return True


def test_within_tolerance_consolidates():
    print("\n" + "=" * 80)
    print("TEST 5: Two limits within the similarity tolerance consolidate")
    print("=" * 80)

    # 100.0 vs 101.5: relative tolerance = 2% of 101.5 = 2.03, so 1.5 <= 2.03 -> equivalent
    assert limit_values_are_equivalent(100.0, 101.5) is True

    entries = [
        {'value': 100.0, 'tier': 'LSM', 'feature': 'viscosidad'},
        {'value': 101.5, 'tier': 'LSC', 'feature': 'viscosidad'},
    ]
    lines = consolidate_limit_entries(entries)
    assert len(lines) == 1, lines
    assert "Límite marginal y condenatorio de viscosidad" == lines[0]['label']

    print("✅ Near-equal limits within tolerance consolidate into one line")
    return True


def test_outside_tolerance_stays_separate():
    print("\n" + "=" * 80)
    print("TEST 6: Two limits close but outside tolerance stay separate")
    print("=" * 80)

    # 100.0 vs 103.5: relative tolerance = 2% of 103.5 = 2.07, gap is 3.5 -> NOT equivalent
    assert limit_values_are_equivalent(100.0, 103.5) is False

    entries = [
        {'value': 100.0, 'tier': 'LSM', 'feature': 'viscosidad'},
        {'value': 103.5, 'tier': 'LSC', 'feature': 'viscosidad'},
    ]
    lines = consolidate_limit_entries(entries)
    assert len(lines) == 2, lines
    labels = sorted(line['label'] for line in lines)
    assert labels == ["Límite superior viscosidad", "Límite superior viscosidad"], labels

    print("✅ Limits outside tolerance render as two separate lines")
    return True


def test_null_and_invalid_values_never_plotted():
    print("\n" + "=" * 80)
    print("TEST 7: Null / non-numeric limit values are never plotted")
    print("=" * 80)

    entries = [
        {'value': None, 'tier': 'LIC', 'feature': 'hierro'},
        {'value': None, 'tier': 'LIM', 'feature': 'hierro'},
        {'value': float('nan'), 'tier': 'LSM', 'feature': 'hierro'},
        {'value': 'not-a-number', 'tier': 'LSC', 'feature': 'hierro'},
    ]
    lines = consolidate_limit_entries(entries)
    assert lines == [], lines

    print("✅ Null/NaN/non-numeric entries are dropped, never rendered as a 0-line")
    return True


def test_lower_limits_are_purple():
    print("\n" + "=" * 80)
    print("TEST 8: Lower-limit lines use purple, upper-limit lines use red")
    print("=" * 80)

    assert limit_line_color(['LIC']) == LOWER_LIMIT_COLOR
    assert limit_line_color(['LIM']) == LOWER_LIMIT_COLOR
    assert limit_line_color(['LIC', 'LIM']) == LOWER_LIMIT_COLOR
    assert limit_line_color(['LSM']) == UPPER_LIMIT_COLOR
    assert limit_line_color(['LSC']) == UPPER_LIMIT_COLOR
    assert LOWER_LIMIT_COLOR != '#0072B2' and LOWER_LIMIT_COLOR != 'blue'
    assert LOWER_LIMIT_COLOR == '#6f42c1'

    print("✅ Lower-limit tiers resolve to the centrally-defined purple, not blue")
    return True


def test_generic_and_viscosity_labels():
    print("\n" + "=" * 80)
    print("TEST 9/10: Generic 'Límite {feature}' and 'Límite viscosidad' labels")
    print("=" * 80)

    generic = consolidate_limit_entries([{'value': 5.0, 'tier': 'LSC', 'feature': 'sodio'}])
    assert generic[0]['label'] == "Límite sodio", generic

    visc = consolidate_limit_entries([{'value': 18.0, 'tier': 'LSC', 'feature': 'viscosidad'}])
    assert visc[0]['label'] == "Límite viscosidad", visc

    print("✅ Feature name is used verbatim in the 'Límite {feature}' label")
    return True


def _sample_history(dates_and_values):
    df = pd.DataFrame({
        'sampleDate': pd.to_datetime([d for d, _ in dates_and_values]),
        'Hierro': [v for _, v in dates_and_values],
    })
    return df.sort_values('sampleDate')


def test_tendencia_date_filter_custom_range_inclusive():
    print("\n" + "=" * 80)
    print("TEST 13/14: Tendencia date filter - custom range with inclusive boundaries")
    print("=" * 80)

    history = _sample_history([
        ('2025-01-01', 10.0),
        ('2025-06-15', 12.0),
        ('2026-01-01', 14.0),
        ('2026-06-15', 16.0),
    ])
    comp_limits = {}
    children = _build_oil_tendencia_view(history, comp_limits, 'LT_1000',
                                          start_date='2025-06-15', end_date='2026-01-01')
    # children[1] is the grid/placeholder; a non-empty range with data should not
    # be the "no history" placeholder text.
    grid = children[1]
    assert not (hasattr(grid, 'children') and isinstance(getattr(grid, 'children', None), str)
                and 'Sin historial' in grid.children), "boundary samples were incorrectly excluded"

    print("✅ Samples exactly on the start/end boundary are included (inclusive range)")
    return True


def test_tendencia_date_filter_empty_range():
    print("\n" + "=" * 80)
    print("TEST 15: Tendencia date filter - no samples in the selected range")
    print("=" * 80)

    history = _sample_history([
        ('2025-01-01', 10.0),
        ('2025-06-15', 12.0),
    ])
    comp_limits = {}
    children = _build_oil_tendencia_view(history, comp_limits, 'LT_1000',
                                          start_date='2030-01-01', end_date='2030-06-01')
    grid = children[1]
    text = getattr(grid, 'children', None)
    assert text == "Sin historial para este equipo/componente", text

    print("✅ A range with no matching samples shows the empty-history placeholder")
    return True


def main():
    tests = [
        ("all four limits, no collisions", test_all_four_limits_no_collisions),
        ("only upper limits", test_only_upper_limits),
        ("exactly equal values consolidate", test_exactly_equal_values_consolidate),
        ("within tolerance consolidates", test_within_tolerance_consolidates),
        ("outside tolerance stays separate", test_outside_tolerance_stays_separate),
        ("null/invalid values never plotted", test_null_and_invalid_values_never_plotted),
        ("lower limits are purple", test_lower_limits_are_purple),
        ("generic and viscosity labels", test_generic_and_viscosity_labels),
        ("tendencia filter: custom range inclusive", test_tendencia_date_filter_custom_range_inclusive),
        ("tendencia filter: empty range", test_tendencia_date_filter_empty_range),
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
