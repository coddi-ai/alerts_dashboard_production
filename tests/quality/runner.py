"""Runner for the Campbell AI response-quality suite.

Executes each case against the real service and scores the answer against the
expectations in `expectations.py`. It calls OpenAI, so it is opt-in: enable it with
``CAMPBELL_AI_QUALITY_SUITE=1`` under pytest, or run this module directly.

Direct run, from the repository root:

    python -m dotenv run -- python -m tests.quality.runner --client cda

Options: ``--client``, ``--case`` (repeatable), ``--tag`` (repeatable),
``--report PATH`` to write the full JSON, ``--concurrency`` (default 3).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from src.campbell_ai.config import get_campbell_settings
from src.campbell_ai.service import CampbellAIService
from tests.quality.expectations import (
    BOLD_PATTERN,
    CASES,
    CASE_MAP,
    PERIOD_PATTERN,
    DataFacts,
    QualityCase,
    date_variants,
    fold,
    resolve_facts,
)


@dataclass
class CaseResult:
    case_id: str
    question: str
    passed: bool
    seconds: float
    failures: list[str] = field(default_factory=list)
    request_type: str = ""
    response: str = ""
    charts: list[str] = field(default_factory=list)
    facts: dict[str, str] = field(default_factory=dict)
    grounding: dict = field(default_factory=dict)
    error: str | None = None

    def as_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "question": self.question,
            "passed": self.passed,
            "seconds": round(self.seconds, 1),
            "failures": self.failures,
            "request_type": self.request_type,
            "charts": self.charts,
            "facts": self.facts,
            "grounding": self.grounding,
            "error": self.error,
            "response": self.response,
        }


def _matches(haystack: str, needle) -> bool:
    """A string must appear; a tuple means any of its members may appear."""
    if isinstance(needle, tuple):
        return any(_matches(haystack, item) for item in needle)
    return fold(needle) in haystack


def evaluate(
    case: QualityCase,
    response: str,
    request_type: str,
    charts: list[dict],
    facts: dict[str, str],
    grounding: dict | None = None,
) -> list[str]:
    """Return the list of expectation failures for one answer."""
    failures: list[str] = []
    folded = fold(response)

    if case.expect_request_type and request_type != case.expect_request_type:
        failures.append(
            f"request_type={request_type!r}, se esperaba {case.expect_request_type!r}"
        )

    for needle in case.must_include:
        if not _matches(folded, needle):
            failures.append(f"falta mencionar {needle!r}")

    for pattern in case.must_include_regex:
        if not re.search(pattern, folded):
            failures.append(f"no satisface el patrón {pattern!r}")

    for name, value in facts.items():
        if not value:
            failures.append(f"el dato esperado {name} vino vacío")
        elif not _matches(folded, date_variants(value)):
            failures.append(f"no cita {name}={value!r}")

    for needle in case.must_not_include:
        if _matches(folded, needle):
            failures.append(f"no debería mencionar {needle!r}")

    if case.expect_bold and not BOLD_PATTERN.search(response):
        failures.append("sin negrita en los datos clave")

    if case.expect_period and not PERIOD_PATTERN.search(response):
        failures.append("no declara el periodo analizado")

    if case.expect_chart and not charts:
        failures.append("no generó ninguna figura")

    if case.expect_chart_ids:
        produced = {str(chart.get("chart_id", "")) for chart in charts}
        if not any(
            expected in identifier
            for expected in case.expect_chart_ids
            for identifier in produced
        ):
            failures.append(
                f"chart_id {sorted(produced)} no coincide con {list(case.expect_chart_ids)}"
            )

    if case.expect_grounded:
        report = grounding or {}
        unverified = report.get("unverified_numbers") or []
        units = report.get("invented_units") or []
        if unverified:
            failures.append(f"cifras sin origen en los datos: {unverified}")
        if units:
            failures.append(f"unidades de medida inventadas: {units}")
        if not report:
            failures.append("la respuesta no trae auditoría de trazabilidad")

    return failures


class QualityRunner:
    def __init__(self, client: str = "cda", username: str | None = None):
        self.service = CampbellAIService()
        self.client = client
        self.username = username or self._pick_username(client)
        self.facts = DataFacts(self.service.repository, client)

    @staticmethod
    def _pick_username(client: str) -> str:
        """First dashboard user authorized for this client, so the suite needs no secrets."""
        from config.users import USERS

        for username, user in USERS.items():
            allowed = {str(item).strip().lower() for item in user.get("clients", [])}
            if client.strip().lower() in allowed:
                return username
        raise RuntimeError(f"Ningun usuario del dashboard tiene acceso a {client}")

    async def run_case(self, case: QualityCase) -> CaseResult:
        started = time.time()
        try:
            facts = resolve_facts(self.facts, case.must_include_facts)
        except Exception as exc:
            return CaseResult(
                case_id=case.case_id,
                question=case.question,
                passed=False,
                seconds=time.time() - started,
                error=f"no se pudo anclar el caso en los datos: {exc}",
            )

        try:
            session = await self.service.initialize(self.username, self.client)
            session_id = session.session_id
            # A follow-up needs the previous turn in the same session.
            if case.follow_up_of:
                previous = CASE_MAP[case.follow_up_of]
                await self.service.send_message(
                    self.username, self.client, session_id, previous.question
                )
            result = await self.service.send_message(
                self.username, self.client, session_id, case.question
            )
        except Exception as exc:
            return CaseResult(
                case_id=case.case_id,
                question=case.question,
                passed=False,
                seconds=time.time() - started,
                error=f"{type(exc).__name__}: {exc}",
                facts=facts,
            )

        charts = [item.model_dump(mode="json") for item in result.visualizations]
        failures = evaluate(
            case,
            result.response,
            result.request_type,
            charts,
            facts,
            result.grounding,
        )
        return CaseResult(
            case_id=case.case_id,
            question=case.question,
            passed=not failures,
            seconds=time.time() - started,
            failures=failures,
            request_type=result.request_type,
            response=result.response,
            charts=[str(chart.get("chart_id", "")) for chart in charts],
            facts=facts,
            grounding=result.grounding,
        )

    async def run(
        self, cases: list[QualityCase], concurrency: int = 3
    ) -> list[CaseResult]:
        semaphore = asyncio.Semaphore(max(1, concurrency))

        async def guarded(case: QualityCase) -> CaseResult:
            async with semaphore:
                result = await self.run_case(case)
                mark = "PASS" if result.passed else "FAIL"
                print(f"[{mark}] {result.case_id} ({result.seconds:.0f}s)", flush=True)
                for failure in result.failures:
                    print(f"        - {failure}", flush=True)
                if result.error:
                    print(f"        ! {result.error}", flush=True)
                return result

        return list(await asyncio.gather(*(guarded(case) for case in cases)))


def select_cases(case_ids: list[str], tags: list[str]) -> list[QualityCase]:
    selected = list(CASES)
    if case_ids:
        selected = [case for case in selected if case.case_id in set(case_ids)]
    if tags:
        wanted = set(tags)
        selected = [case for case in selected if wanted & set(case.tags)]
    # A follow-up replays its predecessor itself, so ordering does not matter.
    return selected


def summarize(results: list[CaseResult]) -> dict:
    passed = [item for item in results if item.passed]
    return {
        "total": len(results),
        "passed": len(passed),
        "failed": len(results) - len(passed),
        "pass_rate": round(len(passed) / len(results) * 100, 1) if results else 0.0,
        "seconds": round(sum(item.seconds for item in results), 1),
        "cases": [item.as_dict() for item in results],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", default="cda")
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument("--report", default="")
    parser.add_argument("--concurrency", type=int, default=3)
    args = parser.parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY no configurada; la suite de calidad requiere el modelo real")
        return 2
    if not get_campbell_settings().internal_token:
        print("Aviso: CAMPBELL_AI_INTERNAL_TOKEN no configurado (no requerido en modo directo)")

    cases = select_cases(args.case, args.tag)
    if not cases:
        print("Ningun caso coincide con el filtro")
        return 2

    runner = QualityRunner(client=args.client)
    print(f"Ejecutando {len(cases)} casos para {args.client.upper()} como {runner.username}\n")
    results = asyncio.run(runner.run(cases, concurrency=args.concurrency))
    summary = summarize(results)

    print()
    print(
        f"{summary['passed']}/{summary['total']} casos aprobados "
        f"({summary['pass_rate']}%) en {summary['seconds']}s"
    )
    if args.report:
        Path(args.report).write_text(
            json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"Reporte completo en {args.report}")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
