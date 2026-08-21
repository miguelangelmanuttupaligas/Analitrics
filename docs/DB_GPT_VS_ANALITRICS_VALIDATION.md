# Validacion DB-GPT vs LibreChat + Analitrics

Fecha de validacion: 2026-08-16

Esta comparacion evalua DB-GPT contra `LibreChat + analitrics-adapter + analitrics-app`.
Keycloak se considera una capacidad comun externa: si DB-GPT no cubre auth/tenant nativo,
la hipotesis valida es extenderlo con Keycloak, claims o headers confiables.

Wren AI queda fuera de evaluacion por decision de producto: no se usara al no considerarse
OSS suficiente para Analitrics.

## Criterio de comparacion

No se compara "DB-GPT completo" contra "LibreChat + Keycloak + todo Analitrics".
Se compara:

- DB-GPT como plataforma candidata de data product.
- LibreChat + Adapter/App como plataforma construida por Analitrics.

## Prueba comun XLSX

Archivo:

```text
data_2024_2026.xlsx
```

Pregunta:

```text
Cuantas filas tiene el archivo y cual es el monto total? Responde con numeros.
```

Resultado esperado validado por pandas:

```text
filas: 10812
monto_total: 18199238.3
```

## Evidencia LibreChat + Analitrics

Comando:

```bash
QUESTION='Cuantas filas tiene el archivo y cual es el monto total? Responde con numeros.' \
FILENAME='data_2024_2026.xlsx' \
make analitrics-agent
```

Resultado observado:

```json
{
  "in_scope": true,
  "sql": "SELECT (SELECT SUM(row_count) FROM \"__analitrics_catalog\" WHERE source_filename = 'data_2024_2026.xlsx') AS filas, (SELECT SUM(monto) FROM \"data_2024_2026_d98d15ef_data_2024_2026_hoja1\") AS monto_total;",
  "rows_preview": [
    {
      "filas": 10812.0,
      "monto_total": 18199238.300000146
    }
  ],
  "answer": "10812, 18199238.3",
  "chart_spec": {
    "chart_required": false
  }
}
```

Servicios verificados:

```text
analytics-agent: /health ok
analitrics-mcp: /health ok
LibreChat API: MCP analitrics cargado
```

Consumo observado en idle/aproximado:

```text
analitrics-analytics-agent   167 MiB
analitrics-mcp                62 MiB
LibreChat API                438 MiB
gateway                       15 MiB
```

## Evidencia DB-GPT

DB-GPT corre con imagen derivada:

```text
analitrics/dbgpt-openai:gpt5.5-spike
```

Modelo:

```text
LLM_MODEL_NAME=gpt-5.5
EMBEDDING_MODEL_NAME=text-embedding-3-small
```

Patch requerido:

- DB-GPT upstream `v0.8.1` usa `max_tokens`, incompatible con `gpt-5.5`.
- Se agrego patch para usar `max_completion_tokens` en modelos `gpt-5.*`.
- Se agrego fallback deterministico al parser de `excel_learning`.

Flujo probado:

```text
POST /api/v1/resource/file/upload?chat_mode=chat_excel
POST /api/v1/chat/completions
```

Resultado observado:

```text
upload_success: true
file_learning: true
SQL generado: SELECT COUNT(*) ..., ROUND(SUM(MONTO), 2) ...
filas_totales: 10812
monto_total: 18199238.3
response_table: true
```

DB-GPT genero una salida `chart-view` tipo tabla con SQL y datos:

```json
{
  "type": "response_table",
  "sql": "SELECT COUNT(*) AS filas_totales, ROUND(SUM(MONTO), 2) AS monto_total FROM data_analysis_table;",
  "data": [
    {
      "filas_totales": 10812,
      "monto_total": 18199238.3
    }
  ]
}
```

Consumo observado:

```text
analitrics-dbgpt-webserver ~1.1 GiB RAM
```

## Matriz inicial

| Area | LibreChat + Analitrics | DB-GPT | Lectura |
| --- | --- | --- | --- |
| Chat UI | Validado con LibreChat y SSO previo | UI propia disponible | DB-GPT podria reemplazar UI, pero falta validar UX real |
| XLSX -> tabla | Validado via RustFS + Python + DuckDB | Validado con `chat_excel` + DuckDB | Ambos pasan |
| GPT-5.5 | Validado en Analitrics | Validado con patch | DB-GPT requiere mantenimiento de patch o fork |
| SQL generado | Validado, con sqlglot read-only | Validado, SQL incluido en `chart-view` | DB-GPT ya devuelve artefacto mas cercano a dashboard |
| Respuesta numerica | Correcta | Correcta | Empate en esta prueba |
| Graficos | `chart_spec` propio, no persistente | `chart-view` y endpoints de chart editor | DB-GPT esta mas cerca de producto BI |
| Dashboards | No implementado | Hay escenas/endpoints de charts; dashboard completo pendiente de prueba UI/API | DB-GPT tiene ventaja potencial |
| Datasources DB | Pendiente en Analitrics | Endpoints datasource disponibles | DB-GPT tiene ventaja potencial |
| Tenant/auth | LibreChat + Keycloak ya avanzado | `sys_code` validado como metadata/filtro parcial; no es aislamiento real | Requiere gateway + patch/adaptador |
| Storage | RustFS integrado | Storage interno DB-GPT validado; RustFS no validado | Analitrics va delante si RustFS es requisito |
| Observabilidad | Phoenix integrado | Logs + tracing propio no evaluado | Analitrics va delante hoy |
| Control de producto | Alto, codigo propio | Medio, plataforma grande + patches | Depende de cuanto aceptemos adaptar DB-GPT |
| Recursos | Menor para agente, pero LibreChat completo suma | DB-GPT ~1.1 GiB solo webserver | Analitrics es mas liviano por componente |

## Endpoints DB-GPT relevantes encontrados

Charts:

```text
/api/v1/chart/editor/submit
/api/v1/editor/chart/info
/api/v1/editor/chart/list
/api/v1/editor/chart/run
```

Datasources:

```text
/api/v2/serve/datasource-types
/api/v2/serve/datasources
/api/v2/serve/datasources/test-connection
/api/v2/serve/datasources/{datasource_id}/refresh
```

Files:

```text
/api/v1/resource/file/upload
/api/v1/resource/file/read
/api/v2/serve/file/files/{bucket}
```

AWEL:

```text
/api/v1/serve/awel/flows
/api/v1/serve/awel/flow/debug
/api/v1/serve/awel/flow/import
/api/v1/serve/awel/flow/export/{uid}
```

## Validacion focal: charts, tenant/auth y storage

### 1. Chart persistente / dashboard

Resultado: parcialmente validado.

DB-GPT tiene capacidad suficiente para el MVP de archivos porque `chat_excel` ya:

- carga XLSX;
- genera DuckDB;
- responde preguntas con SQL;
- devuelve `chart-view` embebido cuando aplica.

No se considera necesario seguir validando `chat_excel` en este spike.

Para dashboard formal, usando una datasource como `Walmart_Sales`, DB-GPT genera charts con SQL y los expone por `/api/v1/editor/chart/list`.

Prueba `chat_dashboard`:

```text
conv_uid: analitrics-dashboard-validation
chat_mode: chat_dashboard
select_param: Walmart_Sales
```

Resultado:

```json
{
  "round": 1,
  "db_name": "Walmart_Sales",
  "charts": [
    {
      "showcase": "BarChart",
      "sql": "SELECT `Store` AS store, SUM(`Weekly_Sales`) AS total_sales FROM walmart_sales GROUP BY `Store` ORDER BY total_sales DESC LIMIT 8;",
      "title": "Top Stores by Total Sales"
    }
  ]
}
```

Tambien se valido `/api/v1/editor/chart/run` contra `Walmart_Sales`; ejecuta SQL y devuelve datos para graficar.

Brechas:

- `chart/info` fallo con `Unable to serialize unknown type: <class 'sqlalchemy.engine.row.Row'>`.
- No se probo aun que el dashboard sobreviva reinicio visualmente desde UI.

Lectura: DB-GPT esta mas cerca de dashboard que Analitrics actual. Para el MVP se acepta la capacidad actual de `chat_excel`; la validacion critica pasa a ser tenant/auth.

### 2. Tenant / auth

Resultado: `sys_code` funciona como metadata y filtro parcial, pero no como aislamiento real de plataforma.

Codigo observado:

```python
def get_user_from_headers(user_id: Optional[str] = Header(None)):
    if user_id:
        return UserRequest(user_id=user_id, role="admin", ...)
    else:
        return UserRequest(user_id="001", role="admin", ...)
```

Implicaciones:

- Si no llega `user-id`, DB-GPT crea un usuario mock `001`.
- Si llega cualquier `user-id`, DB-GPT lo acepta.
- El rol queda como `admin`.
- Esto no valida JWT, OIDC ni Keycloak.

Los endpoints `api/v2/serve/*` tienen Bearer opcional, pero si `api_keys` no esta configurado, permiten todo.

Prueba observada:

```text
GET /api/v2/serve/file/test_auth sin Bearer -> HTTP 200
GET /api/v2/serve/file/files/metadata sin Bearer -> HTTP 200
```

DB-GPT si tiene campos utiles para mapear `tenantId`:

```text
user_name
sys_code
custom_metadata
```

#### Files

Se subieron archivos de prueba con dos tenants:

```text
tenant-a -> user-a -> tenant_a.csv
tenant-b -> user-b -> tenant_b.csv
```

Metadata persistida:

```text
user_name=user-a
sys_code=tenant-a
user_name=user-b
sys_code=tenant-b
```

Problema: la metadata se puede leer por `bucket + file_id` sin Bearer y sin `sys_code`.

Ejemplo:

```text
GET /api/v2/serve/file/files/metadata?bucket=tenant_matrix&file_id=<file_tenant_a>
```

Respuesta:

```text
bucket=tenant_matrix
file_name=tenant_a.csv
storage_type=distributed
user_name=user-a
sys_code=tenant-a
```

Lectura: files persiste `sys_code`, pero no exige `sys_code` para lectura/download/delete. Debe parchearse o aislarse por gateway/adaptador.

#### Conversaciones

Se crearon conversaciones reales por tenant usando `/api/v1/chat/completions`:

```text
tenant-a-chat-validation -> sys_code=tenant-a
tenant-b-chat-validation -> sys_code=tenant-b
```

DB-GPT persistio:

```text
conv_uid                  user_name  sys_code
tenant-a-chat-validation  001        tenant-a
tenant-b-chat-validation  001        tenant-b
```

Observaciones:

- `sys_code` se persiste correctamente.
- `GET /api/v1/chat/dialogue/list?sys_code=tenant-a` devuelve solo tenant-a.
- `POST /api/v1/chat/dialogue/query` respeta `sys_code` si se envia.
- `GET /api/v1/chat/dialogue/messages/history?con_uid=<conv>` no recibe `sys_code` y permite leer mensajes solo conociendo `conv_uid`.
- El `user_name` enviado en el body no se preservo como `user-a/user-b`; quedo como `001` por el mock de auth.

Lectura: conversaciones tienen filtro parcial por `sys_code`, pero endpoints por `conv_uid` siguen siendo vulnerables si no se fuerza tenant desde una capa confiable.

#### Datasources

La tabla `connect_config` tiene columnas:

```text
user_id
sys_code
user_name
```

Pero el metodo observado `get_db_list()` filtra por `user_id`, no por `sys_code`:

```text
SELECT * FROM connect_config where user_id='<user_id>' or user_id='' or user_id IS NULL
```

La datasource ejemplo `Walmart_Sales` queda global:

```text
db_name=Walmart_Sales
user_id=''
sys_code=NULL
```

Lectura: datasource no esta lista para aislamiento por tenant. Para Analitrics habria que hacer que toda datasource pertenezca a `tenantId/sys_code`, y que los conectores read-only solo se resuelvan dentro de ese scope.

#### Decision sobre tenantId/sys_code

`sys_code` es buen candidato tecnico para `tenantId`, pero hoy DB-GPT no lo aplica de forma obligatoria ni segura.

Requisitos minimos si DB-GPT sigue como candidato:

- Gateway/Keycloak obligatorio delante de DB-GPT.
- El usuario no debe poder enviar `sys_code`; debe inyectarlo el gateway o un adapter confiable.
- Bloquear acceso directo al puerto interno de DB-GPT.
- Patch/adaptador para validar `tenantId/sys_code` en files metadata/read/download/delete.
- Patch/adaptador para validar `tenantId/sys_code` en conversation query/history/delete/clear/export.
- Patch/adaptador para validar `tenantId/sys_code` en datasource list/get/add/delete/refresh.
- Corregir `get_user_from_headers` para no crear usuario mock admin y para mapear usuario real desde claim/header confiable.

### 3. Storage de uploads

Resultado: validado como almacenamiento local persistente, no S3.

Con el compose actual, DB-GPT monta:

```text
volume-analitrics-dbgpt-pilot -> /app/pilot
volume-analitrics-dbgpt-data  -> /data
```

Archivos observados dentro del contenedor:

```text
/app/pilot/data/<uuid>.xlsx
/app/pilot/data/_chat_excel_tmp/_chat_excel_<uuid>.xlsx.duckdb
/app/pilot/data/file_server_5670/dbgpt_app_file/<file_id>_<node_hash>
/app/pilot/data/file_server_5670/dbgpt_app_file/<file_id>_<conv_uid>_<node_hash>
/app/pilot/meta_data/dbgpt.db
```

Modelo de storage observado en codigo:

```text
LocalFileStorage.storage_type = "local"
SimpleDistributedStorage.storage_type = "distributed"
```

`SimpleDistributedStorage.save()` indica explicitamente que guarda local:

```text
Just save the file locally.
```

Metadata SQLite:

```text
tabla: dbgpt_serve_file
campos: bucket, file_id, file_name, file_size, storage_type, storage_path, uri, custom_metadata, user_name, sys_code
```

Ejemplo de URI:

```text
dbgpt-fs://distributed/dbgpt_app_file/<uuid>?user_name=analitrics-spike&conv_uid=...
```

Lectura: DB-GPT no esta usando RustFS/S3 en esta configuracion. Preserva archivos y DuckDB en filesystem local persistente. Si RustFS sigue siendo requisito de producto, hay que integrar backend S3 compatible o sincronizar/adaptar uploads entre DB-GPT y RustFS.

## Lectura tecnica

DB-GPT parece mejor encaminado si Analitrics quiere ser una plataforma de data product:

- ya tiene `chat_excel`;
- ya materializa DuckDB;
- ya genera SQL;
- ya devuelve SQL y datos como `chart-view`;
- ya expone endpoints de chart editor;
- ya expone datasources;
- ya tiene AWEL para workflows.

LibreChat + Analitrics gana donde queremos control fino:

- SSO/Keycloak ya avanzado;
- tenantId ya pensado desde gateway/claims;
- RustFS ya integrado;
- trazabilidad Phoenix ya integrada;
- menor acoplamiento a una plataforma grande;
- mas control sobre restricciones de producto.

## Decision provisional

DB-GPT debe seguir como candidato principal para reemplazar una parte grande o total
de `LibreChat + analitrics-app`, pero no se declara reemplazo todavia.

La siguiente validacion debe enfocarse en endurecer `tenantId/sys_code`:

1. Definir si usaremos patch directo en DB-GPT o adapter/gateway delante de DB-GPT.
2. Inyectar `tenantId` desde Keycloak/gateway como `sys_code`, no desde el cliente.
3. Forzar filtro por `sys_code` en files metadata/read/download/delete.
4. Forzar filtro por `sys_code` en conversation query/history/delete/clear/export.
5. Forzar filtro por `sys_code` en datasource list/get/add/delete/refresh.
6. Reemplazar `get_user_from_headers` para mapear usuario real y nunca asignar admin por defecto.
7. Repetir prueba cruzada `tenant-a` vs `tenant-b` y confirmar que los accesos indebidos devuelven 403/404.
