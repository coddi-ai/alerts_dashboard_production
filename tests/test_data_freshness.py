"""
Test script for Data Freshness functionality.

This script tests:
1. CSV file loading
2. Timezone conversion (UTC to Chile)
3. Status calculation
4. Data processing
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pandas as pd
from datetime import datetime
import pytz

# Import the functions from the callback module
from dashboard.callbacks.data_freshness_callbacks import (
    FRESHNESS_CRITERIA,
    load_data_freshness,
    convert_utc_to_chile,
    calculate_freshness_status,
    process_freshness_data
)


def test_load_data():
    """Test CSV loading"""
    print("=" * 80)
    print("TEST 1: Loading CSV Data")
    print("=" * 80)
    
    df = load_data_freshness()
    
    if df.empty:
        print("❌ ERROR: No data loaded")
        return False
    
    print(f"✅ Loaded {len(df)} records")
    print(f"\nColumns: {df.columns.tolist()}")
    print(f"\nFirst 3 rows:")
    print(df.head(3))
    
    return True


def test_timezone_conversion():
    """Test UTC to Chile timezone conversion"""
    print("\n" + "=" * 80)
    print("TEST 2: Timezone Conversion")
    print("=" * 80)
    
    # Create a test UTC datetime
    utc_time = datetime(2026, 5, 12, 16, 7, 0)  # Example from CSV
    
    # Convert to Chile time
    chile_time = convert_utc_to_chile(utc_time)
    
    print(f"UTC time:   {utc_time}")
    print(f"Chile time: {chile_time}")
    print(f"Offset: {chile_time.strftime('%z')} ({chile_time.tzinfo})")
    
    # Expected: Chile is UTC-3 or UTC-4 depending on DST
    expected_hours_diff = -3  # or -4
    actual_hours_diff = (chile_time.hour - utc_time.hour) % 24
    
    if actual_hours_diff in [21, 20]:  # -3 or -4 hours in 24h format
        print(f"✅ Timezone conversion correct: {actual_hours_diff} hours difference")
        return True
    else:
        print(f"❌ ERROR: Unexpected time difference: {actual_hours_diff} hours")
        return False


def test_status_calculation():
    """Freshness labels and colors must match the criteria the dashboard applies.

    The expectations are derived from FRESHNESS_CRITERIA rather than restated here.
    This test previously hardcoded an older spec (labels 'Actualizado'/'Crítico' and
    different thresholds) and kept failing after the criteria were refactored, which
    is exactly the desync a derived test prevents.
    """
    chile_tz = pytz.timezone("America/Santiago")
    current_time = datetime.now(chile_tz)

    for data_type, criteria in FRESHNESS_CRITERIA.items():
        previous = pd.Timedelta(0)
        for index, (threshold, label, color) in enumerate(criteria):
            span = pd.Timedelta(threshold) - previous
            if span <= pd.Timedelta(0):
                # The last entry repeats its threshold as a sentinel for the
                # "worse than everything" case, covered separately below.
                continue
            inside = previous + span / 2
            status, actual_color, time_str = calculate_freshness_status(
                current_time - inside, data_type, current_time
            )
            assert status == label, (
                f"{data_type} a {inside} esperaba {label!r}, obtuvo {status!r}"
            )
            assert actual_color == color, f"{data_type} {label}: color {actual_color}"
            assert time_str and time_str != "N/A"
            previous = pd.Timedelta(threshold)

        # Beyond every threshold the worst status applies.
        worst_label, worst_color = criteria[-1][1], criteria[-1][2]
        status, actual_color, _ = calculate_freshness_status(
            current_time - (pd.Timedelta(criteria[-1][0]) * 2), data_type, current_time
        )
        assert status == worst_label, f"{data_type} fuera de rango: {status!r}"
        assert actual_color == worst_color


def test_status_calculation_handles_missing_and_unknown_inputs():
    """A missing timestamp or an unmodelled data type must not raise."""
    chile_tz = pytz.timezone("America/Santiago")
    current_time = datetime.now(chile_tz)

    status, color, time_str = calculate_freshness_status(
        pd.NaT, "Telemetria", current_time
    )
    assert (status, time_str) == ("Sin Datos", "N/A")
    assert color

    status, _, _ = calculate_freshness_status(
        current_time - pd.Timedelta(hours=1), "Vibraciones", current_time
    )
    assert status == "Desconocido"


def test_data_processing():
    """Test complete data processing pipeline"""
    print("\n" + "=" * 80)
    print("TEST 4: Data Processing Pipeline")
    print("=" * 80)
    
    # Load raw data
    df_raw = load_data_freshness()
    
    if df_raw.empty:
        print("❌ ERROR: No data to process")
        return False
    
    # Process data
    df_processed = process_freshness_data(df_raw)
    
    if df_processed.empty:
        print("❌ ERROR: Processing failed")
        return False
    
    print(f"✅ Processed {len(df_processed)} units")
    print(f"\nColumns: {df_processed.columns.tolist()}")
    
    # Show summary statistics
    if 'Estado_General' in df_processed.columns:
        print("\n📊 STATUS DISTRIBUTION:")
        status_counts = df_processed['Estado_General'].value_counts()
        for status, count in status_counts.items():
            print(f"  {status}: {count} units")
    
    # Show first few rows
    print("\n👁️ SAMPLE DATA (first 3 units):")
    display_cols = ['Unidad', 'Estado_General', 'Telemetría_Tiempo', 'Tribología_Tiempo']
    if all(col in df_processed.columns for col in display_cols):
        print(df_processed[display_cols].head(3).to_string(index=False))
    else:
        print(df_processed.head(3))
    
    print("\n✅ Data processing test passed!")
    return True


def main():
    """Run all tests"""
    print("\n" + "=" * 80)
    print("🧪 DATA FRESHNESS FUNCTIONALITY TESTS")
    print("=" * 80 + "\n")
    
    tests = [
        ("Load CSV Data", test_load_data),
        ("Timezone Conversion", test_timezone_conversion),
        ("Status Calculation", test_status_calculation),
        ("Data Processing", test_data_processing)
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n❌ ERROR in {test_name}: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))
    
    # Summary
    print("\n" + "=" * 80)
    print("📊 TEST SUMMARY")
    print("=" * 80)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    total_passed = sum(1 for _, result in results if result)
    total_tests = len(results)
    
    print(f"\nTotal: {total_passed}/{total_tests} tests passed")
    
    if total_passed == total_tests:
        print("\n🎉 ALL TESTS PASSED!")
        return 0
    else:
        print(f"\n⚠️ {total_tests - total_passed} test(s) failed")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
