"""Tests for the numeric provenance audit.

The hard requirement is that every figure an agent writes comes from a data query,
never from the model. Prompts alone cannot guarantee that, so `grounding.py` checks
the finished answer against the tool output produced during the same turn. These
tests pin both halves of its usefulness: it must catch invented figures, and it must
not flag legitimate ones, because a noisy auditor gets ignored.
"""

from __future__ import annotations

import json

from src.campbell_ai.grounding import (
    audit_response,
    collect_grounded_numbers,
    extract_numbers,
)


ALERTS = json.dumps(
    {
        "total": 21,
        "window": {
            "mode": "relative",
            "days": 60,
            "start_date": "2026-05-10T19:13:00",
            "end_date": "2026-07-09T19:13:00",
        },
        "by_unit": {"T_9": 9, "T_15": 7, "T_18": 5},
        "by_system": {"Motor": 20, "Direccion": 1},
    },
    ensure_ascii=False,
)

DETAIL = json.dumps(
    {
        "records": [
            {
                "unit_id": "T_18",
                "trigger": "EngCoolTemp",
                "peak_value": 100.917,
                "upper_limit": 105.0,
                "samples_above_limit": 0,
            }
        ]
    },
    ensure_ascii=False,
)


def test_extraction_ignores_ordered_list_markers():
    """A numbered list is structure; only claims should be audited."""
    text = "Hallazgos:\n1. El equipo T_9 tuvo 9 alertas.\n2. El sistema Motor concentra 20."

    numbers = extract_numbers(text)

    assert "9" in numbers
    assert "20" in numbers
    # "1." and "2." are markers, not claims. 9 appears once as a claim.
    assert numbers.count("1") == 0
    assert numbers.count("2") == 0


def test_extraction_normalizes_both_decimal_conventions():
    assert "100.92" in extract_numbers("el pico fue 100.92")
    assert "100.92" in extract_numbers("el pico fue 100,92")


def test_three_digit_groups_keep_both_readings_because_they_are_ambiguous():
    """`1.247` is 1247 in Spanish notation but a decimal in `100.917`."""
    from src.campbell_ai.grounding import extract_claims

    (_, variants), = extract_claims("hubo 1.247 alertas")

    assert variants == {"1.247", "1247"}
    # Either reading grounds the claim, so a correct answer is never flagged.
    assert audit_response("hubo 1.247 alertas", ['{"total": 1247}']).is_grounded
    assert audit_response("el pico fue 1.247", ['{"peak": 1.247}']).is_grounded
    assert not audit_response("hubo 1.247 alertas", ['{"total": 99}']).is_grounded


def test_collects_numbers_from_tool_payloads():
    grounded = collect_grounded_numbers([ALERTS])

    assert {"21", "9", "7", "5", "20"} <= grounded


def test_a_grounded_answer_passes():
    response = (
        "En los últimos **60 días** se registraron **21 alertas**. "
        "El equipo **T_9** concentra **9**, seguido de **T_15** con **7** y **T_18** con **5**. "
        "El sistema **Motor** acumula **20**."
    )

    report = audit_response(response, [ALERTS])

    assert report.unverified_numbers == []
    assert report.invented_units == []
    assert report.is_grounded is True
    assert report.verified >= 5


def test_an_invented_figure_is_reported():
    """The exact failure mode this exists for: a plausible number with no source."""
    response = "Se registraron **21 alertas**, con un costo estimado de **48750** dólares."

    report = audit_response(response, [ALERTS])

    assert "48750" in report.unverified_numbers
    assert report.is_grounded is False


def test_units_are_always_reported_because_no_source_publishes_them():
    grounded = "La temperatura máxima fue **100.92**, con umbral **105.0**."
    invented = "La temperatura máxima fue **100.92 °C**, con umbral **105.0 °C**."

    assert audit_response(grounded, [DETAIL]).invented_units == []
    report = audit_response(invented, [DETAIL])
    assert report.invented_units == ["°C"]
    assert report.is_grounded is False


def test_common_unit_spellings_are_detected():
    for text in (
        "el pico fue 100.92°C",
        "la presión llegó a 350 kPa",
        "el motor giró a 1800 rpm",
        "alcanzó 95 grados celsius",
    ):
        assert audit_response(text, [DETAIL]).invented_units, text


def test_rounding_of_a_grounded_value_is_accepted():
    """The data says 100.917; writing 100.92 is reporting, not inventing."""
    report = audit_response("El pico fue **100.92** frente al umbral **105.0**.", [DETAIL])

    assert report.unverified_numbers == []


def test_a_percentage_derived_from_grounded_counts_is_accepted():
    """20 of 21 is 95%: computing from real counts is not invention."""
    response = "El sistema **Motor** concentra **20** de **21** alertas, un **95%** del total."

    report = audit_response(response, [ALERTS])

    assert report.unverified_numbers == []


def test_a_percentage_with_no_grounded_pair_is_reported():
    report = audit_response("El **73.4%** de la flota está en riesgo.", [ALERTS])

    assert "73.4" in report.unverified_numbers


def test_a_difference_between_grounded_values_is_accepted():
    """Period comparisons and exceedances are legitimate arithmetic."""
    report = audit_response(
        "El equipo **T_9** tuvo **9** alertas y **T_15** **7**: una diferencia de **2**.",
        [ALERTS],
    )

    assert report.unverified_numbers == []


def test_dates_reformatted_from_a_grounded_timestamp_are_accepted():
    response = "La ventana analizada va del **10 de mayo** al **9 de julio de 2026**."

    report = audit_response(response, [ALERTS])

    assert report.unverified_numbers == []


def test_an_answer_with_no_tool_output_cannot_ground_any_figure():
    """If nothing was queried, no number in the answer has provenance."""
    report = audit_response("La flota registró **1247** alertas este mes.", [])

    assert report.tool_outputs_seen == 0
    assert "1247" in report.unverified_numbers
    assert report.is_grounded is False


def test_a_qualitative_answer_is_grounded_by_construction():
    report = audit_response(
        "Puedes ver el detalle en la sección **Monitoreo > Telemetría**.", []
    )

    assert report.is_grounded is True
    assert report.verified == 0


def test_iso_date_parts_ground_a_date_rewritten_in_spanish():
    """In "2026-04-26T00:00:00" the day is followed by T, so a generic scan misses it."""
    oil = json.dumps(
        {
            "total_units": 11,
            "sample_window": {"oldest": "2026-04-26T00:00:00", "newest": "2026-07-07T00:00:00"},
        }
    )

    report = audit_response(
        "Muestras entre el **26 de abril** y el **7 de julio de 2026**.", [oil]
    )

    assert report.unverified_numbers == []
    assert report.is_grounded is True


def test_a_two_step_derivation_is_reported_separately_from_invention():
    """6 of 11 is real arithmetic over grounded counts; the answer just hid its basis."""
    oil = json.dumps({"total_units": 11, "by_status": {"Normal": 5, "Anormal": 4, "Alerta": 2}})

    report = audit_response(
        "De **11** equipos, **4** están Anormal y **2** en Alerta: un 54% requiere atención.",
        [oil],
    )

    assert report.derived_without_basis == ["54"]
    # Not fabrication: every input is grounded, so the gate must not fail on it.
    assert report.unverified_numbers == []
    assert report.is_grounded is True


def test_invention_still_fails_even_though_derivation_is_tolerated():
    """The tolerance must not turn into a blanket pass for any number."""
    oil = json.dumps({"total_units": 11, "by_status": {"Normal": 5, "Anormal": 4, "Alerta": 2}})

    report = audit_response(
        "El costo de intervención asciende a **48750** dólares y la vida útil restante "
        "es de **11400** horas.",
        [oil],
    )

    assert "48750" in report.unverified_numbers
    assert "11400" in report.unverified_numbers
    assert report.is_grounded is False


def test_report_serializes_for_the_api_response():
    payload = audit_response("Costo de **48750**.", [ALERTS]).as_dict()

    assert payload["is_grounded"] is False
    assert payload["unverified_numbers"] == ["48750"]
    assert set(payload) == {
        "verified",
        "unverified_numbers",
        "invented_units",
        "derived_without_basis",
        "tool_outputs_seen",
        "is_grounded",
    }


def test_signal_catalogue_states_the_absence_of_units():
    """The catalogue is the authorized source for names, and it has no units to give."""
    from src.charts.signals import describe_signals, signal_label

    described = describe_signals(["EngCoolTemp", "NoSuchSignal"])

    assert described["EngCoolTemp"]["label"] == "Temperatura del refrigerante del motor"
    assert described["EngCoolTemp"]["unit"] is None
    assert "no la infieras" in described["EngCoolTemp"]["unit_note"]
    assert described["NoSuchSignal"]["catalogued"] is False
    assert signal_label("StrgOilTemp") == "Temperatura del aceite de dirección"


def test_dashboard_and_agents_share_the_signal_catalogue():
    from dashboard.components.alerts_charts import FEATURE_NAMES_ES
    from src.charts.signals import SIGNAL_LABELS

    assert FEATURE_NAMES_ES is SIGNAL_LABELS
