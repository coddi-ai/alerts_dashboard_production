# UI/UX Design Guide - Multi-Technical Alerts Dashboard

**Version:** 2.1.1  
**Last Updated:** July 2026  
**Purpose:** Reference guide for replicating dashboard aesthetics in other projects
 
---

## 📐 Design Philosophy

The dashboard follows a **professional, data-driven design** with these core principles:

- **Clarity First**: Information hierarchy is clear, with prominent headers and structured sections
- **Visual Consistency**: Repeated patterns for cards, headers, and sections
- **Semantic Colors**: Colors convey meaning (red=danger/alerts, blue=info, green=success, yellow=warning)
- **Spacious Layout**: Generous padding and margins prevent visual clutter
- **Icon-Driven Navigation**: FontAwesome icons enhance recognition and scannability
- **Bootstrap-Native**: Leverages Bootstrap 5 components for professional appearance

---

## 🎨 Color Palette

### Primary Colors
```css
/* Primary (Blue) - Main brand color for headers and primary actions */
--bs-primary: #007bff;
--bs-primary-light: #3498db;
--bs-primary-hover: rgba(52, 152, 219, 0.2);

/* Danger (Red) - Alerts and critical metrics */
--bs-danger: #dc3545;
--danger-bg: #fff5f5;

/* Success (Green) - Positive metrics and confirmations */
--bs-success: #28a745;
--success-bg: #f0fff4;

/* Warning (Yellow/Orange) - Caution and attention items */
--bs-warning: #ffc107;
--warning-bg: #fffcf0;

/* Info (Light Blue) - Informational metrics */
--bs-info: #17a2b8;
--info-bg: #f0f8ff;
```

### Neutral Colors
```css
/* Text and borders */
--text-primary: #1a252f;
--text-muted: #6c757d;
--border-color: #dee2e6;
--bg-light: #f8f9fa;
--bg-white: #ffffff;
```

### Card Background Colors (Semantic KPI Cards)
```css
/* Each KPI card uses a subtle tinted background */
.card-danger-tint { background-color: #fff5f5; }  /* Total Alerts */
.card-info-tint { background-color: #f0f8ff; }    /* Affected Units */
.card-success-tint { background-color: #f0fff4; } /* Telemetry Coverage */
.card-warning-tint { background-color: #fffcf0; } /* Oil Analysis */
```

---

## 🏗️ Layout Structure

### Page Container
```python
html.Div([
    # Content here
], className="container-fluid p-4")
```

### Standard Page Header
```python
html.Div([
    html.H3([
        html.I(className="fas fa-microscope me-2"),
        "Análisis Detallado de Alerta"
    ], className="text-primary mb-2"),
    html.P("Explore evidencia completa de telemetría, tribología y mantenimiento", 
           className="text-muted")
], className="mb-4")
```

**Key Elements:**
- H3 for main page title with icon
- Blue primary color for emphasis
- Subtitle in muted text
- Bottom margin of 4 units

---

## 📦 Card Components

### Standard Card Structure
```python
dbc.Card([
    dbc.CardHeader([
        html.H5([
            html.I(className="fas fa-filter me-2"),
            "Filtros de Búsqueda"
        ], className="mb-0")
    ], className="bg-light"),
    dbc.CardBody([
        # Card content here
    ])
], className="shadow-sm mb-4")
```

**Styling Convention:**
- `shadow-sm`: Subtle shadow for depth
- `mb-4`: Bottom margin for spacing between cards
- `bg-light`: Light gray background for headers
- Icons in headers for visual recognition

### Card Header Variants

**Light Header (Default)**
```python
dbc.CardHeader([
    html.H5([
        html.I(className="fas fa-truck me-2"),
        "Distribución por Unidad"
    ], className="mb-0")
], className="bg-light")
```

**Primary Header (Important Sections)**
```python
dbc.CardHeader([
    html.H5([
        html.I(className="fas fa-bullseye me-2"),
        "Selección de Alerta"
    ], className="mb-0")
], className="bg-primary text-white")
```

### Full-Height Cards (Equal Height in Rows)
```python
dbc.Card([
    # Content
], className="shadow-sm mb-4 h-100")  # h-100 ensures equal height
```

---

## 📊 Section Headers (Evidence Sections)

This is the **signature pattern** used for "Evidencia de Telemetría", "Evidencia Tribológica", etc.

```python
html.Div([
    html.H4([
        html.I(className="fas fa-signal me-2"),
        "Evidencia de Telemetría"
    ], className="text-primary mb-3 mt-4 pb-2 border-bottom"),
    html.P("Análisis de datos de sensores y ubicación GPS durante el evento", 
           className="text-muted mb-3")
])
```

**Key Features:**
- **H4 heading** with icon
- `text-primary`: Blue color for prominence
- `mb-3 mt-4 pb-2 border-bottom`: Creates visual separator line
- Descriptive subtitle in muted text

**Visual Effect:**
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📡 Evidencia de Telemetría
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Análisis de datos de sensores y ubicación GPS durante el evento
```

### Other Section Header Examples

**Análisis de Alertas**
```python
html.Div([
    html.H4([
        html.I(className="fas fa-chart-bar me-2"),
        "Análisis de Alertas"
    ], className="text-primary mb-3 mt-4")
])
```

**Listado de Alertas**
```python
html.Div([
    html.H4([
        html.I(className="fas fa-database me-2"),
        "Listado de Alertas"
    ], className="text-primary mb-3 mt-4")
])
```

**Evidencia Tribológica**
```python
html.Div([
    html.H4([
        html.I(className="fas fa-oil-can me-2"),
        "Evidencia Tribológica"
    ], className="text-primary mb-3 mt-4 pb-2 border-bottom"),
    html.P("Análisis de aceite y desgaste de componentes", 
           className="text-muted mb-3")
])
```

---

## 🎯 Icons (FontAwesome 5)

Icons are used **consistently** throughout the dashboard to improve scannability.

### Common Icon Mappings

| Context | Icon Class | Visual |
|---------|-----------|---------|
| Alerts | `fas fa-exclamation-triangle` | ⚠️ |
| Telemetry/Sensors | `fas fa-signal` | 📡 |
| Oil/Tribology | `fas fa-oil-can` | 🛢️ |
| Units/Trucks | `fas fa-truck` | 🚚 |
| Systems | `fas fa-cogs` | ⚙️ |
| Charts/Analytics | `fas fa-chart-bar` | 📊 |
| Charts (Line) | `fas fa-chart-line` | 📈 |
| Charts (Pie) | `fas fa-chart-pie` | 🥧 |
| Database/Lists | `fas fa-database` | 💾 |
| Tables | `fas fa-table` | 📋 |
| Filters | `fas fa-filter` | 🔍 |
| Calendar | `fas fa-calendar-alt` | 📅 |
| GPS/Location | `fas fa-map-marked-alt` | 🗺️ |
| Search | `fas fa-search` | 🔎 |
| Target/Selection | `fas fa-bullseye` | 🎯 |
| Info | `fas fa-info-circle` | ℹ️ |
| Flask/Lab | `fas fa-flask` | 🧪 |
| Microscope | `fas fa-microscope` | 🔬 |
| KPI/Speed | `fas fa-tachometer-alt` | ⏱️ |
| Sync/Refresh | `fas fa-sync-alt` | 🔄 |

### Icon Usage Pattern
```python
html.I(className="fas fa-icon-name me-2")
```
- `me-2`: Right margin of 2 units (spacing between icon and text)
- For larger icons: `fa-2x`, `fa-3x`
- For colored icons: Add `text-{color}` class

**Example:**
```python
html.I(className="fas fa-exclamation-triangle fa-2x text-danger mb-2")
```

---

## ✍️ Typography

### Heading Hierarchy

```python
# Page Title (H2)
html.H2([
    html.I(className="fas fa-oil-can me-3"),
    "Monitor de Aceite"
], className="text-primary mb-1")

# Section Header (H3)
html.H3([
    html.I(className="fas fa-microscope me-2"),
    "Análisis Detallado de Alerta"
], className="text-primary mb-2")

# Subsection Header (H4)
html.H4([
    html.I(className="fas fa-chart-bar me-2"),
    "Análisis de Alertas"
], className="text-primary mb-3 mt-4")

# Card Header (H5)
html.H5([
    html.I(className="fas fa-truck me-2"),
    "Distribución por Unidad"
], className="mb-0")

# Small Labels (H6)
html.H6("Total de Alertas", 
        className="text-muted text-uppercase mb-2",
        style={'fontSize': '0.85rem', 'letterSpacing': '0.5px'})
```

### Text Styles

```python
# Primary text
"text-primary"

# Muted/secondary text
"text-muted"

# Uppercase labels (KPI cards)
"text-uppercase"

# Bold text
"fw-bold"

# Medium weight
"fw-500"

# Center aligned
"text-center"
```

---

## 📏 Spacing System (Bootstrap 5)

The dashboard uses Bootstrap's spacing utilities consistently.

### Margin Classes
```css
.m-0   /* margin: 0 */
.mt-1  /* margin-top: 0.25rem */
.mt-2  /* margin-top: 0.5rem */
.mt-3  /* margin-top: 1rem */
.mt-4  /* margin-top: 1.5rem */
.mb-2  /* margin-bottom: 0.5rem */
.mb-3  /* margin-bottom: 1rem */
.mb-4  /* margin-bottom: 1.5rem */
.me-2  /* margin-right: 0.5rem (for icons) */
.me-3  /* margin-right: 1rem */
```

### Padding Classes
```css
.p-0   /* padding: 0 */
.p-2   /* padding: 0.5rem */
.p-3   /* padding: 1rem */
.p-4   /* padding: 1.5rem */
```

### Common Combinations
```python
className="mb-4"           # Standard card spacing
className="mb-3 mt-4"      # Section header spacing
className="mb-0"           # Remove default heading margin
className="g-3"            # Row gap spacing (Bootstrap 5)
```

---

## 🔘 Buttons and Interactive Elements

### Primary Button
```python
dbc.Button(
    [
        html.I(className="fas fa-sign-in-alt me-2"),
        "Iniciar Sesión"
    ],
    id='login-button',
    color='primary',
    size="lg",
    className='w-100',
    style={'fontWeight': '600'}
)
```

### Button Hover Effects (CSS)
```css
#login-button:hover {
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
    transition: all 0.2s ease;
}

#login-button:active {
    transform: translateY(0);
}
```

---

## 📋 Tables (DataTable)

### Standard DataTable Styling
```python
dash_table.DataTable(
    id='alerts-datatable',
    columns=[...],
    data=data,
    style_table={
        'overflowX': 'auto',
        'overflowY': 'auto',
        'maxHeight': '500px'
    },
    style_cell={
        'textAlign': 'left',
        'padding': '10px',
        'fontFamily': 'Arial, sans-serif',
        'fontSize': '14px',
        'minWidth': '100px',
        'maxWidth': '400px',
        'whiteSpace': 'normal',
        'height': 'auto'
    },
    style_header={
        'backgroundColor': '#2c3e50',
        'color': 'white',
        'fontWeight': 'bold',
        'textAlign': 'center'
    },
    style_data_conditional=[
        {
            'if': {'row_index': 'odd'},
            'backgroundColor': '#f8f9fa'
        },
        {
            'if': {'state': 'active'},
            'backgroundColor': '#3498db',
            'color': 'white',
            'border': '2px solid #2980b9',
            'cursor': 'pointer'
        }
    ],
    filter_action='native',
    sort_action='native',
    page_size=20
)
```

**Key Features:**
- Dark header (`#2c3e50`)
- Zebra striping for rows
- Active row highlighting in blue
- Responsive overflow handling

---

## 📊 Summary Statistics Cards

This is the **KPI card pattern** used for executive summaries.

```python
def create_summary_stats_display(total_alerts, total_units, telemetry_pct, oil_pct):
    return html.Div([
        # Section Header
        html.Div([
            html.H4([
                html.I(className="fas fa-chart-line me-2"),
                "Resumen Ejecutivo"
            ], className="text-primary mb-3")
        ]),
        
        # KPI Cards Row
        dbc.Row([
            # Total Alerts - Danger metric
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.Div([
                            html.I(className="fas fa-exclamation-triangle fa-2x text-danger mb-2"),
                            html.H6("Total de Alertas", 
                                   className="text-muted text-uppercase mb-2", 
                                   style={'fontSize': '0.85rem', 'letterSpacing': '0.5px'}),
                            html.H2(f"{total_alerts:,}", 
                                   className="text-danger mb-0 fw-bold")
                        ], className="text-center")
                    ])
                ], className="shadow-sm border-0", 
                   style={'backgroundColor': '#fff5f5'})
            ], md=3),
            
            # Affected Units - Info metric
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.Div([
                            html.I(className="fas fa-truck fa-2x text-info mb-2"),
                            html.H6("Unidades Afectadas",
                                   className="text-muted text-uppercase mb-2",
                                   style={'fontSize': '0.85rem', 'letterSpacing': '0.5px'}),
                            html.H2(f"{total_units}", 
                                   className="text-info mb-0 fw-bold")
                        ], className="text-center")
                    ])
                ], className="shadow-sm border-0", 
                   style={'backgroundColor': '#f0f8ff'})
            ], md=3),
            
            # Telemetry Coverage - Success metric
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.Div([
                            html.I(className="fas fa-signal fa-2x text-success mb-2"),
                            html.H6("Con Telemetría",
                                   className="text-muted text-uppercase mb-2",
                                   style={'fontSize': '0.85rem', 'letterSpacing': '0.5px'}),
                            html.H2(f"{telemetry_pct:.1f}%", 
                                   className="text-success mb-0 fw-bold")
                        ], className="text-center")
                    ])
                ], className="shadow-sm border-0", 
                   style={'backgroundColor': '#f0fff4'})
            ], md=3),
            
            # Oil Coverage - Warning metric
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.Div([
                            html.I(className="fas fa-oil-can fa-2x text-warning mb-2"),
                            html.H6("Con Tribología",
                                   className="text-muted text-uppercase mb-2",
                                   style={'fontSize': '0.85rem', 'letterSpacing': '0.5px'}),
                            html.H2(f"{oil_pct:.1f}%", 
                                   className="text-warning mb-0 fw-bold")
                        ], className="text-center")
                    ])
                ], className="shadow-sm border-0", 
                   style={'backgroundColor': '#fffcf0'})
            ], md=3)
        ], className="g-3 mb-4")
    ])
```

**KPI Card Anatomy:**
1. **Large colored icon** (`fa-2x`) at top
2. **Small uppercase label** in muted gray
3. **Large bold number** in semantic color
4. **Subtle tinted background** matching the metric color
5. **No border** (`border-0`) with subtle shadow
6. **Centered content** (`text-center`)

---

## 🧭 Navigation

### Sidebar Menu Item (Active State)
```css
.nav-menu-item:hover {
    background-color: rgba(52, 152, 219, 0.2) !important;
    color: #3498db !important;
    transform: translateX(4px);
}

.nav-menu-item.active {
    background-color: rgba(52, 152, 219, 0.3) !important;
    color: #3498db !important;
    font-weight: 600 !important;
    border-left: 3px solid #3498db;
}

.nav-menu-item {
    transition: all 0.2s ease;
}
```

### Custom Tabs (Internal Navigation)
```css
.custom-tab {
    background-color: #f8f9fa;
    border: 1px solid #dee2e6;
    border-bottom: none;
    padding: 12px 24px;
    font-weight: 500;
    color: #6c757d;
    cursor: pointer;
    transition: all 0.3s ease;
}

.custom-tab:hover {
    background-color: #e9ecef;
    color: #495057;
}

.custom-tab--selected {
    background-color: #ffffff;
    border: 1px solid #dee2e6;
    border-bottom: 2px solid #007bff;
    color: #007bff;
    font-weight: 600;
}
```

**Usage:**
```python
dcc.Tabs(
    id='oil-internal-tabs',
    value='fleet-overview',
    children=[
        dcc.Tab(
            label='Visión de Flota',
            value='fleet-overview',
            className='custom-tab',
            selected_className='custom-tab--selected'
        ),
        dcc.Tab(
            label='Detalle de Reporte',
            value='report-detail',
            className='custom-tab',
            selected_className='custom-tab--selected'
        )
    ],
    className='mb-4'
)
```

### 🔗 URL Routing (Dash Pages) — updated July 2026

Top-level navigation used to be a single URL with a nav-button click callback swapping content into `section-content`. It's now **Dash Pages**: every sidebar section has its own bookmarkable, shareable URL, and content is dispatched by `dash.page_container` based on the browser's current path — no click callback involved.

**URL scheme:**

| Section | Path |
|---|---|
| Resumen — General | `/overview/general` |
| Resumen — Estado de Datos | `/overview/data-freshness` |
| Monitoreo — Alertas | `/monitoring/alerts` |
| Monitoreo — Telemetría | `/monitoring/telemetry` |
| Monitoreo — Aceite | `/monitoring/oil` |
| Predictivo — Motor | `/predictive/motor` |
| Predictivo — Transmisión | `/predictive/transmision` |
| Agentes — Campbell AI | `/agents/campbell-ai` |
| Conexión ERP — Validación de Avisos | `/integration/validacion-avisos` |
| Conexión ERP — Seguimiento de Avisos | `/integration/seguimiento-avisos` |
| Reportes | `/reporting` |
| Administración | `/admin` |
| *(root)* | `/` → client-side redirect to `/overview/general` |

Paths are relative to `DASH_PATH_PREFIX` if set — always build hrefs with `dash.get_relative_path(path)` rather than a raw string.

**Sidebar links** are `dbc.NavLink`s, not `dbc.Button`s:
```python
dbc.NavLink(
    [html.I(className="fas fa-chevron-right me-2 nav-chevron"), "Alertas"],
    href=dash.get_relative_path("/monitoring/alerts"),
    active="exact",
    className="nav-menu-item text-start w-100 mb-1 px-3 py-2",
)
```
`active="exact"` compares the link's `href` to the current URL automatically — the `.nav-menu-item.active` CSS above still applies, `dbc` just adds/removes the `active` class for you. There is no callback that manually sets nav button `className` anymore.

**Registering a new page** (thin adapter, no business logic):
```python
# dashboard/pages/my_new_section.py
import dash
from dashboard.tabs.tab_my_new_section import create_layout


def layout(**kwargs):
    return create_layout()


# layout= must be passed explicitly: pages_folder="" (set in app.py) disables
# Dash's auto-discovery "plug" step, which is what normally fills page["layout"]
# in from the module's `layout` attribute.
dash.register_page(__name__, path="/my/new-section", title="My Section | Multi-Technical Alerts", layout=layout)
```
Then: (1) import the module for its `register_page()` side effect in `dashboard/app.py`, and (2) add a matching `dbc.NavLink` entry in `create_sidebar`/`create_main_dashboard` in `layout.py`.

**Auth is unchanged and sits outside the page system**: `page-content` still swaps between the login form and the full dashboard shell based on `user-info-store` (unchanged from before this migration). `dash.page_container` only lives *inside* the post-login shell — so an unauthenticated visitor never reaches page routing at all, regardless of which URL they hit.

**Pages driven by the client-selector dropdown**: a page's `layout()` function runs once per navigation and has no access to the global `client-selector` value, so any page whose content depends on the selected client needs its own reactive callback (`Input('client-selector', 'value')`) rather than relying on `layout()` alone. See `dashboard/callbacks/predictive_pages_callbacks.py` for the pattern — the page registers a placeholder container, and a single pattern-matching (`ALL`) callback fills it in and keeps it in sync when the client changes.

---

## 📱 Responsive Layout

### Grid System
```python
# Full width section
dbc.Col([...], md=12)

# Half-width sections
dbc.Row([
    dbc.Col([...], md=6),
    dbc.Col([...], md=6)
])

# Asymmetric layout (9-3 split for table + sidebar)
dbc.Row([
    dbc.Col([...], md=9),  # Main content
    dbc.Col([...], md=3)   # Sidebar
])

# Equal height cards
dbc.Row([
    dbc.Col([
        dbc.Card([...], className="shadow-sm mb-4 h-100")
    ], md=4),
    dbc.Col([
        dbc.Card([...], className="shadow-sm mb-4 h-100")
    ], md=8)
], className="gx-3")  # Horizontal gap spacing
```

---

## 🎨 Custom CSS Utilities

### Animations
```css
@keyframes fadeInUp {
    from {
        opacity: 0;
        transform: translateY(20px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}

.card {
    animation: fadeInUp 0.5s ease-out;
}
```

### Scrollbar Styling
```css
.sidebar-menu::-webkit-scrollbar {
    width: 8px;
}

.sidebar-menu::-webkit-scrollbar-track {
    background: rgba(0, 0, 0, 0.1);
    border-radius: 4px;
}

.sidebar-menu::-webkit-scrollbar-thumb {
    background: rgba(255, 255, 255, 0.2);
    border-radius: 4px;
}

.sidebar-menu::-webkit-scrollbar-thumb:hover {
    background: rgba(255, 255, 255, 0.3);
}
```

---

## 📦 Complete Component Examples

### Filter Section with Icons
```python
dbc.Card([
    dbc.CardHeader([
        html.H5([
            html.I(className="fas fa-filter me-2"),
            "Filtros de Búsqueda"
        ], className="mb-0")
    ], className="bg-light"),
    dbc.CardBody([
        dbc.Row([
            dbc.Col([
                html.Label([
                    html.I(className="fas fa-truck me-1"),
                    "Unidad"
                ], className="fw-bold mb-2"),
                dcc.Dropdown(
                    id='detail-filter-unit',
                    placeholder="Todas las unidades...",
                    clearable=True,
                    searchable=True,
                    multi=True
                )
            ], md=3),
            
            dbc.Col([
                html.Label([
                    html.I(className="fas fa-cogs me-1"),
                    "Sistema"
                ], className="fw-bold mb-2"),
                dcc.Dropdown(
                    id='detail-filter-sistema',
                    placeholder="Todos los sistemas...",
                    clearable=True,
                    multi=True
                )
            ], md=3)
        ], className="g-3")
    ])
], className="shadow-sm mb-4")
```

### Chart Card
```python
dbc.Card([
    dbc.CardHeader([
        html.H5([
            html.I(className="fas fa-chart-line me-2"),
            "Tendencias de Sensores"
        ], className="mb-0")
    ], className="bg-light"),
    dbc.CardBody([
        dcc.Loading(
            id="loading-sensor-trends",
            type="circle",
            children=[
                dcc.Graph(
                    id='sensor-trends-chart',
                    config={'displayModeBar': True}
                )
            ]
        )
    ])
], className="shadow-sm mb-4")
```

### Alert Banner
```python
dbc.Alert([
    html.I(className="fas fa-arrow-up me-2"),
    "Por favor, seleccione una alerta para ver los detalles"
], color="info", className="text-center")
```

### Info Tooltip
```python
html.Small([
    html.I(className="fas fa-info-circle me-1"),
    "💡 Haga clic en cualquier fila para ver el análisis detallado"
], className="text-muted")
```

---

## 🔑 Key Takeaways

### Essential Patterns to Replicate

1. **Section Evidence Headers**: Use H4 with icon, blue color, border-bottom, and descriptive subtitle
2. **KPI Cards**: Large icon, small uppercase label, big bold number, tinted background
3. **Card Structure**: Always use `shadow-sm mb-4` for consistent depth and spacing
4. **Icons Everywhere**: Use FontAwesome icons in headers, labels, and buttons for visual recognition
5. **Semantic Colors**: Red (alerts/danger), Blue (info/primary), Green (success), Yellow (warning)
6. **Consistent Spacing**: Use Bootstrap's spacing utilities (`mb-3`, `mt-4`, `me-2`, etc.)
7. **Professional Typography**: H3 for page titles, H4 for sections, H5 for card headers
8. **Hover Effects**: Subtle transforms and color changes for interactive elements

### Bootstrap Dependencies
```python
import dash_bootstrap_components as dbc
from dash import html, dcc

# In app initialization
app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    suppress_callback_exceptions=True
)
```

### FontAwesome 5 CDN
Add to your HTML head or app assets:
```html
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.15.4/css/all.min.css">
```

---

## 📚 Additional Resources

- **Bootstrap 5 Documentation**: https://getbootstrap.com/docs/5.0/
- **Dash Bootstrap Components**: https://dash-bootstrap-components.opensource.faculty.ai/
- **FontAwesome Icons**: https://fontawesome.com/v5/search
- **Color Palette Tool**: https://coolors.co/

---

**End of Document** | For questions or clarifications, refer to the source dashboard codebase.
