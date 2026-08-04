"""Pytest entry point for the Campbell AI response-quality suite.

Skipped by default: these cases call OpenAI and cost money. Enable with
``CAMPBELL_AI_QUALITY_SUITE=1``. The expectation logic itself is always tested
below with recorded answers, so a bug in the scorer is caught for free.
"""

from __future__ import annotations

import os

import pytest

from tests.quality.expectations import CASES, QualityCase, fold
from tests.quality.runner import evaluate, select_cases, summarize

QUALITY_ENABLED = os.getenv("CAMPBELL_AI_QUALITY_SUITE", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


def test_case_catalogue_is_coherent():
    """Every case must be actionable: unique id, a question and a stated reason."""
    identifiers = [case.case_id for case in CASES]
    assert len(identifiers) == len(set(identifiers)), "hay case_id duplicados"
    for case in CASES:
        assert case.question.strip(), case.case_id
        assert case.why.strip(), f"{case.case_id} no explica qué protege"
        assert case.tags, f"{case.case_id} no tiene tags para filtrar"
        # A case that asserts nothing would always pass and hide regressions.
        asserts_something = any(
            (
                case.expect_request_type,
                case.must_include,
                case.must_include_regex,
                case.must_not_include,
                case.must_include_facts,
                case.expect_bold,
                case.expect_period,
                case.expect_chart,
                case.expect_chart_ids,
            )
        )
        assert asserts_something, f"{case.case_id} no verifica nada"
    for case in CASES:
        if case.follow_up_of:
            assert case.follow_up_of in identifiers, case.case_id


def test_selection_filters_by_case_and_tag():
    assert [case.case_id for case in select_cases(["report_refusal"], [])] == [
        "report_refusal"
    ]
    security = {case.case_id for case in select_cases([], ["seguridad"])}
    assert "cross_company_block" in security
    assert "pareto_chart" not in security


def test_fold_ignores_case_and_accents():
    assert fold("Refrigeración") == fold("refrigeracion")
    assert fold("ÍNDICE PQ") == fold("indice pq")


def _case(**kwargs) -> QualityCase:
    base = {"case_id": "probe", "question": "q", "why": "w", "tags": ("t",)}
    return QualityCase(**{**base, **kwargs})


def test_scorer_rejects_an_answer_that_omits_the_grounded_value():
    """The scorer must fail an answer that reads well but drops the real figure."""
    case = _case(must_include_facts=("top_alert_unit",), expect_bold=True)
    failures = evaluate(
        case,
        "El equipo con más alertas presenta varias incidencias recientes.",
        "agents",
        [],
        {"top_alert_unit": "T_9"},
    )
    assert any("T_9" in failure for failure in failures)
    assert any("negrita" in failure for failure in failures)


def test_scorer_accepts_a_grounded_and_formatted_answer():
    case = _case(
        must_include_facts=("top_alert_unit",),
        expect_bold=True,
        expect_period=True,
        must_not_include=("no se dispone",),
    )
    failures = evaluate(
        case,
        "El equipo **T_9** registró **9 alertas** el **2026-07-09**.",
        "agents",
        [],
        {"top_alert_unit": "T_9"},
    )
    assert failures == []


def test_scorer_matches_alternatives_ignoring_accents():
    case = _case(must_include=(("causa raíz", "causa ra"),))
    assert evaluate(case, "La causa raiz provisional es obstrucción.", "agents", [], {}) == []


def test_scorer_checks_request_type_and_named_charts():
    case = _case(
        expect_request_type="visualization",
        expect_chart=True,
        expect_chart_ids=("telemetry_fleet_status",),
    )
    assert evaluate(case, "Aquí está el gráfico.", "agents", [], {}) != []
    assert (
        evaluate(
            case,
            "Aquí está el gráfico.",
            "visualization",
            [{"chart_id": "telemetry_fleet_status"}],
            {},
        )
        == []
    )


def test_scorer_accepts_a_spanish_date_for_an_iso_fact():
    """The agent answers in Spanish; requiring the ISO literal failed correct answers."""
    from tests.quality.expectations import date_variants

    assert "9 de julio de 2026" in date_variants("2026-07-09")
    case = _case(must_include_facts=("latest_alert_date",))
    assert (
        evaluate(
            case,
            "La última alerta fue el **9 de julio de 2026 a las 19:13**.",
            "agents",
            [],
            {"latest_alert_date": "2026-07-09"},
        )
        == []
    )
    # A different date must still fail.
    assert evaluate(
        case,
        "La última alerta fue el 3 de marzo de 2025.",
        "agents",
        [],
        {"latest_alert_date": "2026-07-09"},
    ) != []


def test_scorer_regex_covers_variable_phrasing():
    case = _case(must_include_regex=(r"(no|sin)\b[^.]{0,60}ranking",))
    for answer in (
        "No hay un ranking publicado para transmisión.",
        "El modelo no ha calculado ningún ranking.",
        "Sin ranking disponible en esta fuente.",
    ):
        assert evaluate(case, answer, "agents", [], {}) == [], answer
    assert evaluate(case, "El ranking es T_9 primero.", "agents", [], {}) != []


def test_summary_reports_the_pass_rate():
    from tests.quality.runner import CaseResult

    summary = summarize(
        [
            CaseResult(case_id="a", question="q", passed=True, seconds=1.0),
            CaseResult(case_id="b", question="q", passed=False, seconds=1.0),
        ]
    )
    assert summary == {
        **summary,
        "total": 2,
        "passed": 1,
        "failed": 1,
        "pass_rate": 50.0,
    }


@pytest.mark.skipif(
    not QUALITY_ENABLED,
    reason="Suite de calidad deshabilitada; exporta CAMPBELL_AI_QUALITY_SUITE=1",
)
def test_response_quality_suite():
    """Run every case against the real agents and require a full pass."""
    import asyncio

    from tests.quality.runner import QualityRunner

    runner = QualityRunner(client=os.getenv("CAMPBELL_AI_QUALITY_CLIENT", "cda"))
    results = asyncio.run(runner.run(list(CASES), concurrency=3))
    summary = summarize(results)
    failed = [item for item in results if not item.passed]
    detail = "\n".join(
        f"{item.case_id}: {'; '.join(item.failures) or item.error}" for item in failed
    )
    assert not failed, f"{len(failed)}/{summary['total']} casos fallaron\n{detail}"
