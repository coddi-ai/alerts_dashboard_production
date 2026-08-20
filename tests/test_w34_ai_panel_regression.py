"""W34-07 — Arreglar Análisis Inteligente: regression smoke test, NOT a
reimplementation.

Per the W34 plan, this improvement is marked `Listo` upstream — the only
obligation here is to confirm the existing default-message behavior still
works after W34-01/06/11/12 touch adjacent modules (labels, timestamps,
signal catalogue). No new diagnosis/severity logic is introduced.

Run last in Fase 1, after W34-01/06/11 land, so it validates against their
combined effect rather than a clean baseline that proves nothing about them.
"""

import ast
import json

import pandas as pd
import pytest

from dashboard.components.ai_analysis_panel import create_ai_analysis_panel, _parse_acciones
from dashboard.components.alerts_tables import parse_ia_message_sections


# ---------------------------------------------------------------------------
# No external calls: the module Alertas/Predictivo both render through must
# not import an HTTP client or an LLM SDK — a "sin análisis disponible" alert
# must never trigger a network call.
# ---------------------------------------------------------------------------

def test_ai_analysis_panel_module_makes_no_network_or_llm_imports():
    import dashboard.components.ai_analysis_panel as module
    source = ast.dump(ast.parse(open(module.__file__, encoding="utf-8").read()))
    for forbidden in ("requests", "httpx", "urllib", "openai", "agents"):
        assert forbidden not in source, f"unexpected import-like reference to {forbidden!r}"


# ---------------------------------------------------------------------------
# create_ai_analysis_panel — default messages when nothing is available
# ---------------------------------------------------------------------------

def test_panel_shows_default_message_for_all_three_sections_when_nothing_available():
    """The exact case tab_predictive_evidence.py hits for a unit with no row
    in analisis_inteligente.parquet yet — must render, not raise."""
    panel = create_ai_analysis_panel(None, None, None)
    rendered = str(panel)
    assert rendered.count("No disponible") == 3


def test_panel_shows_default_message_for_blank_strings_too():
    panel = create_ai_analysis_panel("", "   ", None)
    rendered = str(panel)
    assert rendered.count("No disponible") == 3


def test_panel_renders_provided_diagnostico_and_causa_verbatim():
    panel = create_ai_analysis_panel("Diagnóstico real", "Causa real", None)
    rendered = str(panel)
    assert "Diagnóstico real" in rendered
    assert "Causa real" in rendered
    assert "No disponible" in rendered  # only acciones is missing


def test_panel_renders_json_array_acciones_as_a_bulleted_list():
    panel = create_ai_analysis_panel("d", "c", '["Revisar presión", "Cambiar filtro"]')
    rendered = str(panel)
    assert "Revisar presión" in rendered
    assert "Cambiar filtro" in rendered


def test_panel_never_raises_for_any_combination_of_missing_fields():
    for diagnostico, causa, acciones in [
        (None, None, None),
        ("", "", ""),
        (None, "causa", None),
        ("diag", None, "[]"),
        (float("nan"), None, None),
    ]:
        create_ai_analysis_panel(diagnostico, causa, acciones)  # must not raise


# ---------------------------------------------------------------------------
# _parse_acciones — never raises, sane fallback for every input shape
# ---------------------------------------------------------------------------

def test_parse_acciones_handles_none_and_nan():
    assert _parse_acciones(None) == []
    assert _parse_acciones(float("nan")) == []


def test_parse_acciones_handles_empty_and_empty_json_array():
    assert _parse_acciones("") == []
    assert _parse_acciones("   ") == []
    assert _parse_acciones("[]") == []


def test_parse_acciones_handles_valid_json_array():
    assert _parse_acciones('["a1", "a2"]') == ["a1", "a2"]


def test_parse_acciones_handles_already_a_list():
    assert _parse_acciones(["a1", "a2", ""]) == ["a1", "a2"]


def test_parse_acciones_falls_back_to_plain_text_for_invalid_json():
    """Not valid JSON — treated as a single freeform action, not an error."""
    assert _parse_acciones("Revisar el sistema de enfriamiento") == [
        "Revisar el sistema de enfriamiento"
    ]


def test_parse_acciones_never_raises_for_malformed_input():
    for value in ["{broken", "[1, 2,", None, float("nan"), 42, {"not": "a list"}]:
        _parse_acciones(value)  # must not raise


# ---------------------------------------------------------------------------
# parse_ia_message_sections — empty input produces the documented empty shape
# ---------------------------------------------------------------------------

def test_parse_ia_message_sections_empty_input_produces_three_empty_keys():
    sections = parse_ia_message_sections("")
    assert sections == {"diagnostico": "", "causa_probable": "", "acciones": ""}


def test_parse_ia_message_sections_none_and_nan_produce_the_same_empty_shape():
    """None and float('nan') — the two shapes `mensaje_ia` actually takes for
    a missing value once loaded from CSV via pandas (an object-dtype column's
    missing cell is float NaN, not pandas' nullable pd.NA sentinel)."""
    assert parse_ia_message_sections(None) == {"diagnostico": "", "causa_probable": "", "acciones": ""}
    assert parse_ia_message_sections(float("nan")) == {
        "diagnostico": "",
        "causa_probable": "",
        "acciones": "",
    }


def test_parse_ia_message_sections_decodes_structured_capstone_json():
    """The structured-JSON path (Capstone) must still resolve correctly after
    W34-11's signal-catalogue change, since this function translates signal
    codes inside the diagnosis text via _translate_signal_text."""
    message = json.dumps(
        {
            "diagnostic": "engine_speed_rpm supera el límite",
            "recommended_actions": ["Revisar oil_level_pct"],
            "evidence": ["telemetry"],
        }
    )
    sections = parse_ia_message_sections(message)
    assert "Velocidad del motor" in sections["diagnostico"]
    assert "Nivel de aceite" in sections["acciones"]


def test_parse_ia_message_sections_never_raises_for_garbage_text():
    """Realistic garbage: malformed JSON or free text that doesn't match the
    regex sections — always a string, matching what a CSV text column holds."""
    for value in ["not json {{{", "DIAGNÓSTICO", "12345"]:
        parse_ia_message_sections(value)  # must not raise


def test_parse_ia_message_sections_guard_clause_has_a_known_gap_with_array_like_input():
    """Documents a pre-existing limitation, NOT a W34 regression: the
    function's `if not mensaje_ia or pd.isna(mensaje_ia):` guard raises for
    pandas' nullable NA sentinel or any list/array-like value, because
    `pd.isna()` on those returns an array/ambiguous NA rather than a single
    bool. Not triggered by this codebase's actual data path today — CSV
    loading (`pd.read_csv`, no nullable dtypes) only ever produces `str` or
    plain float `NaN` for this column (both handled correctly above) — so
    this is deliberately not "fixed" here per W34-07's "no reimplementar"
    scope. Recorded so a future change to the loader (e.g. adopting nullable
    dtypes) has a test that will fail loudly instead of finding this the
    same way this test's own first draft did."""
    with pytest.raises((TypeError, ValueError)):
        parse_ia_message_sections(pd.NA)
    with pytest.raises((TypeError, ValueError)):
        parse_ia_message_sections(["a", "list"])
