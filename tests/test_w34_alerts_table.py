"""W34-03 — Acortar Tabla de Alertas: regression guard, NOT a reimplementation.

The improvement was already implemented before W34 started:
`create_alerts_report_table` (the live table, rendered by `update_general_tab`)
already drops ID/Fuente/Evidencia from the visible `columns` while keeping
them in each row's `data` dict — the exact pattern documented in
documentation/alerts/agent_context_alerts.md. This file only guards against
regression: the legacy `create_alerts_datatable` variant (different columns,
including ID/Fuente as visible) still exists in alerts_tables.py, unimported
from alerts_callbacks.py since W34-03 — if it were ever wired back in behind
the same `id='alerts-datatable'`, the three columns would reappear.
"""

import pandas as pd

from dashboard.components.alerts_tables import create_alerts_report_table


def _sample_alerts_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "FusionID": "F-1",
                "Timestamp": pd.Timestamp("2026-07-10 16:00:00"),
                "UnitId": "CA-42",
                "sistema": "motor",
                "componente": "engine",
                "Trigger_type": "Mixto",
                "Trigger_Var": "EngCoolTemp",
                "mensaje_ia": "",
                "has_telemetry": True,
                "has_tribology": True,
            },
            {
                "FusionID": "F-2",
                "Timestamp": pd.Timestamp("2026-07-11 10:00:00"),
                "UnitId": "CA-43",
                "sistema": "motor",
                "componente": "rifle",
                "Trigger_type": "Telemetria",
                "Trigger_Var": "EngOilPres",
                "mensaje_ia": "",
                "has_telemetry": True,
                "has_tribology": False,
            },
        ]
    )


def test_id_fuente_evidencia_are_not_visible_columns():
    table = create_alerts_report_table(_sample_alerts_df())
    visible_ids = {column["id"] for column in table.columns}
    assert "ID" not in visible_ids
    assert "Fuente" not in visible_ids
    assert "Evidencia" not in visible_ids


def test_id_fuente_evidencia_still_present_in_row_data():
    """store_selected_alert and render_selected_alert_summary
    (alerts_callbacks.py) read these three fields from
    `derived_virtual_data` — they must survive even though they're hidden."""
    table = create_alerts_report_table(_sample_alerts_df())
    for row in table.data:
        assert "ID" in row and row["ID"] in ("F-1", "F-2")
        assert "Fuente" in row and row["Fuente"] in ("Multitécnica", "Telemetría")
        assert "Evidencia" in row and row["Evidencia"]


def test_mixto_row_highlight_rule_still_targets_the_fuente_field():
    """The purple left-border rule keys off the *value* in `data`, not a
    visible column — Dash's filter_query reads `data` regardless of what
    `columns` exposes, so this must keep working after W34-03."""
    table = create_alerts_report_table(_sample_alerts_df())
    filter_queries = [rule["if"].get("filter_query") for rule in table.style_data_conditional if "filter_query" in rule.get("if", {})]
    assert '{Fuente} = "Multitécnica"' in filter_queries


def test_visible_columns_are_exactly_the_seven_client_facing_fields():
    table = create_alerts_report_table(_sample_alerts_df())
    visible_ids = [column["id"] for column in table.columns]
    assert visible_ids == [
        "Fecha", "Unidad", "Sistema", "Componente",
        "Señal / variable", "Diagnóstico", "Acción",
    ]


def test_legacy_datatable_variant_is_not_imported_by_the_live_callback_module():
    """The regression this guards against: create_alerts_datatable (which DOES
    expose ID/Fuente as visible columns) must not be reachable from
    alerts_callbacks.py — if it were re-imported and wired to the same
    id='alerts-datatable', the columns W34-03 removed would reappear."""
    import dashboard.callbacks.alerts_callbacks as callbacks_module

    assert not hasattr(callbacks_module, "create_alerts_datatable")


def test_legacy_datatable_variant_still_exists_as_deliberately_unused_code():
    """Confirms it wasn't deleted outright — alerts_tables.py keeps it as a
    documented-legacy function per the W34 plan (leave dead code alone
    unless directly required)."""
    from dashboard.components import alerts_tables

    assert hasattr(alerts_tables, "create_alerts_datatable")
