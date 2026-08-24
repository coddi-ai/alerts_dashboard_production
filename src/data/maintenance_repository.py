"""
Repository layer for Mantenciones General dashboard.
Provides data access functions that can work in dummy or production mode.
"""

import pandas as pd
from datetime import datetime, timedelta
from typing import Optional
import logging

from src.data.dummy_generator import generate_dummy_tables
from src.data.loaders import (
    load_maintenance_actions_all_equipment,
    load_business_kpis
)

logger = logging.getLogger(__name__)


class MaintenanceRepository:
    """Repository for maintenance data access."""
    
    def __init__(self, mode="dummy", client="cda"):
        """
        Initialize repository.
        
        Args:
            mode: "dummy" for in-memory data, "parquet" for parquet files, "prod" for database queries
            client: Client name (e.g., "cda", "emin") for data filtering
        """
        self.mode = mode
        self.client = client.lower()  # Normalize to lowercase
        self._dummy_cache = None
        self._parquet_cache = None
        self._parquet_actions_cache = None
        self._parquet_kpis_cache = None

    def _get_parquet_actions(self):
        """Load detailed actions only when a caller actually needs them."""
        if self._parquet_actions_cache is None:
            logger.info(
                "Loading maintenance actions from parquet files for client: %s",
                self.client,
            )
            self._parquet_actions_cache = load_maintenance_actions_all_equipment(
                client=self.client
            )
        return self._parquet_actions_cache

    def _get_parquet_kpis(self):
        """Load the small KPI source independently from detailed actions."""
        if self._parquet_kpis_cache is None:
            logger.info(
                "Loading maintenance KPIs from parquet files for client: %s",
                self.client,
            )
            self._parquet_kpis_cache = load_business_kpis(client=self.client)
        return self._parquet_kpis_cache
        
    def _get_dummy_data(self):
        """Get or generate dummy data."""
        if self._dummy_cache is None:
            logger.info("Generating dummy maintenance data...")
            self._dummy_cache = generate_dummy_tables()
        return self._dummy_cache
    
    def _get_parquet_data(self):
        """Get or load parquet data."""
        if self._parquet_cache is None:
            self._parquet_cache = {
                "actions": self._get_parquet_actions(),
                "kpis": self._get_parquet_kpis(),
            }
        return self._parquet_cache
    
    def get_data_period_info(self) -> dict:
        """
        Get information about the period covered by the data.
        
        Returns:
            Dictionary with keys: period_start, period_end, period_label
        """
        if self.mode == "parquet":
            data = self._get_parquet_data()
            df_actions = data["actions"]
            
            if df_actions.empty:
                return {
                    "period_start": None,
                    "period_end": None,
                    "period_label": "Sin datos"
                }
            
            latest_date = df_actions['change_date'].max()
            if pd.isna(latest_date):
                return {
                    "period_start": None,
                    "period_end": None,
                    "period_label": "Sin datos"
                }
            
            # Usar el año y mes de la última fecha disponible
            latest_year = latest_date.year
            latest_month = latest_date.month
            
            month_start = datetime(latest_year, latest_month, 1)
            
            # Nombre del mes en español
            meses = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
                    'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
            month_name = meses[latest_month - 1]
            
            return {
                "period_start": month_start,
                "period_end": latest_date,
                "period_label": f"{month_name} {latest_year}"
            }
        else:
            now = datetime.now()
            return {
                "period_start": datetime(now.year, now.month, 1),
                "period_end": now,
                "period_label": "Mes Actual"
            }
    
    def get_status_counts(self, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None) -> pd.DataFrame:
        """
        Get count of machines by status (SANO vs DETENIDO).
        
        Args:
            start_date: Start date for filtering
            end_date: End date for filtering
            
        Returns:
            DataFrame with columns: machine_status, n_machines
        """
        if self.mode == "dummy":
            data = self._get_dummy_data()
            df_machines = data["machines"]
            df_records = data["records"]
            
            # Determinar qué máquinas están detenidas (tienen records ongoing)
            detenidos = df_records[df_records["ongoing"] == True]["machine_id"].unique()
            
            status_data = [
                {"machine_status": "DETENIDO", "n_machines": len(detenidos)},
                {"machine_status": "SANO", "n_machines": len(df_machines) - len(detenidos)},
            ]
            return pd.DataFrame(status_data)
        
        elif self.mode == "parquet":
            # General only needs the compact KPI source for this operation;
            # do not parse the detailed action history on the login path.
            df_kpis = self._get_parquet_kpis()
            
            if df_kpis.empty:
                return pd.DataFrame([
                    {"machine_status": "DETENIDO", "n_machines": 0},
                    {"machine_status": "SANO", "n_machines": 0}
                ])
            
            # Usar equipment_status de query_4
            # equipment_status = 'OPERATIVO' significa SANO
            # Si tiene has_ongoing_maintenance = True, está DETENIDO
            
            # Contar máquinas por status
            # Por ahora todos están como OPERATIVO según los datos
            # Pero verificamos has_ongoing_maintenance para determinar si están detenidos
            n_detenidos = df_kpis['has_ongoing_maintenance'].sum() if 'has_ongoing_maintenance' in df_kpis.columns else 0
            total_machines = len(df_kpis)
            n_sanos = total_machines - n_detenidos
            
            logger.info(f"Status count - Total machines: {total_machines}, Detenidos: {n_detenidos}, Sanos: {n_sanos}")
            
            status_data = [
                {"machine_status": "DETENIDO", "n_machines": int(n_detenidos)},
                {"machine_status": "SANO", "n_machines": int(n_sanos)},
            ]
            return pd.DataFrame(status_data)
        
        else:
            # TODO: Implement SQL query for production
            raise NotImplementedError("Production mode not yet implemented")
    
    def get_downtime_mtd(self) -> pd.DataFrame:
        """
        Get total downtime hours for current month (Month-To-Date).
        
        Returns:
            DataFrame with column: total_downtime_hours_mtd
        """
        if self.mode == "dummy":
            data = self._get_dummy_data()
            df_records = data["records"]
            
            # Calcular MTD (Month-To-Date)
            now = datetime.now()
            month_start = datetime(now.year, now.month, 1)
            
            # Filtrar records del mes actual
            df_month = df_records[
                (df_records["start_date"] >= month_start) |
                (df_records["ongoing"] == True)
            ].copy()
            
            # Calcular horas de detención
            total_hours = 0.0
            for _, row in df_month.iterrows():
                start = row["start_date"]
                if pd.isna(start):
                    continue
                    
                # Si está ongoing, usar tiempo hasta ahora
                if row["ongoing"]:
                    end = now
                else:
                    end = row["end_date"]
                    if pd.isna(end):
                        continue
                
                # Solo contar desde inicio del mes
                effective_start = max(start, month_start)
                duration = (end - effective_start).total_seconds() / 3600
                total_hours += max(0, duration)
            
            return pd.DataFrame([{"total_downtime_hours_mtd": total_hours}])
        
        elif self.mode == "parquet":
            # Calculate MTD from the daily downtime data to ensure consistency
            df_daily = self.get_downtime_by_day_mtd()
            
            if df_daily.empty:
                return pd.DataFrame([{"total_downtime_hours_mtd": 0.0}])
            
            # Sum all daily hours for MTD total
            total_hours = df_daily['downtime_hours'].sum()
            
            logger.info(f"Total downtime MTD: {total_hours:.2f} hours (from {len(df_daily)} days)")
            return pd.DataFrame([{"total_downtime_hours_mtd": float(total_hours)}])
        
        else:
            # TODO: Implement SQL query for production
            raise NotImplementedError("Production mode not yet implemented")
    
    def get_last_detentions(self, n_per_machine: int = 3) -> pd.DataFrame:
        """
        Get last detention periods per machine.
        
        Args:
            n_per_machine: Number of last detentions per machine
            
        Returns:
            DataFrame with columns: machine_code, record_id, start_date, end_date, 
                                   ongoing, duration_hours, job_types
        """
        if self.mode == "dummy":
            data = self._get_dummy_data()
            df_machines = data["machines"]
            df_records = data["records"]
            df_jobs = data["jobs"]
            
            # Merge para obtener machine_code
            df = df_records.merge(
                df_machines[["machine_id", "machine_code"]], 
                on="machine_id"
            )
            
            # Calcular duración
            now = datetime.now()
            df["duration_hours"] = df.apply(
                lambda row: (
                    (now - row["start_date"]).total_seconds() / 3600 
                    if row["ongoing"] 
                    else (row["end_date"] - row["start_date"]).total_seconds() / 3600
                    if not pd.isna(row["end_date"])
                    else 0
                ),
                axis=1
            )
            
            # Agregar job_types por record
            job_types_by_record = df_jobs.groupby("record_id")["job_type"].apply(
                lambda x: ", ".join(x.unique())
            ).to_dict()
            
            df["job_types"] = df["record_id"].map(job_types_by_record).fillna("Sin trabajos")
            
            # Ordenar por fecha y tomar los últimos N por máquina
            df = df.sort_values("start_date", ascending=False)
            df = df.groupby("machine_code").head(n_per_machine)
            
            # Seleccionar columnas
            result = df[[
                "machine_code", "record_id", "start_date", "end_date", 
                "ongoing", "duration_hours", "job_types"
            ]].copy()
            
            return result.sort_values(["machine_code", "start_date"], ascending=[True, False])
        
        elif self.mode == "parquet":
            data = self._get_parquet_data()
            df_actions = data["actions"]
            
            if df_actions.empty:
                return pd.DataFrame(columns=[
                    "machine_code", "record_id", "start_date", "end_date",
                    "ongoing", "duration_hours", "job_types"
                ])
            
            # Filtrar registros válidos (con machine_id y record_id)
            df_valid = df_actions[
                df_actions['machine_id'].notna() & 
                df_actions['record_id'].notna()
            ].copy()
            
            if df_valid.empty:
                return pd.DataFrame(columns=[
                    "machine_code", "record_id", "start_date", "end_date",
                    "ongoing", "duration_hours", "job_types"
                ])
            
            # Agrupar por machine_id (unit_id) y record_id
            # Cada combinación representa un período de detención único
            grouped = df_valid.groupby(['machine_id', 'record_id', 'machine_code'], dropna=True)
            
            records = []
            for (machine_id, record_id, machine_code), group in grouped:
                # Usar event_ts como fecha y hora del evento (momento de la detención)
                event_datetime = pd.to_datetime(group['event_ts'].iloc[0], utc=True)
                n_actions = len(group)
                
                # Crear job_types como "accion-sistema" sin duplicados
                # Combinar action_type_name con action_system_name
                action_system_pairs = []
                for _, row in group.iterrows():
                    action_type = row.get('action_type_name', '')
                    action_system = row.get('action_system_name', '')
                    if pd.notna(action_type) and pd.notna(action_system):
                        pair = f"{action_type}-{action_system}"
                        if pair not in action_system_pairs:
                            action_system_pairs.append(pair)
                
                job_types = ", ".join(action_system_pairs) if len(action_system_pairs) > 0 else "Sin información"
                
                # Para duración, usamos el conteo de acciones como proxy
                # Cada acción representa aproximadamente 1-2 horas de trabajo
                # Esto es una estimación basada en la actividad registrada
                estimated_duration = n_actions * 1.5  # 1.5 horas por acción en promedio
                
                records.append({
                    'machine_code': machine_code,
                    'machine_id': machine_id,
                    'record_id': record_id,
                    'start_date': event_datetime,
                    'end_date': event_datetime,  # Misma fecha para registros históricos
                    'ongoing': False,  # Datos históricos
                    'duration_hours': estimated_duration,
                    'job_types': job_types,
                    'n_actions': n_actions
                })
            
            df = pd.DataFrame(records)
            
            if df.empty:
                return pd.DataFrame(columns=[
                    "machine_code", "record_id", "start_date", "end_date",
                    "ongoing", "duration_hours", "job_types"
                ])
            
            # Ordenar por fecha descendente (más reciente primero)
            df = df.sort_values("start_date", ascending=False)
            
            # Tomar los últimos N períodos de detención por equipo (machine_code)
            df = df.groupby("machine_code", dropna=True).head(n_per_machine)
            
            # Seleccionar columnas finales (sin machine_id interno)
            result = df[[
                "machine_code", "record_id", "start_date", "end_date",
                "ongoing", "duration_hours", "job_types"
            ]].copy()
            
            return result.sort_values(["machine_code", "start_date"], ascending=[True, False])
        
        else:
            # TODO: Implement SQL query for production
            raise NotImplementedError("Production mode not yet implemented")
    
    def get_jobs_last_week(self) -> pd.DataFrame:
        """
        Get jobs performed in the last week.
        
        Returns:
            DataFrame with columns: job_id, machine_code, system_name, subsystem_name,
                                   job_type, start_date, end_date, ongoing, notes
        """
        if self.mode == "dummy":
            data = self._get_dummy_data()
            df_jobs = data["jobs"]
            df_records = data["records"]
            df_machines = data["machines"]
            df_systems = data["systems"]
            df_subsystems = data["subsystems"]
            
            # Filtrar última semana
            now = datetime.now()
            week_ago = now - timedelta(days=7)
            
            df = df_jobs[df_jobs["start_date"] >= week_ago].copy()
            
            # Merge con records para obtener machine_id
            df = df.merge(df_records[["record_id", "machine_id"]], on="record_id")
            
            # Merge con machines para obtener machine_code
            df = df.merge(df_machines[["machine_id", "machine_code"]], on="machine_id")
            
            # Merge con systems
            df = df.merge(
                df_systems[["system_id", "system_name"]], 
                on="system_id", 
                how="left"
            )
            
            # Merge con subsystems
            df = df.merge(
                df_subsystems[["subsystem_id", "subsystem_name"]], 
                on="subsystem_id", 
                how="left"
            )
            
            # Seleccionar y ordenar columnas
            result = df[[
                "job_id", "machine_code", "system_name", "subsystem_name",
                "job_type", "start_date", "end_date", "ongoing", "notes"
            ]].copy()
            
            return result.sort_values("start_date", ascending=False)
        
        elif self.mode == "parquet":
            data = self._get_parquet_data()
            df_actions = data["actions"]
            
            if df_actions.empty:
                return pd.DataFrame(columns=[
                    "job_id", "machine_code", "system_name", "subsystem_name",
                    "job_type", "start_date", "end_date", "ongoing", "notes"
                ])
            
            # Filtrar últimas 10 semanas (70 días) para capturar datos históricos
            now = datetime.now()
            period_start = pd.Timestamp(now - timedelta(days=70), tz='UTC')
            
            # Filtrar por change_date
            df = df_actions[df_actions["change_date"] >= period_start].copy()
            
            # Si no hay datos en el período, usar todos los datos disponibles
            if df.empty:
                df = df_actions.copy()
            
            # Preparar datos para el formato esperado usando las columnas correctas
            result = df[[
                'job_id', 'machine_code', 'job_system_name', 'job_subsystem_name',
                'action_type_name', 'event_ts', 'action_detail_clean'
            ]].copy()
            
            # Renombrar columnas
            result = result.rename(columns={
                'job_system_name': 'system_name',
                'job_subsystem_name': 'subsystem_name',
                'action_type_name': 'job_type',
                'event_ts': 'start_date',
                'action_detail_clean': 'notes'
            })
            
            # Agregar columnas faltantes
            result["end_date"] = result["start_date"]  # Acciones instantáneas
            result["ongoing"] = False
            
            # Limitar a 100 registros más recientes
            result = result.sort_values("start_date", ascending=False).head(100)
            
            return result
        
        else:
            # TODO: Implement SQL query for production
            raise NotImplementedError("Production mode not yet implemented")
    
    def get_downtime_by_day_mtd(self) -> pd.DataFrame:
        """
        Get downtime hours by day for the most recent month with data available (MTD - Month To Date).
        If no data exists for current month, uses the last month with available data.
        
        Returns:
            DataFrame with columns: date, downtime_hours
        """
        if self.mode == "dummy":
            data = self._get_dummy_data()
            df_records = data["records"]
            
            now = datetime.now()
            month_start = datetime(now.year, now.month, 1)
            
            # Crear rango de días del mes
            days = pd.date_range(month_start, now, freq='D')
            daily_hours = []
            
            for day in days:
                day_start = day
                day_end = day + timedelta(days=1)
                
                # Filtrar records activos en este día
                df_day = df_records[
                    (df_records["start_date"] < day_end) &
                    (
                        (df_records["end_date"] >= day_start) |
                        (df_records["ongoing"] == True)
                    )
                ]
                
                # Calcular horas de detención en este día
                day_hours = 0.0
                for _, row in df_day.iterrows():
                    start = max(row["start_date"], day_start)
                    if row["ongoing"]:
                        end = min(now, day_end)
                    else:
                        end = min(row["end_date"], day_end)
                    
                    duration = (end - start).total_seconds() / 3600
                    day_hours += max(0, duration)
                
                daily_hours.append({
                    "date": day.date(),
                    "downtime_hours": day_hours
                })
            
            return pd.DataFrame(daily_hours)
        
        elif self.mode == "parquet":
            data = self._get_parquet_data()
            df_actions = data["actions"]
            
            if df_actions.empty:
                return pd.DataFrame(columns=["date", "downtime_hours"])
            
            # Encontrar el último mes con datos disponibles
            df_actions['date'] = df_actions['change_date'].dt.date
            latest_date = df_actions['change_date'].max()
            
            if pd.isna(latest_date):
                logger.warning("No valid dates found in maintenance actions")
                return pd.DataFrame(columns=["date", "downtime_hours"])
            
            # Usar el año y mes de la última fecha disponible
            latest_year = latest_date.year
            latest_month = latest_date.month
            
            # Calcular inicio y fin del último mes con datos
            month_start = pd.Timestamp(datetime(latest_year, latest_month, 1), tz='UTC')
            
            # Fin del mes: primer día del siguiente mes - 1 día
            if latest_month == 12:
                month_end = pd.Timestamp(datetime(latest_year + 1, 1, 1), tz='UTC')
            else:
                month_end = pd.Timestamp(datetime(latest_year, latest_month + 1, 1), tz='UTC')
            
            # Filtrar acciones del último mes con datos
            df_month = df_actions[
                (df_actions["change_date"] >= month_start) &
                (df_actions["change_date"] < month_end)
            ].copy()
            
            if df_month.empty:
                logger.warning(f"No maintenance actions found for last available month ({latest_year}-{latest_month:02d})")
                return pd.DataFrame(columns=["date", "downtime_hours"])
            
            # Contar acciones por día como proxy de actividad de mantenimiento
            daily_counts = df_month.groupby('date').size().reset_index(name='action_count')
            
            # Estimar horas de downtime: 
            # - Cada acción representa ~1.5 horas de trabajo en promedio
            # - Esto es un estimado basado en la actividad registrada
            daily_counts['downtime_hours'] = daily_counts['action_count'] * 1.5
            
            logger.info(f"MTD downtime: Using last available month {latest_year}-{latest_month:02d}")
            logger.info(f"Data range: {len(daily_counts)} days from {daily_counts['date'].min()} to {daily_counts['date'].max()}")
            logger.info(f"Total actions: {daily_counts['action_count'].sum()}, Total hours: {daily_counts['downtime_hours'].sum():.2f}")
            
            return daily_counts[['date', 'downtime_hours']].sort_values('date')
        
        else:
            # TODO: Implement SQL query for production
            raise NotImplementedError("Production mode not yet implemented")


# Global instance - now keyed by (mode, client)
_repositories = {}


def get_repository(mode="dummy", client="cda") -> MaintenanceRepository:
    """
    Get or create repository instance.
    
    Args:
        mode: "dummy" for in-memory data, "parquet" for parquet files
        client: Client name (e.g., "cda", "emin")
        
    Returns:
        MaintenanceRepository instance
    """
    global _repositories
    key = (mode, client.lower())
    if key not in _repositories:
        _repositories[key] = MaintenanceRepository(mode, client)
    return _repositories[key]
