# Vista "Mantenciones General" - Guía de Uso

## 📋 Descripción

La vista **Mantenciones General** proporciona una ventana consolidada del estado de equipos y trabajos de mantenimiento. Incluye:

- **KPIs principales**: Estado de equipos y horas detenidas
- **Visualizaciones**: Gráficos de distribución y tendencias
- **Tablas detalladas**: Detenciones recientes y trabajos realizados

## 🏗️ Arquitectura

### Componentes Implementados

```
tds_alerts_dashboard/
├── src/data/
│   ├── dummy_generator.py           # Generador de datos dummy
│   └── maintenance_repository.py    # Capa de acceso a datos
├── dashboard/
│   ├── tabs/
│   │   └── tab_mantenciones_general.py    # Layout de la vista
│   └── callbacks/
│       └── mantenciones_general_callbacks.py  # Callbacks interactivos
└── generate_dummy_data.py           # Script para generar datos de prueba
```

### Data Contract

El sistema respeta el siguiente modelo de datos:

- **MACHINES**: Equipos de la flota
- **SYSTEMS**: Sistemas técnicos
- **SUBSYSTEMS**: Subsistemas de cada sistema
- **COMPONENTS**: Componentes de cada subsistema
- **MACHINE_SYSTEMS**: Relación máquinas-sistemas
- **RECORDS**: Registros de detención
- **JOBS**: Trabajos realizados en cada record
- **ACTIONS**: Acciones específicas en cada job
- **ACTION_TYPES**: Catálogo de tipos de acción

## 🚀 Uso

### 1. Generar Datos Dummy (Primera Vez)

Para poblar datos de prueba:

```bash
cd tds_alerts_dashboard
python generate_dummy_data.py
```

Esto creará archivos CSV en `data/mantentions/dummy/` con datos sintéticos pero consistentes.

### 2. Ejecutar el Dashboard

Si ya tienes Docker corriendo:

```bash
# El dashboard ya está en http://localhost:8050
# Solo necesitas refrescar el navegador
```

Si necesitas reiniciar:

```bash
cd tds_alerts_dashboard
docker-compose restart
```

### 3. Acceder a la Vista

1. Abre el navegador en: http://localhost:8050
2. Inicia sesión (usuario: `admin`, contraseña: `admin123`)
3. En el menú lateral, ve a: **Monitoring > Mantentions**
4. Haz clic en el botón **"Refrescar"** para cargar los datos

## 📊 Funcionalidades

### KPIs Principales

- **Equipos Totales**: Conteo total de máquinas en la flota
- **Equipos Sanos**: Máquinas sin detenciones activas
- **Equipos Detenidos**: Máquinas con detenciones en curso
- **Horas Detenidas MTD**: Total de horas de detención en el mes actual

### Visualizaciones

#### Gráfico de Estado de Equipos (Donut)
- Distribución visual entre equipos sanos y detenidos
- Colores: Verde (Sano), Rojo (Detenido)

#### Tendencia de Horas Detenidas (Línea)
- Evolución diaria de horas de detención en el mes
- Permite identificar patrones y picos de actividad

### Tablas Interactivas

#### Últimos Periodos de Detención
- Muestra los últimos 3 periodos de detención por equipo
- Incluye duración, estado (en curso/finalizado) y tipos de trabajo
- Filtrable y ordenable por columna

#### Trabajos Última Semana
- Lista todos los trabajos realizados en los últimos 7 días
- Muestra equipo, sistema, subsistema, tipo y notas
- Útil para seguimiento de actividades recientes

## 🔧 Modo Desarrollo vs Producción

### Modo Dummy (Actual)

El sistema actualmente usa datos generados en memoria:

```python
from src.data.maintenance_repository import get_repository

# Obtener repositorio en modo dummy
repo = get_repository(mode="dummy")

# Obtener datos
df_status = repo.get_status_counts()
df_downtime = repo.get_downtime_mtd()
```

### Modo Producción (Futuro)

Para conectar a base de datos real, modificar en `maintenance_repository.py`:

```python
def get_status_counts(self, start_date, end_date):
    if self.mode == "prod":
        # Implementar consulta SQL
        query = """
        SELECT 
            CASE WHEN ongoing THEN 'DETENIDO' ELSE 'SANO' END as machine_status,
            COUNT(DISTINCT machine_id) as n_machines
        FROM records
        GROUP BY machine_status
        """
        return pd.read_sql(query, connection)
```

## 🎨 Personalización

### Cambiar Colores de KPIs

En `tab_mantenciones_general.py`, modifica la función `create_kpi_card()`:

```python
create_kpi_card("Equipos Sanos", "0", "fa-check-circle", "success")  # verde
create_kpi_card("Equipos Detenidos", "0", "fa-exclamation-triangle", "danger")  # rojo
```

Colores disponibles: `primary`, `secondary`, `success`, `danger`, `warning`, `info`, `light`, `dark`

### Ajustar Cantidad de Registros en Tablas

En `maintenance_repository.py`:

```python
def get_last_detentions(self, n_per_machine: int = 3):  # Cambiar aquí
    # ...
```

### Modificar Rango de Datos Dummy

En `generate_dummy_data.py`:

```python
tables = generate_dummy_tables(
    n_machines=50,        # Más equipos
    n_systems=8,          # Más sistemas
    days_back=90,         # Más historia
    seed=42               # Cambiar seed para datos diferentes
)
```

## 🐛 Solución de Problemas

### La vista no carga datos

1. Verifica que los datos dummy existan:
   ```bash
   ls data/mantentions/dummy/
   ```

2. Si no existen, genera nuevamente:
   ```bash
   python generate_dummy_data.py
   ```

3. Verifica los logs del contenedor:
   ```bash
   docker-compose logs -f
   ```

### Error en callbacks

Revisa la consola del navegador (F12 > Console) para ver errores de JavaScript.

### Tablas vacías

Haz clic en el botón **"Refrescar"** en la vista para recargar los datos.

## 📈 Próximos Pasos

- [ ] Conectar a base de datos real (Databricks/SQL Warehouse)
- [ ] Agregar filtros por fecha
- [ ] Implementar exportación a Excel
- [ ] Agregar más visualizaciones (breakdown por sistema)
- [ ] Notificaciones de alertas críticas

## 🤝 Contribuir

Para agregar nuevas funcionalidades:

1. Modificar `maintenance_repository.py` para agregar nuevas consultas
2. Actualizar `tab_mantenciones_general.py` para el layout
3. Agregar callbacks en `mantenciones_general_callbacks.py`
4. Registrar en `app.py` si es necesario

## 📞 Soporte

Para dudas o problemas, revisar:
- Logs del dashboard: `docker-compose logs`
- Documentación del proyecto: `documentation/`
- Guía original: `01_dashboard_general_build_guide.md`
