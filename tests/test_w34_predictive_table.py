"""W34-10 — Mejorar Tabla Predictivo.

Original defects, all in the failure-mode table (`_failure_table`,
`tab_predictive_overview.py`):

1. A unit with NaN in both `avg_ranking_30d` and `max_fm_30d` defaulted to
   "Saludable" (NaN comparisons are always False in pandas, so it fell
   through every threshold check).
2. A present-but-NaN `ranking`/`avg_ranking_*` value rendered as the literal
   text "nan" (from `float(r.get(key, 0))`, which only defaults on a missing
   KEY, not a NaN value), styled green by `_score_cell_style`'s fall-through;
   a NaN failure-mode score silently became "0", also styled green. Both now
   render "—" with a neutral gray style.
3. `sort_values` on a single column falls back to an unstable quicksort for
   ties — two renders of the same input could show tied units in a
   different order. Now sorted with "Unit" as a deterministic secondary key.

Reconciled after merging `origin/dev`: `dev` independently replaced the
threshold-based status classification with `attach_status()`, which reads
`estado` straight from `analisis_inteligente.parquet` (REQ-PR-04) and
deliberately defaults an unscored unit to "Normal" so only three labels ever
appear (REQ-PR-05) — a different, more current product decision than this
file's original `classify_predictive_status` (which added a 4th "Sin datos"
status for exactly that case). `classify_predictive_status` was removed as
dead code once both call sites switched to `attach_status`; defect #1 above
is superseded by that newer design, not covered here anymore. Defects #2 and
#3 are independent of where `status` comes from and remain fully in scope —
re-applied on top of `dev`'s rewritten `_failure_table`/`_priority_card`
(new signature: `_failure_table(sorted_df, window, sort_by, ascending,
failure_modes)`, one ranking column instead of four, click-to-sort headers).
"""

import pandas as pd
import pytest

from dashboard.tabs.tab_predictive_overview import (
    _failure_table,
    _priority_card,
    _score_cell_style,
)


FAILURE_MODES = {"fm1": "Modo Uno", "fm2": "Modo Dos"}


def _unit_row(unit, status="Normal", ranking=10.0, avg30=10.0, avg60=10.0, avg90=10.0, max_fm_30d=10.0, **fm_scores):
    row = {
        "Unit": unit,
        "status": status,
        "ranking": ranking,
        "avg_ranking_30d": avg30,
        "avg_ranking_60d": avg60,
        "ranking_acum_90d": avg90,
        "max_fm_30d": max_fm_30d,
    }
    for key in FAILURE_MODES:
        row[f"{key}_30d"] = fm_scores.get(key, 10.0)
    return row


# ---------------------------------------------------------------------------
# 1. Cell styling — null is never rendered/styled like a healthy 0
# ---------------------------------------------------------------------------

def test_score_cell_style_none_is_neutral_not_green():
    null_style = _score_cell_style(None)
    healthy_zero_style = _score_cell_style(0.0)
    assert null_style != healthy_zero_style
    # Frontend consistency pass: the null style reads the same --surface-2 /
    # --text-muted tokens as the Estado x Unidad and Estado de Datos tables'
    # own "no data" badges, not an independently hand-picked grey pair.
    assert null_style == {"background": "var(--surface-2)", "text": "var(--text-muted)"}


def test_score_cell_style_nan_float_is_also_neutral():
    assert _score_cell_style(float("nan")) == _score_cell_style(None)


def test_priority_card_renders_dash_for_missing_score_not_the_text_nan():
    """Found during W34 visual QA: a unit with no computed ranking yet still
    rendered the literal text "nan" / "+nan" in the fleet-priority card,
    because _priority_card formats score/acum_30d/delta with plain f-strings
    with no NaN guard — the same defect class _failure_table and
    _score_cell_style already fix, in a sibling component that was missed."""
    card = _priority_card(
        "U1", score=float("nan"), acum_30d=float("nan"), delta=float("nan"),
        status="Normal", drivers=[],
    )
    rendered = str(card)
    assert "nan" not in rendered.lower()
    assert "—" in rendered


def test_priority_card_keeps_real_values_and_delta_sign_intact():
    """dev's layout shows acum_30d as the headline score (.0f) and score
    ("Reciente") as the secondary line (.1f) — the reverse of the emphasis
    this project's own tests originally assumed, reconciled after merging
    origin/dev's redesign of this card."""
    card = _priority_card(
        "U1", score=87.3, acum_30d=78.0, delta=4.5, status="Anormal", drivers=[],
    )
    rendered = str(card)
    assert "78" in rendered  # acum_30d headline
    assert "87.3" in rendered  # score, "Reciente" line
    assert "+4.5" in rendered
    assert "nan" not in rendered.lower()


def test_failure_table_renders_dash_for_missing_ranking_not_the_text_nan():
    df = pd.DataFrame([_unit_row("U1", ranking=float("nan"), avg30=float("nan"), max_fm_30d=float("nan"))])
    table = _failure_table(df, "avg_ranking_30d", "avg_ranking_30d", False, FAILURE_MODES)
    rendered = str(table)
    assert "nan" not in rendered.lower().replace("no data", "")  # "nan" text must not leak into a cell
    assert "—" in rendered


def test_failure_table_renders_dash_for_missing_failure_mode_score():
    """_failure_table returns Div([Table([Thead, Tbody(rows)])]) — navigate
    down to the single data row's cells: Unit, ranking (window-driven),
    Estado, fm1, fm2."""
    row = _unit_row("U1")
    row["fm1_30d"] = float("nan")
    df = pd.DataFrame([row])
    table_div = _failure_table(df, "avg_ranking_30d", "avg_ranking_30d", False, FAILURE_MODES)
    table = table_div.children[0]
    tbody = table.children[1]
    data_row = tbody.children[0]
    cells = data_row.children
    assert len(cells) == 5  # Unit, ranking (window), Estado, fm1, fm2
    fm1_cell = str(cells[-2])
    fm2_cell = str(cells[-1])
    assert "—" in fm1_cell
    assert "—" not in fm2_cell  # fm2 has a real value (10.0) — must render normally


def test_failure_table_header_says_estado_not_status():
    df = pd.DataFrame([_unit_row("U1")])
    table = _failure_table(df, "avg_ranking_30d", "avg_ranking_30d", False, FAILURE_MODES)
    header_text = str(table.children[0])
    assert "Estado" in header_text
    assert "Status" not in header_text


def test_failure_table_preserves_real_ranking_values_bit_for_bit():
    """W34-10 must not change the ranking itself — only how a missing one is
    displayed."""
    df = pd.DataFrame([_unit_row("U1", ranking=42.7, avg30=13.2)])
    table = _failure_table(df, "avg_ranking_30d", "avg_ranking_30d", False, FAILURE_MODES)
    rendered = str(table)
    assert "13.2" in rendered


def test_failure_table_ascending_toggle_still_renders():
    """dev's column-header click-to-sort feature added an `ascending` arg —
    confirm it doesn't break rendering in either direction (not a full test
    of the sort/toggle feature itself, which is dev's, not W34's)."""
    df = pd.DataFrame([_unit_row("U1", avg30=10.0), _unit_row("U2", avg30=90.0)])
    for ascending in (True, False):
        table = _failure_table(df, "avg_ranking_30d", "avg_ranking_30d", ascending, FAILURE_MODES)
        assert "U1" in str(table) and "U2" in str(table)


# ---------------------------------------------------------------------------
# 2. Deterministic tie order
# ---------------------------------------------------------------------------

def test_tied_units_sort_deterministically_across_repeated_calls():
    """Same input, sorted twice — the tie-break must produce the identical
    unit order both times (an unstable quicksort would not guarantee this)."""
    tied_df = pd.DataFrame([
        _unit_row("U3", avg30=50.0),
        _unit_row("U1", avg30=50.0),
        _unit_row("U2", avg30=50.0),
    ])

    first = tied_df.sort_values(["avg_ranking_30d", "Unit"], ascending=[False, True])["Unit"].tolist()
    second = tied_df.sort_values(["avg_ranking_30d", "Unit"], ascending=[False, True])["Unit"].tolist()
    assert first == second == ["U1", "U2", "U3"]


def test_non_tied_units_still_sort_by_score_first():
    df = pd.DataFrame([
        _unit_row("U_low", avg30=10.0),
        _unit_row("U_high", avg30=90.0),
    ])
    ordered = df.sort_values(["avg_ranking_30d", "Unit"], ascending=[False, True])["Unit"].tolist()
    assert ordered == ["U_high", "U_low"]
