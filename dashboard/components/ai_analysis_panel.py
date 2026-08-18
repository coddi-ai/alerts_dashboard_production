"""
Shared "Analisis Inteligente" panel.

Extracted from the Diagnostico / Causa probable / Accion layout used in
Alertas -> Detalle (dashboard/callbacks/alerts_callbacks.py::_alert_case_header)
so AI-generated diagnosis text is styled the same everywhere it appears.
"""

import json

import dash_bootstrap_components as dbc
import pandas as pd
from dash import html


def _parse_acciones(acciones) -> list:
    """Normalize `acciones` (JSON-array string, list, or None/NaN) to a list of strings."""
    if acciones is None or (isinstance(acciones, float) and pd.isna(acciones)):
        return []
    if isinstance(acciones, list):
        return [str(a).strip() for a in acciones if str(a).strip()]
    if isinstance(acciones, str):
        text = acciones.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return [text]
        if isinstance(parsed, list):
            return [str(a).strip() for a in parsed if str(a).strip()]
        return [str(parsed).strip()]
    return [str(acciones).strip()]


def create_ai_analysis_panel(diagnostico, causa_probable, acciones, header_text="Analisis Inteligente"):
    """
    Build the "Analisis Inteligente" card: Diagnostico / Causa probable / Acciones.

    `acciones` is parsed from a JSON-array string (or accepted as a list
    already) and rendered as a bullet list instead of raw text.
    """

    def _text_block(title, value, icon):
        text = value if (value and str(value).strip()) else "No disponible"
        return dbc.Col([
            html.Div([
                html.H6([html.I(className=f"fas {icon} me-2"), title], className="mb-2"),
                html.P(text, className="mb-0", style={"whiteSpace": "pre-wrap", "lineHeight": "1.5"}),
            ], className="p-3 bg-light rounded h-100")
        ], md=4)

    actions = _parse_acciones(acciones)
    if actions:
        actions_body = html.Ul(
            [html.Li(action, style={"marginBottom": "4px"}) for action in actions],
            className="mb-0 ps-3",
        )
    else:
        actions_body = html.P("No disponible", className="mb-0")

    actions_block = dbc.Col([
        html.Div([
            html.H6([html.I(className="fas fa-wrench me-2"), "Acciones"], className="mb-2"),
            actions_body,
        ], className="p-3 bg-light rounded h-100")
    ], md=4)

    return dbc.Card([
        dbc.CardBody([
            html.H5([html.I(className="fas fa-brain me-2"), header_text],
                    className="text-primary mb-3 pb-2 border-bottom"),
            dbc.Row([
                _text_block("Diagnostico", diagnostico, "fa-search"),
                _text_block("Causa probable", causa_probable, "fa-project-diagram"),
                actions_block,
            ], className="g-3"),
        ])
    ], className="shadow-sm", style={"borderTop": "3px solid #3498db"})
