# Hot Sheet - Nueva Pestaña

## Resumen

Se ha creado una nueva pestaña llamada "**Hot Sheet**" que proporciona una vista rápida del estado de todas las unidades mediante indicadores tipo semáforo que combinan datos de alertas y tribología.

## Ubicación en el Dashboard

La nueva pestaña se encuentra en:
- **Sección**: Monitoreo
- **Nombre**: Hot Sheet
- **Posición**: Primera pestaña en la sección de Monitoreo (vista principal)

## Funcionalidades Implementadas

### 1. Tarjetas de Resumen (KPIs)
Muestra 6 métricas clave:
1. **Unidades Totales**: Cantidad total de equipos monitoreados
2. **Alertas Anormales**: Equipos con estado crítico en alertas
3. **Alertas en Alerta**: Equipos con estado de advertencia en alertas
4. **Alertas Normales**: Equipos con estado normal en alertas
5. **Tribología Anormal**: Equipos con análisis de aceite anormal
6. **Tribología Normal**: Equipos con análisis de aceite normal

### 2. Tabla de Estado por Unidad

**Estructura de la tabla**:
```
| Unidad  | Alertas | Tribología |
|---------|---------|------------|
| CAT001  | 🔴 Anormal | 🟢 Normal |
| CAT002  | 🟡 Alerta  | 🔴 Anormal |
| CAT003  | 🟢 Normal  | 🟢 Normal |
```

**Características**:
- Una fila por unidad
- Dos columnas de estado: Alertas y Tribología
- Codificación por colores de fondo
- Iconos de semáforo (🔴🟡🟢⚪)
- Ordenamiento automático: unidades con peor estado primero

### 3. Sistema de Clasificación de Alertas

#### Niveles de Alertas (basados en campo `Trigger`):

**Nivel 1 - Crítico**:
- Engine Coolant Temperature (eng_cool_temp)
- Engine Oil Pressure (eng_oil_pres)

**Nivel 2 - Importante**:
- Transmission Oil Temperature (trans_oil_temp)
- Differential Oil Temperature (diff_oil_temp)
- Brake Oil Temperature (brake_oil_temp)
- Front/Rear Brake Oil Temperatures

**Nivel 3 - General**:
- Todos los demás triggers

#### Criterios de Estado para Alertas:

**🔴 Anormal (Rojo)**:
- 1 o más alertas nivel 1 en los últimos 7 días, **O**
- 3 o más alertas nivel 2 en los últimos 14 días

**🟡 Alerta (Amarillo)**:
- 1-2 alertas nivel 2 en los últimos 14 días, **O**
- 3 o más alertas nivel 3 en los últimos 14 días

**🟢 Normal (Verde)**:
- Ninguna de las condiciones anteriores

### 4. Sistema de Clasificación de Tribología

Basado en el estado del análisis de aceite más reciente:

**🔴 Anormal (Rojo)**:
- `report_status` contiene: "anormal", "critic", "critico"

**🟡 Alerta (Amarillo)**:
- `report_status` contiene: "precaucion", "advertencia", "alerta", "warning"

**🟢 Normal (Verde)**:
- `report_status` contiene: "normal"

**⚪ Sin Datos (Gris)**:
- No hay datos de tribología disponibles
- Estado no reconocido

## Lógica de Ordenamiento

Las unidades se ordenan por "peor estado primero" usando un sistema de prioridades combinadas:

```python
Prioridad: anormal (0) > alerta (1) > normal (2) > sin_datos (3)
Prioridad Combinada = Prioridad_Alertas + Prioridad_Tribología
```

Ejemplo:
- CAT001 con (Anormal, Anormal) = 0 + 0 = 0 (primera)
- CAT002 con (Anormal, Alerta) = 0 + 1 = 1 (segunda)
- CAT003 con (Normal, Normal) = 2 + 2 = 4 (última)

## Archivos Creados/Modificados

### Nuevos Archivos
1. `dashboard/tabs/tab_hot_sheet.py` - Layout de la pestaña
2. `dashboard/callbacks/hot_sheet_callbacks.py` - Lógica de callbacks
3. `HOT_SHEET_IMPLEMENTATION.md` - Esta documentación

### Archivos Modificados
1. `dashboard/layout.py` - Agregada al menú de navegación (primera en Monitoreo)
2. `dashboard/app.py` - Importados los callbacks
3. `dashboard/callbacks/navigation_callbacks.py` - Agregado el generador de contenido

## Datos Utilizados

### Fuentes de Datos
1. **Alertas**: `load_alerts_data(client)`
   - Archivo: `data/alerts/golden/{client}/consolidated_alerts.csv`
   - Columnas clave: `Timestamp`, `UnitId`/`Unidad`, `Trigger`, `componente`

2. **Tribología**: `load_oil_classified(client)`
   - Archivo: `data/oil/golden/{client}/classified.parquet`
   - Columnas clave: `unitId`, `report_status`, `sampleDate`

### Algoritmos Principales

#### `classify_alert_level(trigger: str) -> int`
Clasifica una alerta en nivel 1, 2 o 3 basándose en el nombre del trigger.

#### `calculate_alert_status(df_alerts, unit_id) -> str`
Calcula el estado de alertas ('anormal', 'alerta', 'normal') para una unidad considerando:
- Nivel de las alertas
- Período de tiempo (7 o 14 días)
- Cantidad de alertas

#### `calculate_tribology_status(df_oil, unit_id) -> str`
Obtiene el estado del análisis de aceite más reciente para una unidad.

#### `get_hot_sheet_data(df_alerts, df_oil) -> DataFrame`
Genera el DataFrame completo con el estado de todas las unidades.

## Codificación de Colores

```python
status_colors = {
    'anormal': '#ffcccc',  # Rojo claro
    'alerta': '#fff3cd',   # Amarillo claro
    'normal': '#d4edda',   # Verde claro
    'sin_datos': '#e2e3e5' # Gris claro
}
```

## Casos de Uso

1. **Vista Rápida de Flota**: Identificar en segundos qué unidades requieren atención inmediata

2. **Priorización de Inspecciones**: Las unidades en rojo (anormal) deben ser inspeccionadas primero

3. **Correlación Multi-técnica**: Ver si una unidad tiene problemas tanto en alertas como en tribología

4. **Monitoreo Ejecutivo**: Vista de alto nivel para gerencia sin entrar en detalles técnicos

5. **Validación Cruzada**: Verificar si las alertas están respaldadas por análisis de aceite

## Ventajas del Diseño

1. **Simplicidad**: Vista clara y directa, fácil de entender
2. **Acción Inmediata**: Los colores indican prioridad de acción
3. **Cobertura Completa**: Todas las unidades en una sola tabla
4. **Multi-técnica**: Combina dos fuentes de datos complementarias
5. **Actualización Dinámica**: Se actualiza automáticamente al cambiar de cliente

## Consideraciones Técnicas

### Manejo de Datos Faltantes
- Si no hay columna `Trigger`, se usa `componente` como fallback
- Si no hay datos de tribología, se marca como "Sin Datos"
- Si una unidad solo aparece en alertas o tribología, se incluye igual

### Performance
- Cálculo eficiente usando pandas vectorizado
- Pre-clasificación de niveles de alerta
- Filtrado temporal optimizado

### Escalabilidad
- Funciona con cualquier número de unidades
- Los triggers se pueden extender fácilmente
- Los criterios de tiempo son configurables

## Próximas Mejoras Sugeridas

1. **Filtros**: Agregar capacidad de filtrar por estado (mostrar solo anormales)
2. **Exportación**: Permitir exportar la tabla a Excel/PDF
3. **Histórico**: Ver evolución del estado en el tiempo
4. **Drill-down**: Click en una unidad para ver detalle de alertas
5. **Notificaciones**: Alertas automáticas cuando una unidad cambia a estado anormal
6. **Personalización**: Permitir ajustar criterios de clasificación por usuario
7. **Dashboard móvil**: Optimizar vista para tablets/móviles

## Ejemplo de Uso

1. Usuario abre el dashboard
2. Navega a **Monitoreo → Hot Sheet**
3. Ve inmediatamente:
   - 3 unidades en rojo (requieren atención urgente)
   - 5 unidades en amarillo (monitorear de cerca)
   - 12 unidades en verde (operando normalmente)
4. Prioriza inspección de las 3 unidades en rojo
5. Revisa si tienen también tribología anormal para confirmar criticidad
