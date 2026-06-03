"""
KPI Card Component - Following Bootstrap 5 + Design Guide Patterns
"""

from dash import html


def KPI(title, value, subtitle="", color="#2563EB", icon=None):
    """Render a modern KPI card."""
    children = []

    if icon:
        bg = color + "18"  # translucent bg
        children.append(
            html.Div(icon, className="kpi-icon",
                      style={"background": bg, "color": color})
        )

    children += [
        html.Div(title, className="kpi-title"),
        html.Div(str(value), className="kpi-value", style={"color": color}),
    ]

    if subtitle:
        children.append(html.Div(subtitle, className="kpi-sub"))

    return html.Div(children, className="kpi-card")


def create_kpi_card(
    value,
    label,
    icon_class,
    color_type="primary",
    subtitle=None
):
    """
    Create a semantic KPI card following design guide patterns.
    
    Features:
    - Large colored FontAwesome icons
    - Small uppercase labels
    - Large bold numbers
    - Tinted backgrounds matching metric colors
    
    Args:
        value: The metric value to display (number or string)
        label: Uppercase label for the metric
        icon_class: FontAwesome icon class (e.g., "fas fa-exclamation-triangle")
        color_type: One of "danger", "info", "success", "warning", "primary"
        subtitle: Optional subtitle text below the value
    
    Returns:
        html.Div: KPI card component
    """
    
    # Define color mappings
    color_config = {
        "danger": {
            "icon": "text-danger",
            "value": "text-danger",
            "bg": "kpi-card-danger"
        },
        "info": {
            "icon": "text-info",
            "value": "text-info",
            "bg": "kpi-card-info"
        },
        "success": {
            "icon": "text-success",
            "value": "text-success",
            "bg": "kpi-card-success"
        },
        "warning": {
            "icon": "text-warning",
            "value": "text-warning",
            "bg": "kpi-card-warning"
        },
        "primary": {
            "icon": "text-primary",
            "value": "text-primary",
            "bg": "kpi-card-info"
        }
    }
    
    config = color_config.get(color_type, color_config["primary"])
    
    # Format value if it's a number
    if isinstance(value, (int, float)):
        if isinstance(value, float) and value != int(value):
            formatted_value = f"{value:,.1f}".replace(",", ".")
        else:
            formatted_value = f"{int(value):,}".replace(",", ".")
    else:
        formatted_value = str(value)
    
    card_content = [
        # Large icon
        html.Div([
            html.I(className=f"{icon_class} kpi-icon-large {config['icon']}")
        ], className="text-center"),
        
        # Small uppercase label
        html.H6(
            label,
            className="kpi-label-small text-center mb-2"
        ),
        
        # Large bold value
        html.H2(
            formatted_value,
            className=f"kpi-value-large {config['value']} text-center mb-0 fw-bold"
        )
    ]
    
    # Add optional subtitle
    if subtitle:
        card_content.append(
            html.Div(
                subtitle,
                className="text-muted text-center",
                style={"fontSize": "0.75rem", "marginTop": "0.5rem"}
            )
        )
    
    return html.Div(
        html.Div(
            card_content,
            className="text-center"
        ),
        className=f"kpi-card-enhanced {config['bg']} shadow-sm border-0"
    )


def create_kpi_row(kpi_cards):
    """
    Create a responsive row of KPI cards.
    
    Args:
        kpi_cards: List of KPI card components
    
    Returns:
        html.Div: Grid container with KPI cards
    """
    return html.Div(
        kpi_cards,
        className="kpi-row",
        style={"marginBottom": "1.5rem"}
    )
