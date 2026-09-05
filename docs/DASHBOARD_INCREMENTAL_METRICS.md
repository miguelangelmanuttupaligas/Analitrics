# Dashboard Incremental y Métricas Derivadas

## Contrato MVP

El dashboard vive 1:1 con una conversación analítica. Para el MVP usa el `.duckdb` de esa conversación y el catálogo enriquecido guardado en Postgres.

El chat principal responde con texto y tablas. Los gráficos renderizados viven en `/dashboards`.

## Añadir Gráfico Incremental

Flujo implementado:

1. El usuario abre un panel existente.
2. Escribe una instrucción natural, por ejemplo:
   - `agrega un gráfico por país usando monto`
   - `cambia este gráfico a torta`
   - `quiero ver esto mensual`
   - `usa tipo_producto en vez de producto`
3. LibreChat envía la instrucción a:
   - `POST /api/analitrics/dashboards/:dashboardId/instructions`
4. El proxy de LibreChat agrega identidad:
   - `tenantId`
   - `userId`
5. El agente resuelve la instrucción con un planner LLM y devuelve una operación:
   - `add_chart`
   - `replace_chart`
   - `remove_chart`
   - `change_dimension`
   - `change_metric`
   - `change_chart_type`
6. El backend valida:
   - dashboard pertenece al usuario y tenant;
   - tabla/columnas existen;
   - SQL es read-only;
   - chart spec es compatible con Apache ECharts;
   - path DuckDB sigue dentro de `/var/analitrics/analytics/cache`.
7. Se modifica solo la vista afectada. No se reconstruye todo el dashboard salvo cambio de catálogo detectado por hash.

Cada gráfico se guarda como entidad independiente en `analysis_dashboard_views`:

- `dashboard_id`
- `view_id`
- `title`
- `sql`
- `metric`
- `dimensions`
- `filters`
- `chart_spec`
- `source_file_ids`
- `catalog_hash`
- `generation_metadata`

`generation_metadata` conserva:

- instrucción original del usuario;
- operación aplicada;
- resumen de cambio;
- SQL resultante;
- si usó feedback o métrica derivada;
- razón del planner.

## Métricas Derivadas

Las métricas derivadas no se hardcodean en el generador de dashboards. Se guardan como definiciones estructuradas en `analysis_catalog_metrics`.

Ejemplos de definición:

```json
{
  "name": "ticket_promedio",
  "label": "Ticket promedio",
  "kind": "avg",
  "value_column": "monto"
}
```

```json
{
  "name": "alumnos_unicos",
  "label": "Alumnos únicos",
  "kind": "count_distinct",
  "distinct_column": "alumno_id"
}
```

Kinds soportados inicialmente:

- `sum`
- `avg`
- `count`
- `count_distinct`
- `share_of_sum`

Estas métricas se exponen al generador SQL y a las tools de exploración como catálogo reutilizable. Si el catálogo cambia, el `catalog_hash` cambia y el dashboard puede regenerarse.

## Pendientes

- UI para elegir explícitamente qué gráfico reemplazar cuando la instrucción sea ambigua.
- Soporte visual para mostrar historial de cambios por gráfico.
- Mejor soporte de métricas compuestas con numerador/denominador arbitrario.
- Regeneración selectiva automática al cambiar solo una métrica derivada usada por un gráfico.
