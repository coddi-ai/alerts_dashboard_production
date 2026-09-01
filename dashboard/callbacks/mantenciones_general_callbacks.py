"""
Callbacks for Mantenciones General tab.
Handles data loading, KPI updates, and visualizations.
"""

from dash import callback, Output, Input, State, html
from dash.exceptions import PreventUpdate
import json
from datetime import datetime
import logging

from src.data.maintenance_repository import get_repository
from dashboard.tabs.tab_mantenciones_general import (
    create_status_donut_chart,
    create_downtime_trend_chart,
    create_system_pareto_chart,
    create_detentions_table,
    create_jobs_table,
    create_empty_figure
)

logger = logging.getLogger(__name__)


def register_mantenciones_general_callbacks(app):
    """
    Register all callbacks for Mantenciones General tab.
    
    Args:
        app: Dash application instance
    """
    
    @callback(
        Output("filter-system", "options"),
        [Input("client-selector", "value")]
    )
    def update_system_filter_options(client):
        """Populate the System filter with every system present in the client's data."""
        if not client:
            raise PreventUpdate

        try:
            repo = get_repository(mode="parquet", client=client)
            systems = repo.get_available_systems()
            return [{"label": s, "value": s} for s in systems]
        except Exception as e:
            logger.error(f"Error loading system filter options: {e}")
            return []

    @callback(
        [
            Output("filter-equipment", "options"),
            Output("filter-equipment", "value"),
        ],
        [
            Input("filter-system", "value"),
            Input("client-selector", "value"),
        ],
        [State("filter-equipment", "value")]
    )
    def update_equipment_filter_options(selected_systems, client, current_equipment):
        """
        Populate the Equipment filter, cascading on the System selection: with
        systems selected, only machines with at least one action on those
        systems are offered. Any previously-selected machine that falls out
        of the new option set is dropped instead of left as a stale value.
        """
        if not client:
            raise PreventUpdate

        try:
            repo = get_repository(mode="parquet", client=client)
            equipment = repo.get_available_equipment(systems=selected_systems or None)
        except Exception as e:
            logger.error(f"Error loading equipment filter options: {e}")
            return [], None

        options = [{"label": code, "value": code} for code in equipment]
        valid_values = set(equipment)
        new_value = [v for v in (current_equipment or []) if v in valid_values] or None
        return options, new_value

    @callback(
        [
            Output("store-general-data", "data"),
            Output("store-general-timestamp", "data"),
            Output("store-general-loaded", "data"),
        ],
        [
            Input("btn-refresh-general", "n_clicks"),
            Input("store-general-loaded", "data"),
            Input("client-selector", "value"),
            Input("filter-date-range", "start_date"),
            Input("filter-date-range", "end_date"),
            Input("filter-system", "value"),
            Input("filter-equipment", "value"),
        ],
        prevent_initial_call=False
    )
    def load_general_data(n_clicks, loaded, client, date_start, date_end, systems, equipment):
        """
        Load all data for the general view.
        Triggered by refresh button, initial page load, or any filter change.
        """
        if not client:
            raise PreventUpdate

        try:
            logger.info(
                f"Loading mantenciones general data for client: {client}... "
                f"(n_clicks={n_clicks}, loaded={loaded}, systems={systems}, equipment={equipment}, "
                f"date_start={date_start}, date_end={date_end})"
            )

            # Get repository (using parquet mode for real data) - MUST pass client parameter
            repo = get_repository(mode="parquet", client=client)

            # Get period info
            period_info = repo.get_data_period_info()

            # Load all datasets. Status KPIs are real-time (not historical),
            # so they respond to System/Equipment but deliberately not to the
            # date-range filter - see MaintenanceRepository.get_status_counts.
            df_status = repo.get_status_counts(systems=systems, equipment=equipment)
            df_downtime_mtd = repo.get_downtime_mtd(
                systems=systems, equipment=equipment, date_start=date_start, date_end=date_end
            )
            df_last_detentions = repo.get_last_detentions(
                n_per_machine=1, systems=systems, equipment=equipment,
                date_start=date_start, date_end=date_end
            )  # Solo el último periodo por equipo
            df_jobs_last_week = repo.get_jobs_last_week(
                systems=systems, equipment=equipment, date_start=date_start, date_end=date_end
            )
            df_downtime_by_day = repo.get_downtime_by_day_mtd(
                systems=systems, equipment=equipment, date_start=date_start, date_end=date_end
            )
            df_by_system = repo.get_maintenance_by_system(
                systems=systems, equipment=equipment, date_start=date_start, date_end=date_end
            )

            # Convert to JSON-serializable format
            data = {
                "status": df_status.to_dict("records"),
                "downtime_mtd": df_downtime_mtd.to_dict("records"),
                "last_detentions": df_last_detentions.to_dict("records"),
                "jobs_last_week": df_jobs_last_week.to_dict("records"),
                "downtime_by_day": df_downtime_by_day.to_dict("records"),
                "by_system": df_by_system.to_dict("records"),
                "period_info": period_info,  # Información del período
            }
            
            timestamp = datetime.now().isoformat()
            
            logger.info("Data loaded successfully")
            return data, timestamp, True
            
        except Exception as e:
            logger.error(f"Error loading mantenciones general data: {e}", exc_info=True)
            return {}, None, False
    
    @callback(
        [
            Output("kpi-equipos-totales", "children"),
            Output("kpi-equipos-sanos", "children"),
            Output("kpi-equipos-detenidos", "children"),
            Output("kpi-horas-detenidas-mtd", "children"),
            Output("kpi-horas-detenidas-label", "children"),
        ],
        [Input("store-general-data", "data")]
    )
    def update_kpis(data):
        """Update KPI cards with loaded data and period info."""
        if not data or not data.get("status"):
            return "0", "0", "0", "0", "Horas Detenidas"
        
        try:
            # Parse status counts
            status_data = data["status"]
            sanos = next((item["n_machines"] for item in status_data if item["machine_status"] == "SANO"), 0)
            detenidos = next((item["n_machines"] for item in status_data if item["machine_status"] == "DETENIDO"), 0)
            total = sanos + detenidos
            
            # Parse downtime MTD
            downtime_mtd = data.get("downtime_mtd", [{}])[0].get("total_downtime_hours_mtd", 0)
            downtime_str = f"{downtime_mtd:.1f}"
            
            # Get period label
            period_info = data.get("period_info", {})
            period_label = period_info.get("period_label", "Período")
            kpi_label = f"Horas Detenidas - {period_label}"
            
            return str(total), str(sanos), str(detenidos), downtime_str, kpi_label
            
        except Exception as e:
            logger.error(f"Error updating KPIs: {e}")
            return "Error", "Error", "Error", "Error", "Horas Detenidas"
    
    @callback(
        Output("chart-status-distribution", "figure"),
        [Input("store-general-data", "data")]
    )
    def update_status_chart(data):
        """Update status distribution donut chart."""
        if not data or not data.get("status"):
            return create_empty_figure("No hay datos de estado disponibles")
        
        try:
            import pandas as pd
            df_status = pd.DataFrame(data["status"])
            return create_status_donut_chart(df_status)
        except Exception as e:
            logger.error(f"Error updating status chart: {e}")
            return create_empty_figure("Error al cargar gráfico")
    
    @callback(
        Output("chart-downtime-trend", "figure"),
        [Input("store-general-data", "data")]
    )
    def update_downtime_trend(data):
        """Update downtime trend line chart with period info."""
        if not data or not data.get("downtime_by_day"):
            return create_empty_figure("No hay datos de tendencia disponibles")
        
        try:
            import pandas as pd
            df_trend = pd.DataFrame(data["downtime_by_day"])
            
            # Get period label if available
            period_label = data.get("period_info", {}).get("period_label", "Período")
            
            return create_downtime_trend_chart(df_trend, period_label)
        except Exception as e:
            logger.error(f"Error updating downtime trend: {e}")
            return create_empty_figure("Error al cargar gráfico")
    
    @callback(
        Output("chart-system-pareto", "figure"),
        [Input("store-general-data", "data")]
    )
    def update_system_pareto_chart(data):
        """Update maintenance-by-system Pareto chart."""
        if not data or not data.get("by_system"):
            return create_empty_figure("No hay datos de sistemas disponibles")

        try:
            import pandas as pd
            df_by_system = pd.DataFrame(data["by_system"])
            return create_system_pareto_chart(df_by_system)
        except Exception as e:
            logger.error(f"Error updating system pareto chart: {e}")
            return create_empty_figure("Error al cargar gráfico")

    @callback(
        Output("table-last-detentions", "children"),
        [Input("store-general-data", "data")]
    )
    def update_detentions_table(data):
        """Update last detentions table."""
        if not data or not data.get("last_detentions"):
            return html.P("No hay datos de detenciones disponibles", 
                         className="text-muted text-center p-3")
        
        try:
            import pandas as pd
            df_detentions = pd.DataFrame(data["last_detentions"])
            return create_detentions_table(df_detentions)
        except Exception as e:
            logger.error(f"Error updating detentions table: {e}")
            return html.P("Error al cargar tabla", className="text-danger text-center p-3")
    
    @callback(
        Output("table-jobs-last-week", "children"),
        [Input("store-general-data", "data")]
    )
    def update_jobs_table(data):
        """Update jobs last week table."""
        if not data or not data.get("jobs_last_week"):
            return html.P("No hay trabajos registrados en la última semana", 
                         className="text-muted text-center p-3")
        
        try:
            import pandas as pd
            df_jobs = pd.DataFrame(data["jobs_last_week"])
            return create_jobs_table(df_jobs)
        except Exception as e:
            logger.error(f"Error updating jobs table: {e}")
            return html.P("Error al cargar tabla", className="text-danger text-center p-3")
    
    @callback(
        Output("text-last-update", "children"),
        [Input("store-general-timestamp", "data")]
    )
    def update_timestamp(timestamp):
        """Update last update timestamp."""
        if not timestamp:
            return "N/A"
        
        try:
            dt = datetime.fromisoformat(timestamp)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:
            logger.error(f"Error formatting timestamp: {e}")
            return "Error"
