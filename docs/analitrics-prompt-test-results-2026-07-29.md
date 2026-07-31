# Resultados de Prueba de Prompts Analitrics

Fecha de ejecución: 2026-07-29
Archivo usado: `/home/miguel/Descargas/data_2024_2026.xlsx`
Modelo usado: `Analitrics` (`gpt-4.1-mini`)

## Resumen

Se ejecutó la matriz de prompts definida en `docs/analitrics-prompt-test-matrix.md` usando chats nuevos y carga real del Excel.

## Estado por caso

| ID | Estado | Observación |
|---|---|---|
| A1 | OK | Resume bien el archivo y no genera gráfico. |
| A2 | OK | Da hallazgos gerenciales sin gráfico. |
| A3 | Parcial | Responde, pero hubo error SQL interno por casteo bigint con cadena vacía. |
| B1 | OK | Cuenta filas correctamente sin gráfico. |
| B2 | OK | Lista columnas correctamente sin gráfico. |
| B3 | Falla | Pierde el contexto del archivo y pide volver a especificarlo. |
| C1 | Falla | El usuario pide tabla y el sistema responde con UI visual en lugar de tabla explícita. |
| C2 | Falla | Intenta consultar una tabla `ventas` inexistente en lugar del contexto cargado. |
| C3 | OK | Devuelve tabla en markdown con país, curso y monto total. |
| D1 | OK | Genera gráfico horizontal. |
| D2 | OK | Genera tendencia mensual correctamente. |
| D3 | Falla | Aunque hay archivo cargado, dice que se suba un archivo. |
| E1 | Falla | No usa el contexto cargado y pide subir archivo/contexto. |
| E2 | Falla | No usa el contexto cargado y pide aclaración. |
| F1 | Parcial | Usa el archivo, pero no hay tablas corporativas publicadas para comparar. |
| F2 | Falla | Genera gráfico, pero la “comparación corporativa” replica el mismo archivo y no evidencia cruce real. |
| G1 | Falla | Sin adjuntar archivo, igual reutiliza el último Excel reciente; debió pedir archivo activo. |
| G2 | Falla | Inventa una dimensión inexistente (`region_comercial_avanzada`) y además genera gráfico. |
| G3 | Parcial | Devuelve una celda visual; no reconduce la petición absurda como límite del sistema. |

## Hallazgos principales

- La autoimportación del Excel ya funciona y persiste el contexto en PostgreSQL.
- El enrutamiento básico texto vs gráfico funciona bien en varios casos felices.
- Todavía hay pérdida de contexto en varios prompts ambiguos o gerenciales.
- Hay sobre-ejecución del motor gráfico en algunos casos donde debería responder tabla o pedir precisión.
- El caso “sin archivo cargado” está mal: el sistema reusa el último archivo reciente del usuario.
- Hay invención de dimensiones en consultas no soportadas.
- El enriquecimiento corporativo no está listo para demo porque no hay fuente corporativa realmente publicada en el esquema visible consultado.
