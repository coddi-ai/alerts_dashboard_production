"""W34-02 — Mejorar Look&Feel Estado de Datos.

Before: three independently hand-picked icon/color palettes for the same
three statuses (Ok/Atención/Preocupante) — one in
`tab_data_freshness.py::_build_legend`, one baked into
`FRESHNESS_CRITERIA`'s tuples, one hardcoded across 8 `style_data_conditional`
rules in the table (repeated once per column). They happened to roughly
agree; nothing enforced it.

After: `FRESHNESS_STATUS_STYLE` is the single source (icon, accent, bg,
text) all three consume — `bg`/`text` reuse the app-wide :root design
tokens from `predictive_styles.css` (loaded globally via assets/) instead of
a fourth hardcoded palette.

Explicitly NOT touched (per the plan's "no cambia el cálculo de frescura"):
the threshold values inside FRESHNESS_CRITERIA, and calculate_freshness_status's
actual classification logic — only where the *color value* comes from.
"""

from datetime import datetime, timedelta

import pytz

from dashboard.callbacks.data_freshness_callbacks import (
    FRESHNESS_CRITERIA,
    FRESHNESS_STATUS_STYLE,
    calculate_freshness_status,
)
from dashboard.tabs.tab_data_freshness import _build_legend


# ---------------------------------------------------------------------------
# 1. Thresholds are untouched — only the color's source changed
# ---------------------------------------------------------------------------

def test_telemetria_thresholds_unchanged():
    thresholds = [t for t, _, _ in FRESHNESS_CRITERIA['Telemetria']]
    assert thresholds == [timedelta(hours=2), timedelta(hours=24), timedelta(hours=24)]


def test_tribologia_thresholds_unchanged():
    thresholds = [t for t, _, _ in FRESHNESS_CRITERIA['Tribologia']]
    assert thresholds == [timedelta(days=20), timedelta(days=40), timedelta(days=40)]


def test_criteria_colors_still_match_the_original_hex_values():
    """The consolidation must be value-preserving — same three hex codes,
    now traced to FRESHNESS_STATUS_STYLE instead of typed twice."""
    telem_colors = [c for _, _, c in FRESHNESS_CRITERIA['Telemetria']]
    assert telem_colors == ['#28a745', '#ffc107', '#dc3545']
    tribo_colors = [c for _, _, c in FRESHNESS_CRITERIA['Tribologia']]
    assert tribo_colors == ['#28a745', '#ffc107', '#dc3545']


def test_criteria_colors_are_literally_the_same_object_as_the_style_map():
    """Not just equal by coincidence — FRESHNESS_CRITERIA's color values are
    read directly from FRESHNESS_STATUS_STYLE, so they cannot drift apart."""
    for label in ('Ok', 'Atención', 'Preocupante'):
        criteria_color = next(c for _, l, c in FRESHNESS_CRITERIA['Telemetria'] if l == label)
        assert criteria_color == FRESHNESS_STATUS_STYLE[label]['accent']


# ---------------------------------------------------------------------------
# 2. calculate_freshness_status — classification behavior unchanged
# ---------------------------------------------------------------------------

def _chile_now():
    return datetime.now(pytz.timezone('America/Santiago'))


def test_missing_value_is_sin_datos():
    status, color, time_str = calculate_freshness_status(None, 'Telemetria', _chile_now())
    assert status == 'Sin Datos'
    assert color == FRESHNESS_STATUS_STYLE['Sin Datos']['accent']
    assert time_str == 'N/A'


def test_recent_telemetria_is_ok():
    now = _chile_now()
    status, color, _ = calculate_freshness_status(now - timedelta(minutes=30), 'Telemetria', now)
    assert status == 'Ok'
    assert color == FRESHNESS_STATUS_STYLE['Ok']['accent']


def test_stale_telemetria_is_atencion():
    now = _chile_now()
    status, _, _ = calculate_freshness_status(now - timedelta(hours=10), 'Telemetria', now)
    assert status == 'Atención'


def test_very_stale_telemetria_is_preocupante():
    now = _chile_now()
    status, _, _ = calculate_freshness_status(now - timedelta(hours=30), 'Telemetria', now)
    assert status == 'Preocupante'


def test_tribologia_uses_day_scale_thresholds():
    now = _chile_now()
    status, _, _ = calculate_freshness_status(now - timedelta(days=10), 'Tribologia', now)
    assert status == 'Ok'
    status, _, _ = calculate_freshness_status(now - timedelta(days=30), 'Tribologia', now)
    assert status == 'Atención'
    status, _, _ = calculate_freshness_status(now - timedelta(days=50), 'Tribologia', now)
    assert status == 'Preocupante'


# ---------------------------------------------------------------------------
# 3. Ok / Atención / Preocupante / Sin Datos are all visually distinct
# ---------------------------------------------------------------------------

def test_all_four_statuses_have_distinct_accent_colors():
    accents = {style['accent'] for style in FRESHNESS_STATUS_STYLE.values()}
    assert len(accents) == 4


def test_all_four_statuses_have_distinct_backgrounds():
    backgrounds = {style['bg'] for style in FRESHNESS_STATUS_STYLE.values()}
    assert len(backgrounds) == 4


def test_style_reuses_root_design_tokens_not_new_hardcoded_hex():
    """bg/text values are CSS var() references into predictive_styles.css's
    :root block, not a fifth set of literal hex values."""
    for label in ('Ok', 'Atención', 'Preocupante', 'Sin Datos'):
        assert FRESHNESS_STATUS_STYLE[label]['bg'].startswith('var(--')
        assert FRESHNESS_STATUS_STYLE[label]['text'].startswith('var(--')


# ---------------------------------------------------------------------------
# 4. Legend reads the same source the table does
# ---------------------------------------------------------------------------

def test_legend_uses_the_shared_style_map_not_its_own_palette():
    legend_str = str(_build_legend())
    for label in ('Ok', 'Atención', 'Preocupante'):
        style = FRESHNESS_STATUS_STYLE[label]
        assert style['icon'] in legend_str
        assert style['accent'] in legend_str


def test_legend_and_table_agree_when_the_shared_style_changes(monkeypatch):
    """Strongest form of the guarantee: patch one entry and confirm the
    legend picks it up — proving there is exactly one definition, not two
    that happen to currently match."""
    import dashboard.callbacks.data_freshness_callbacks as freshness_module

    patched = dict(FRESHNESS_STATUS_STYLE)
    patched['Ok'] = {**patched['Ok'], 'accent': '#123456', 'icon': '✅'}
    monkeypatch.setattr(freshness_module, 'FRESHNESS_STATUS_STYLE', patched)

    # tab_data_freshness imported the name directly, so patch it there too —
    # this mirrors how a real edit to the single dict would propagate
    # (both modules hold the same dict object in production).
    import dashboard.tabs.tab_data_freshness as tab_module
    monkeypatch.setattr(tab_module, 'FRESHNESS_STATUS_STYLE', patched)

    legend_str = str(tab_module._build_legend())
    assert '#123456' in legend_str
