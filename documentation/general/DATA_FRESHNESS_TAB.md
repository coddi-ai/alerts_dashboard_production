# Estado de Actualización de Datos - Data Freshness

## 📋 Descripción

Nueva pestaña del dashboard que monitorea en tiempo real el estado de actualización de los datos de **Telemetría** y **Tribología** para todas las unidades.

## 🎯 Funcionalidad

### Indicadores de Estado

La tabla muestra el estado de actualización de datos con un sistema de semáforo de tres colores:

#### 🟢 Verde - Actualizado
- **Telemetría**: Última actualización hace menos de 1 hora
- **Tribología**: Última actualización hace menos de 1 semana

#### 🟡 Amarillo - Atención Requerida
- **Telemetría**: Última actualización entre 1 y 4 horas
- **Tribología**: Última actualización entre 1 y 2 semanas
- **Significado**: Los datos empiezan a estar desactualizados, se requiere atención

#### 🔴 Rojo - Crítico
- **Telemetría**: Última actualización hace más de 4 horas
- **Tribología**: Última actualización hace más de 2 semanas
- **Significado**: Los datos están significativamente desactualizados, requiere acción inmediata

## ⚙️ Conversión de Zona Horaria

- Los datos en el archivo CSV (`Data_Date_Last_Update.csv`) están en **UTC+0**
- La visualización en el dashboard se muestra en **hora de Chile** (UTC-3 o UTC-4 según DST)
- La conversión se realiza automáticamente usando la zona horaria `America/Santiago`

## 📊 Características

1. **Tabla Detallada por Unidad**
   - Estado general de cada unidad
   - Última actualización de Telemetría (fecha y hora en Chile)
   - Tiempo transcurrido desde la última actualización de Telemetría
   - Última actualización de Tribología (fecha y hora en Chile)
   - Tiempo transcurrido desde la última actualización de Tribología
   - Estado individual por tipo de dato

2. **Tarjetas de Resumen**
   - Cantidad de unidades actualizadas (verde)
   - Cantidad de unidades que requieren atención (amarillo)
   - Cantidad de unidades en estado crítico (rojo)
   - Hora de la última actualización del dashboard

3. **Leyenda Visual**
   - Explicación clara de los criterios para cada color
   - Ayuda al usuario a interpretar rápidamente el estado

## 📁 Archivos Involucrados

### Layout
- **`dashboard/tabs/tab_data_freshness.py`**: Definición del layout de la pestaña

### Callbacks
- **`dashboard/callbacks/data_freshness_callbacks.py`**: Lógica de procesamiento y visualización

### Configuración
- **`dashboard/layout.py`**: Registro de la pestaña en el menú de navegación
- **`dashboard/app.py`**: Importación del módulo de callbacks

### Datos
- **`data/auxiliar/cda/Data_Date_Last_Update.csv`**: Archivo fuente con fechas de actualización (UTC+0)

## 🔄 Uso

1. Navegar a **Resumen > Estado de Datos** en el menú lateral
2. Revisar las tarjetas de resumen para una vista rápida
3. Consultar la tabla para detalles específicos por unidad
4. Filtrar y ordenar la tabla según sea necesario
5. Exportar los datos a Excel si es necesario (botón en la tabla)

## 🚀 Próximos Pasos Recomendados

1. **Actualización Automática**: Configurar un refresh automático cada X minutos
2. **Alertas**: Implementar notificaciones cuando unidades entren en estado crítico
3. **Historial**: Registrar el histórico de estados para análisis de tendencias
4. **Gráficos**: Agregar visualizaciones de tendencias de actualización

## 📝 Notas Técnicas

- La tabla se ordena automáticamente por estado (Crítico primero)
- Las fechas se formatean como `YYYY-MM-DD HH:MM` en hora de Chile
- Los tiempos transcurridos se muestran en formato legible (días, horas, minutos)
- La tabla soporta búsqueda, filtrado y ordenamiento nativo
- Los datos se pueden exportar a Excel para análisis adicional
