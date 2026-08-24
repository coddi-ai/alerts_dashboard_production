"""Contract tests for the read-only source catalog."""

from pathlib import Path

from src.data.catalog import build_client_availability, resolve_data_file


def test_auxiliary_loader_accepts_golden_layout(tmp_path: Path):
    expected = tmp_path / "auxiliar" / "golden" / "capstone" / "Data_Date_Last_Update.csv"
    expected.parent.mkdir(parents=True)
    expected.write_text("Data,Ultima Fecha de Actualizacion\nTelemetria,2026-08-01\n", encoding="utf-8")

    assert resolve_data_file("auxiliar", "CAPSTONE", "Data_Date_Last_Update.csv", tmp_path) == expected
    assert build_client_availability("CAPSTONE", tmp_path)["data_freshness"].status == "available"


def test_maintenance_weekly_csv_is_partial_contract(tmp_path: Path):
    maintenance = tmp_path / "mantentions" / "golden" / "emin"
    maintenance.mkdir(parents=True)
    (maintenance / "2026-W01.csv").write_text("machine_code,status\nU1,OK\n", encoding="utf-8")

    probe = build_client_availability("EMIN", tmp_path)["maintenance_contract"]

    assert probe.status == "partial"
    assert "contrato Parquet" in probe.note


def test_predictive_directory_without_component_csv_is_partial(tmp_path: Path):
    predictive = tmp_path / "predictive" / "golden" / "cda"
    predictive.mkdir(parents=True)
    (predictive / "analisis_inteligente.parquet").write_bytes(b"derived")

    probe = build_client_availability("CDA", tmp_path)["predictive_components"]

    assert probe.status == "partial"
    assert "no hay CSV" in probe.note


def test_telemetry_partition_is_available_without_changing_files(tmp_path: Path):
    partition = tmp_path / "telemetry" / "golden" / "cda" / "unit_health" / "year=2026" / "week=31"
    partition.mkdir(parents=True)
    source = partition / "part-000.parquet"
    source.write_bytes(b"snapshot")

    probe = build_client_availability("CDA", tmp_path)["telemetry_unit_health"]

    assert probe.status == "available"
    assert probe.path == str(tmp_path / "telemetry" / "golden" / "cda" / "unit_health")
    assert source.read_bytes() == b"snapshot"
