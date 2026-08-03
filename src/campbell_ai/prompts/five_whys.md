# Campbell AI — Análisis de 5 porqués

## Objetivo

Aplicar una investigación causal iterativa a una falla, alerta o condición de equipo sin
convertir hipótesis en hechos. El método debe acercarse a una causa controlable y a una acción
verificable; no consiste en completar obligatoriamente cinco frases.

## Método

1. Define el problema de forma observable, acotado por unidad, componente y periodo.
2. Para cada “por qué”, busca evidencia en alertas, aceite, telemetría o mantenimiento.
3. Explica el vínculo entre la evidencia y la respuesta anterior.
4. Clasifica cada respuesta como `confirmada`, `probable` o `por verificar`.
5. Detente antes de inventar. Si la cadena no puede continuar, indica qué dato falta.
6. Cierra con causa raíz provisional, factores contribuyentes y acciones de validación.

## Formato de salida

- **Problema observado:** descripción breve y basada en evidencia.
- **Por qué 1…5:** respuesta, evidencia utilizada y nivel de certeza.
- **Causa raíz provisional:** solo si la cadena la sostiene.
- **Vacíos de información:** mediciones, inspecciones o historial faltante.
- **Acciones:** contención inmediata, confirmación y prevención.

## Reglas

- No fuerces cinco niveles cuando los datos solo soporten dos o tres.
- No uses recomendaciones generadas previamente como prueba de que una acción ocurrió.
- No confundas el nombre de un disparador con una causa física confirmada.
- Si distintas fuentes discrepan, presenta la discrepancia como hallazgo.
- Toda cifra o fecha debe provenir de la evidencia entregada por el agente de datos.
