# Analitrics LangGraph

Estado actual del flujo backend del agente analítico.

```mermaid
flowchart TD
    A[agent/run] --> B[resolve_and_profile]
    B --> B1[Resolver archivos: Mongo metadata + RustFS]
    B --> B2[Cargar o reutilizar DuckDB del conversationId]
    B --> B3[Profiling + catalogo tecnico]
    B --> B4[Leer feedback/catalogo de Postgres]
    B --> B5[LLM conversation_planner]
    B5 --> C[check_question_scope]

    C -->|out_of_scope| Z[END: respuesta fuera de alcance]
    C -->|needs_clarification| Z2[END: guardar aclaracion pendiente]
    C -->|requires_sql=false + feedback| P[persist_analysis_state]
    C -->|requires_sql=false| Z3[END: respuesta directa]
    C -->|planner decidio requires_sql=true| D[generate_sql]
    C -->|fallback raro| C1[LLM scope]
    C1 -->|in_scope| D
    C1 -->|fuera de alcance| Z

    D --> E[validate_sql]
    E -->|sqlglot + allowlist OK| F[execute_sql]
    E -->|SQL invalido| R[LLM repair_sql]
    R --> E

    F --> G[compose_answer]
    G --> H{critique_answer}
    H -->|caso simple validado| I[generate_chart_spec]
    H -->|caso complejo| H1[LLM critic]
    H1 --> I
    I -->|sin grafico solicitado| P
    I -->|grafico simple| I0[chart deterministic]
    I -->|grafico complejo| I1[LLM chart_spec]
    I0 --> P
    I1 --> P
    P --> END[END]
```

## Llamadas LLM Sincronas

- Siempre: `conversation_planner`.
- SQL: `generate_sql`.
- Respuesta: `compose_answer`.
- Critica: solo casos no simples. Se salta si SQL valido en primer intento, hay filas, no hubo repair, no hay grafico y el planner tiene confianza media/alta.
- Chart spec: solo si el usuario pide grafico y no aplica el generador deterministico simple.
- Solo fallback raro: `scope`.
- Solo si SQL falla validacion: `repair_sql`.
- Desactivado por defecto en el request sincrono: extractor LLM de `analysis_state`.

## Compactacion Conservadora

- `generate_sql` recibe un contexto compacto cuando el planner no esta en baja confianza.
- Si el planner tiene baja confianza, se usa el contexto amplio.
- No se eliminan columnas por keyword matching simple.
- `compose_answer`, `critique_answer` y `chart_spec` reciben filas acotadas y SQL compacto, no el resultado completo.
- El resultado completo permanece en memoria del flujo, trazas y respuesta estructurada; solo se recorta el payload enviado al LLM.

## Validacion SQL

`sqlglot` parsea y valida estructura SQL de solo lectura. Encima se mantiene una capa propia de allowlist porque `sqlglot` no conoce que tablas pertenecen al DuckDB aislado del chat. Esa allowlist permite CTEs locales y bloquea tablas externas.
