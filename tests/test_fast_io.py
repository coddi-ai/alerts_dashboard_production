from pathlib import Path

import pandas as pd

from src.data.fast_io import engine_name, read_csv, read_csv_filtered


def test_fast_reader_preserves_pandas_contract(tmp_path: Path, monkeypatch):
    source = tmp_path / "source.csv"
    source.write_text("Unit,Fecha,ranking\nU1,2026-08-01,42\n", encoding="utf-8")
    monkeypatch.setenv("DASHBOARD_FRAME_ENGINE", "pandas")

    frame = read_csv(source, columns=["Unit", "Fecha"])

    assert isinstance(frame, pd.DataFrame)
    assert list(frame.columns) == ["Unit", "Fecha"]
    assert len(frame) == 1
    assert engine_name() == "pandas"


def test_filtered_reader_preserves_row_predicate(tmp_path: Path, monkeypatch):
    source = tmp_path / "alerts.csv"
    source.write_text(
        "AlertID,Unit,Value\nA,U1,10\nA,U2,20\nB,U1,30\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DASHBOARD_FRAME_ENGINE", "pandas")

    frame = read_csv_filtered(source, {"AlertID": ["A"], "Unit": ["U2"]})

    assert frame.to_dict("records") == [{"AlertID": "A", "Unit": "U2", "Value": 20}]
