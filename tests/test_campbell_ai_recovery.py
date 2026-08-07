"""Tests for schema inspection and self-correcting tool errors.

A failing tool used to answer "Fuente no disponible para el cliente activo" no
matter what went wrong. That message is usually false — the source exists and an
argument was wrong — and it leaves the agent with two bad options: abandon the
question or invent an answer. These tests pin the replacement: the real reason, the
vocabulary needed to fix it, and whether retrying makes sense at all.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from src.campbell_ai.data import (
    DATASET_FILTERS,
    DATASET_MAP,
    TOOL_DATASETS,
    DashboardDataRepository,
)
from src.campbell_ai.errors import CampbellDataError
from src.campbell_ai.tool_errors import sanitize, tool_failure


def _repository(tmp_path) -> DashboardDataRepository:
    alerts = tmp_path / "alerts" / "golden" / "cda"
    alerts.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "UnitId": "T_18",
                "Timestamp": "2026-07-09T19:13:00",
                "sistema": "Motor",
                "subsistema": "Refrigeracion",
                "componente": "MOTOR",
                "Trigger_type": "Telemetria",
                "Trigger_Var": "EngCoolTemp",
            },
            {
                "UnitId": "T_9",
                "Timestamp": "2026-07-01T10:00:00",
                "sistema": "Frenos",
                "subsistema": "Freno Delantero Derecho",
                "componente": "FRENOS",
                "Trigger_type": "Telemetria",
                "Trigger_Var": "RtFBrkTemp",
            },
        ]
    ).to_csv(alerts / "consolidated_alerts.csv", index=False)
    return DashboardDataRepository(tmp_path)


# ----------------------------------------------------------------- schema tool


def test_dataset_schema_exposes_the_real_filter_vocabulary(tmp_path):
    """The recovery step: read the values a column holds instead of guessing again."""
    payload = json.loads(_repository(tmp_path).describe_dataset("cda", "alerts"))

    entry = payload["datasets"]["alerts"]
    assert entry["available"] is True
    assert entry["rows"] == 2
    assert entry["read_with"] == "query_alerts"

    filters = entry["filters"]
    assert filters["system"]["column"] == "sistema"
    assert sorted(filters["system"]["values"]) == ["Frenos", "Motor"]
    assert "Refrigeracion" in filters["subsystem"]["values"]
    assert "EngCoolTemp" in filters["trigger_var"]["values"]
    assert sorted(filters["unit_id"]["values"]) == ["T_18", "T_9"]


def test_catalogue_lists_every_dataset_without_loading_vocabularies(tmp_path):
    """Reading every vocabulary would materialize every frame for no benefit."""
    payload = json.loads(_repository(tmp_path).describe_dataset("cda"))

    assert set(payload["datasets"]) >= {"alerts", "oil_classified", "maintenance_actions"}
    assert "filters" not in payload["datasets"]["alerts"]
    # A source that is not deployed says so instead of erroring.
    assert payload["datasets"]["oil_classified"]["available"] is False
    assert "no existe" in payload["datasets"]["oil_classified"]["detail"]


def test_schema_tool_rejects_an_unknown_dataset_and_lists_the_valid_ones(tmp_path):
    with pytest.raises(CampbellDataError, match="Dataset no registrado") as excinfo:
        _repository(tmp_path).describe_dataset("cda", "alertas_totales")

    # The message must carry the way out, not just the rejection.
    assert "alerts" in str(excinfo.value)


def test_schema_tool_hides_predictive_sources_from_unauthorized_clients(
    tmp_path, monkeypatch
):
    from src.campbell_ai import data as data_module

    monkeypatch.setattr(data_module, "predictive_module_allows", lambda client: False)

    payload = json.loads(_repository(tmp_path).describe_dataset("cda"))

    assert not [key for key in payload["datasets"] if key.startswith("predictive_")]


def test_filter_specs_cover_every_tool_backed_dataset():
    """A dataset with a query tool but no declared filters cannot be recovered from."""
    for tool, dataset in TOOL_DATASETS.items():
        assert dataset in DATASET_MAP, tool
        assert dataset in DATASET_FILTERS, f"{tool} lee {dataset} sin filtros declarados"
    for dataset, specs in DATASET_FILTERS.items():
        assert dataset in DATASET_MAP, dataset
        assert specs, dataset


# -------------------------------------------------------------- tool failures


def test_a_wrong_argument_is_reported_with_its_reason_and_a_retry_path(tmp_path):
    repository = _repository(tmp_path)

    try:
        repository.query_alerts("cda", start_date="ayer")
    except Exception as exc:
        payload = json.loads(tool_failure("query_alerts", exc))

    assert payload["ok"] is False
    # The real reason survives instead of a generic "source unavailable".
    assert "start_date" in payload["detail"]
    assert payload["recovery"]["retry_allowed"] is True
    assert payload["recovery"]["inspect_with"] == 'inspect_dataset(dataset="alerts")'


def test_a_missing_source_is_not_retryable(tmp_path):
    """Retrying a source that is not deployed wastes a turn and invites invention."""
    repository = _repository(tmp_path)

    try:
        repository.query_telemetry_components("cda")
    except Exception as exc:
        payload = json.loads(tool_failure("query_telemetry_components", exc))

    assert payload["recovery"]["retry_allowed"] is False
    assert "no reintentes" in payload["recovery"]["hint"].lower()
    assert (
        payload["recovery"]["inspect_with"]
        == 'inspect_dataset(dataset="telemetry_classified")'
    )


def test_an_unexpected_error_never_leaks_internals_and_blocks_retry():
    payload = json.loads(
        tool_failure("query_alerts", RuntimeError(r"KeyError at C:\Users\rodri\data.parquet"))
    )

    assert payload["detail"] == "Error interno al leer la fuente"
    assert "rodri" not in json.dumps(payload)
    assert payload["recovery"]["retry_allowed"] is False


def test_domain_messages_are_scrubbed_of_path_like_fragments():
    """Defence in depth: these messages now reach the model."""
    assert "rodri" not in sanitize(r"no se pudo leer C:\Users\rodri\data\alerts.csv")
    assert "[ruta interna]" in sanitize("falta /opt/app/data/alerts.csv")
    # An ordinary message is untouched.
    assert sanitize("start_date no tiene un formato válido") == (
        "start_date no tiene un formato válido"
    )


def test_chart_failures_keep_the_created_flag_the_prompt_checks(tmp_path):
    from src.campbell_ai.visualization import DashboardVisualizationService

    service = DashboardVisualizationService(_repository(tmp_path))

    try:
        service.create_chart(
            client="cda", dataset="alerts", chart_type="bar", dimension="inexistente"
        )
    except Exception as exc:
        payload = json.loads(
            tool_failure(
                "create_dashboard_chart", exc, dataset="alerts", extra={"created": False}
            )
        )

    assert payload["created"] is False
    # The rejection names the valid options, so one retry can succeed.
    assert "Disponibles" in payload["detail"]
    assert "unit" in payload["detail"]
    assert payload["recovery"]["retry_allowed"] is True


def test_prompts_document_the_retry_protocol():
    from src.campbell_ai.prompts import load_prompt

    query_prompt = load_prompt("data_analyst_query.md")
    visualization_prompt = load_prompt("data_analyst_visualization.md")

    for token in ("inspect_dataset", "retry_allowed", "recovery.inspect_with"):
        assert token in query_prompt, token
    assert "una sola vez" in query_prompt
    assert "retry_allowed" in visualization_prompt
    # The failure must not be read as "the data does not exist".
    assert "no hay información disponible" in query_prompt
