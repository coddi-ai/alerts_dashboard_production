"""Provenance audit for the numbers an agent writes.

Every figure in an answer must originate in a tool result, never in the model's own
knowledge. Prompts alone do not guarantee that — a fluent, plausible number is
exactly what a language model produces when it has no data. This module closes the
loop by checking the finished answer against the tool output actually produced
during that turn.

The audit is a **detector, not a filter**: it reports which numeric claims could not
be traced, so the quality suite can fail on them and operators can see drift. It
does not rewrite the answer, because silently deleting a figure from a maintenance
diagnosis is worse than surfacing that it is unverified.

Derived values are accepted when their inputs are grounded, since a model that
computes a percentage from two real counts is not inventing anything:

- rounding (``100.917`` in data → ``100.92`` in the answer);
- thousands separators (``1247`` → ``1.247`` / ``1,247``);
- percentages computed from a grounded pair (``20`` of ``21`` → ``95%``);
- date parts (``2026-07-09`` → day ``9``, year ``2026``);
- differences and sums of two grounded values.

Units of measure are audited separately and always reported, because no dataset in
this repository publishes one.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field


# Numbers written with either decimal convention, optionally signed.
_NUMBER = re.compile(r"(?<![\w.,])-?\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?(?![\w])|(?<![\w.,])-?\d+(?:[.,]\d+)?(?![\w])")

# Ordered-list markers and headings are structure, not claims.
_LIST_MARKER = re.compile(r"^\s{0,6}\d{1,2}[.)]\s", re.MULTILINE)

# ISO date/timestamp, so its parts ground the dates an answer rewrites in Spanish.
_TIMESTAMP = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?"
)

# Physical units. None of them can be data-backed today, so any occurrence attached
# to a measurement is a model-supplied fact.
_UNIT_PATTERN = re.compile(
    r"(?<=[\d\s])(°\s?[CF]|º\s?[CF]|\bkPa\b|\bMPa\b|\bpsi\b|\bbar\b|\brpm\b|\bRPM\b"
    r"|\bppm\b|\bcSt\b|\bl/h\b|\bL/h\b|\bkm/h\b|\bm/s\b|\bkW\b|\bhp\b|\bNm\b|\bmm\b"
    r"|\bµm\b|\bum\b|\bgrados\s+celsius\b|\bgrados\s+cent[íi]grados\b)",
    re.IGNORECASE,
)

# Percent signs and plain counts are fine; these are the tokens that need a source.
_MAX_DECIMALS = 4


def _canonical_variants(text: str) -> set[str]:
    """Canonical readings of a numeric token.

    A single separator followed by exactly three digits is genuinely ambiguous:
    `1.247` is one thousand two hundred forty-seven in Spanish notation, while
    `100.917` is a decimal. Rather than guess, both readings are kept and a claim
    counts as grounded when any reading matches. Guessing wrong would flag correct
    answers, and a noisy auditor is one that gets ignored.
    """
    raw = str(text).strip()
    if not raw:
        return set()
    sign = -1.0 if raw.startswith("-") else 1.0
    raw = raw.lstrip("-")

    candidates: set[str] = set()

    def add(expression: str) -> None:
        try:
            candidates.add(_format(sign * float(expression)))
        except ValueError:
            return

    if "," in raw and "." in raw:
        # Both separators present: the last one is the decimal mark.
        decimal_sep = "," if raw.rfind(",") > raw.rfind(".") else "."
        group_sep = "." if decimal_sep == "," else ","
        add(raw.replace(group_sep, "").replace(decimal_sep, "."))
        return candidates

    separators = raw.count(",") + raw.count(".")
    if separators == 0:
        add(raw)
        return candidates

    normalized = raw.replace(",", ".")
    head, _, tail = normalized.rpartition(".")
    if separators == 1 and len(tail) == 3 and head.isdigit():
        # Ambiguous: keep both the decimal and the grouped reading.
        add(normalized)
        add(head + tail)
        return candidates
    if separators == 1:
        add(normalized)
        return candidates

    # Several separators can only be grouping marks.
    add(raw.replace(",", "").replace(".", ""))
    return candidates


def _canonical(text: str) -> str | None:
    """Preferred canonical reading of a token, or None if unusable."""
    variants = _canonical_variants(text)
    if not variants:
        return None
    # Prefer the decimal reading when both exist; it is the more specific claim.
    return sorted(variants, key=lambda item: ("." not in item, item))[0]


def _format(value: float) -> str:
    quantized = round(value, _MAX_DECIMALS)
    if quantized == int(quantized):
        return str(int(quantized))
    return f"{quantized:.{_MAX_DECIMALS}f}".rstrip("0")


def extract_numbers(text: str) -> list[str]:
    """Numeric claims in an answer, excluding list markers."""
    return [claim for claim, _ in extract_claims(text)]


def extract_claims(text: str) -> list[tuple[str, set[str]]]:
    """Numeric claims with every canonical reading of each one."""
    without_markers = _LIST_MARKER.sub("  ", str(text or ""))
    found: list[tuple[str, set[str]]] = []
    for match in _NUMBER.finditer(without_markers):
        variants = _canonical_variants(match.group(0))
        canonical = _canonical(match.group(0))
        if canonical is not None:
            found.append((canonical, variants))
    return found


def collect_grounded_numbers(tool_outputs: list[str]) -> set[str]:
    """Every number a tool actually returned this turn, in all its readings."""
    grounded: set[str] = set()
    for output in tool_outputs:
        text = str(output or "")
        # Date and time components first: in "2026-04-26T00:00:00" the hyphens are
        # separators, and the day is followed by "T", so the generic scan misses it
        # and would flag an answer that legitimately writes "26 de abril".
        for match in _TIMESTAMP.finditer(text):
            for part in match.groups():
                if part:
                    grounded.add(_format(float(part)))
        for match in _NUMBER.finditer(text):
            for variant in _canonical_variants(match.group(0)):
                grounded.add(variant)
                # A leading hyphen in serialized data is usually a separator, not a
                # sign; grounding both readings avoids false positives.
                grounded.add(variant.lstrip("-"))
    return {value for value in grounded if value}


def _rounding_matches(claim: str, grounded: set[str]) -> bool:
    """True when a grounded value rounds to the claimed one."""
    try:
        target = float(claim)
    except ValueError:
        return False
    decimals = len(claim.split(".")[1]) if "." in claim else 0
    for value in grounded:
        try:
            candidate = float(value)
        except ValueError:
            continue
        if round(candidate, decimals) == target:
            return True
    return False


def _derived_matches(claim: str, grounded: set[str]) -> bool:
    """True when the claim is a percentage, difference or sum of grounded values."""
    try:
        target = float(claim)
    except ValueError:
        return False
    numeric: list[float] = []
    for value in grounded:
        try:
            numeric.append(float(value))
        except ValueError:
            continue
    if not numeric:
        return False

    # Percentages of a grounded pair, as a model would render them.
    for numerator in numeric:
        for denominator in numeric:
            if denominator == 0.0:
                continue
            if _renders_as(numerator / denominator * 100, target):
                return True
    # Differences and sums, which appear in period comparisons and exceedances.
    for left in numeric:
        for right in numeric:
            if abs(abs(left - right) - abs(target)) < 0.01:
                return True
            if abs((left + right) - target) < 0.01:
                return True
    return False


def _multistep_derived_matches(claim: str, grounded: set[str]) -> bool:
    """True when the claim is a percentage over a sum of two grounded values.

    "6 of 11 equipos" is a legitimate reading of a status distribution, but the
    intermediate 6 never appears in any tool result. Kept separate from single-step
    derivation and reported at a lower severity: the inputs are real, what is missing
    is the answer stating its basis. Widening single-step acceptance to cover this
    would make almost any percentage acceptable and blunt the audit.
    """
    try:
        target = float(claim)
    except ValueError:
        return False
    if not 0 <= target <= 100:
        return False
    numeric: list[float] = []
    for value in grounded:
        try:
            candidate = float(value)
        except ValueError:
            continue
        if 0 <= candidate <= 100000:
            numeric.append(candidate)
    # Bounded search: the audit runs on every answer and must stay cheap.
    numeric = sorted(set(numeric))[:60]
    for denominator in numeric:
        if denominator <= 0:
            continue
        for left in numeric:
            for right in numeric:
                share = (left + right) / denominator * 100
                # Both renderings a model actually produces: rounded and truncated
                # (54.545 becomes "55" or "54"). Anything else is not a derivation.
                if _renders_as(share, target):
                    return True
    return False


def _renders_as(computed: float, target: float) -> bool:
    """True when `target` is how a model would write `computed`."""
    candidates = {
        round(computed),
        math.floor(computed),
        round(computed, 1),
        math.floor(computed * 10) / 10,
    }
    return any(abs(candidate - target) < 0.01 for candidate in candidates)


def _is_small_structural_number(claim: str) -> bool:
    """Counts of items the answer itself enumerates are structure, not data claims."""
    try:
        value = float(claim)
    except ValueError:
        return False
    return value.is_integer() and 0 <= value <= 5


@dataclass
class GroundingReport:
    """Traceability of the numeric claims in one answer."""

    verified: int = 0
    unverified_numbers: list[str] = field(default_factory=list)
    invented_units: list[str] = field(default_factory=list)
    # Reachable from grounded values only through arithmetic the answer did not show.
    # A quality issue (the basis should be stated), not fabrication.
    derived_without_basis: list[str] = field(default_factory=list)
    # Present in the user's own question. Restating the asked window ("los últimos 60
    # días") is not fabrication, but it is not data-backed either, so it is reported
    # apart from verified figures instead of failing the gate.
    echoed_from_question: list[str] = field(default_factory=list)
    tool_outputs_seen: int = 0

    @property
    def is_grounded(self) -> bool:
        """True when nothing was fabricated. Undeclared derivations do not fail this."""
        return not self.unverified_numbers and not self.invented_units

    def as_dict(self) -> dict:
        return {
            "verified": self.verified,
            "unverified_numbers": self.unverified_numbers,
            "invented_units": self.invented_units,
            "derived_without_basis": self.derived_without_basis,
            "echoed_from_question": self.echoed_from_question,
            "tool_outputs_seen": self.tool_outputs_seen,
            "is_grounded": self.is_grounded,
        }


def audit_response(
    response: str, tool_outputs: list[str], question: str = ""
) -> GroundingReport:
    """Check that every number in the answer traces back to a tool result.

    `question` is the user's own message. A number it already contains is not a
    fabrication when the answer restates it, so those are reported separately rather
    than counted as verified or flagged.
    """
    report = GroundingReport(tool_outputs_seen=len(tool_outputs))
    text = str(response or "")

    report.invented_units = sorted(
        {match.group(0).strip() for match in _UNIT_PATTERN.finditer(text)}
    )

    claims = extract_claims(text)
    if not claims:
        return report

    grounded = collect_grounded_numbers(tool_outputs)
    asked = collect_grounded_numbers([question]) if question else set()
    unverified: list[str] = []
    undeclared: list[str] = []
    echoed: list[str] = []
    for claim, variants in claims:
        if variants & grounded:
            report.verified += 1
        elif any(_rounding_matches(variant, grounded) for variant in variants):
            report.verified += 1
        elif any(_derived_matches(variant, grounded) for variant in variants):
            report.verified += 1
        elif _is_small_structural_number(claim):
            # Ambiguous: "3 sistemas" may just count the bullets that follow. Not
            # counted as verified, but not reported either, to keep the signal usable.
            continue
        elif any(_multistep_derived_matches(variant, grounded) for variant in variants):
            undeclared.append(claim)
        elif variants & asked:
            echoed.append(claim)
        else:
            unverified.append(claim)

    def ordered(values: list[str]) -> list[str]:
        return sorted(set(values), key=lambda item: (len(item), item))

    report.unverified_numbers = ordered(unverified)
    report.derived_without_basis = ordered(undeclared)
    report.echoed_from_question = ordered(echoed)
    return report
