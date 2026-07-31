# Analitrics Orchestration Architecture

Fecha: 2026-07-29

## Objetivo

Reemplazar el ruteo rígido basado en instrucciones e `if/else` por una arquitectura en dos capas:

1. `orquestador`
2. `workers especializados`

## Capa 1: Orquestador

Tool principal:

- `orquestar_consulta_analitica`

Responsabilidades:

- tomar la pregunta del usuario;
- cargar el contexto real disponible;
- invocar workers pequeños;
- ejecutar el plan resultante;
- devolver una respuesta de negocio y, si aplica, una tabla o gráfico inline.

## Capa 2: Workers

Workers internos actuales:

- `context worker`
  - detecta archivo activo, adjunto reciente y tablas corporativas visibles.
- `context selection worker`
  - elige qué archivos/tablas deben quedar activos para la consulta actual.
- `source selection worker`
  - decide entre tres modos explícitos de trabajo: `archivo`, `corporativo` o `combinado`.
- `intent worker`
  - clasifica la intención del usuario y el formato de salida esperado.
- `planning worker`
  - decide fuente de datos, necesidad de importación, SQL y tipo de salida.
- `sql safety worker`
  - revisa y sanea SQL antes de ejecución, sin reemplazar la barrera técnica del runtime.
- `execution worker`
  - ejecuta importación, descripción de contexto, SQL y visualización.
- `validation worker`
  - verifica coherencia entre pregunta, evidencia y borrador.
- `answer worker`
  - redacta la respuesta final en español.
- `plan reconciliation worker`
  - revisa el plan preliminar y lo alinea con el contexto real disponible.
- `validation reconciliation worker`
  - ajusta la validación preliminar para evitar contradicciones con el contexto real.
- `answer reconciliation worker`
  - corrige borradores finales que contradicen el contexto disponible, antes de la limpieza final.

## Flujo actual del grafo

1. `resolve_context_node`
2. `select_context_node`
3. `clean_intent_node`
4. `classify_intent_node`
5. `source_selection_node`
6. `plan_node`
7. `reconcile_plan_node`
8. `sql_safety_node`
9. `execute_node` o `clarify_node`
10. `refresh_context_node`
11. `draft_answer_node`
12. `validate_node`
13. `reconcile_validation_node`
14. `repair_plan_node` si la validación falla
15. `cleanup_response_node`

## Modos explícitos de fuente

El grafo ya no deja esta decisión implícita solo al planner.
Ahora el `source selection worker` debe escoger exactamente uno de estos modos:

- `archivo`
  - usar solo tablas importadas desde CSV/XLSX cargados.
- `corporativo`
  - usar solo tablas PostgreSQL corporativas visibles en el snapshot.
- `combinado`
  - usar ambos contextos solo si existe una relación analítica defendible.

Si no existe base suficiente o la combinación no es justificable, el worker puede elevar una aclaración.

## Observabilidad por nodo

Cada nodo del grafo ahora emite trazas estructuradas con:

- nombre del nodo;
- timestamp de inicio y fin;
- duración en milisegundos;
- estado `ok` o `error`;
- resumen corto de entradas/salidas.

Estas trazas:

- se escriben en logs estructurados;
- se acumulan en `execution.graphTrace`;
- se exponen vía `diagnosticar_consulta_analitica`.

## Qué se eliminó

Se removieron del camino principal las sobreescrituras rígidas que antes:

- forzaban un plan alterno por archivo activo;
- corregían validaciones mediante guards determinísticos;
- reescribían respuestas finales por reglas ad hoc.

Ahora esas correcciones viven como workers explícitos dentro del `StateGraph`, por lo que el comportamiento es más auditable y mantenible.

## Contrato técnico residual

Todavía existen funciones de parseo y coerción técnica para:

- validar enums y esquemas JSON;
- aplicar defaults seguros cuando un worker omite un campo;
- proteger ejecución SQL y calificar tablas conocidas.

Estas piezas no deciden la estrategia analítica; solo endurecen el contrato técnico entre workers y ejecución.

En SQL quedó una defensa en dos capas:

- `sql safety worker`: control semántico y saneamiento previo dentro del grafo.
- `assertSelectOnly`: barrera técnica dura en runtime antes de ejecutar PostgreSQL.

Los workers deben devolver enums exactos del contrato, por ejemplo:

- `intent`: `resumen | hallazgos | calidad | conteo | columnas | tabla | grafico | comparacion | pregunta_gerencial | ambigua | otro`
- `outputMode`: `texto | tabla | grafico | aclaracion`
- `dataScope`: `archivo | corporativo | combinado | indefinido`
- `responseMode`: `texto | tabla | grafico | aclaracion`
- `dataSource`: `archivo | corporativo | combinado | ninguno`
- `chartType`: `barras | lineas | torta | tabla | ninguno`
- `orientation`: `horizontal | vertical | ninguna`

## Tools expuestos

### Tool principal de usuario

- `orquestar_consulta_analitica`

### Tool técnico de developer

- `diagnosticar_consulta_analitica`
  - ahora incluye `sourceSelection` y `graphTrace`.

### Tools de bajo nivel

- `importar_archivo_actual`
- `describir_contexto_actual`
- `listar_contextos_tabulares`
- `consultar_sql_contexto`
- `generar_grafico_contexto`
- `resumir_archivo_actual`

Estos tools bajos permanecen como capacidades de ejecución o soporte técnico, no como ruta principal de conversación.

## Integración con LibreChat

En `librechat.yaml` el modelo `Analitrics` ahora debe priorizar `orquestar_consulta_analitica` para solicitudes normales del usuario.

## Override técnico residual

No se cambió el core lógico de LibreChat para este comportamiento.
La lógica nueva vive en `analitrics-extension`.
