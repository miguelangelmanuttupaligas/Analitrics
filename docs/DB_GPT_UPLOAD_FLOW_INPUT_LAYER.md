# DB-GPT Upload Flow como guía para Analitrics

Este documento describe cómo DB-GPT trata uploads tabulares y qué patrones conviene observar. No redefine ni reemplaza el flujo de archivos de Analitrics.

Regla obligatoria:

```text
El flujo de archivos Analitrics no se reemplaza ni se reordena por DB-GPT.
```

El flujo vigente para archivos queda cerrado así:

```text
LibreChat upload -> RustFS original -> metadata Mongo/LibreChat -> DuckDB por conversationId -> catalogo/profiling en Postgres -> SQL validado -> respuesta -> chart estructurado
```

DB-GPT solo puede aportar técnicas alrededor de ese flujo:

- manejo de contexto;
- reintentos;
- razonamiento y crítica;
- feedback del usuario;
- contratos de chart;
- evolución a dashboard;
- patrones de seguridad alrededor de manifest público versus metadata privada.

Para el flujo futuro de conexión a bases de datos, DB-GPT sí será una referencia fuerte. Aun así, todo deberá adaptarse al contrato Analitrics: `tenantId`, `userId`, `conversationId`, permisos, catálogo separado y control plane propio.

## Revisión de código base DB-GPT

Repositorio revisado:

```text
https://github.com/eosphoros-ai/DB-GPT
clone local temporal: /tmp/dbgpt-fork-tmp-20260821200443
licencia: MIT
```

Rutas fuente relevantes observadas:

```text
packages/dbgpt-app/src/dbgpt_app/scene/chat_data/chat_excel/excel_reader.py
packages/dbgpt-app/src/dbgpt_app/scene/chat_data/chat_excel/excel_learning/chat.py
packages/dbgpt-app/src/dbgpt_app/scene/chat_data/chat_excel/excel_learning/prompt.py
packages/dbgpt-app/src/dbgpt_app/scene/chat_data/chat_excel/excel_analyze/chat.py
packages/dbgpt-app/src/dbgpt_app/scene/chat_data/chat_excel/excel_analyze/prompt.py
packages/dbgpt-serve/src/dbgpt_serve/session_file/domain.py
packages/dbgpt-serve/src/dbgpt_serve/session_file/models/models.py
packages/dbgpt-serve/src/dbgpt_serve/session_file/models/dao.py
packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/attachment_react_adapter.py
packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tools/execute_analysis.py
packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tools/code_interpreter.py
packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tools/sql_query.py
packages/dbgpt-core/src/dbgpt/agent/core/context/manager.py
packages/dbgpt-core/src/dbgpt/agent/core/context/compact.py
packages/dbgpt-core/src/dbgpt/agent/expand/actions/chart_action.py
packages/dbgpt-core/src/dbgpt/vis/tags/vis_chart.py
```

## Flujo observado en DB-GPT

Endpoint principal para `chat_excel`:

```text
POST /api/v1/resource/file/upload?chat_mode=chat_excel&conv_uid=<id>&sys_code=<tenant>&model_name=<model>
multipart field: doc_files
```

Pasos:

1. El endpoint recibe uno o más `UploadFile`.
2. Define bucket interno fijo: `dbgpt_app_file`.
3. Por archivo construye metadata:
   - `user_name`
   - `sys_code`
   - `conv_uid`
4. Guarda el archivo con `FileStorageClient.save_file`.
5. El storage genera:
   - `file_id` UUID si no se pasa uno;
   - `uri` tipo `dbgpt-fs://<storage>/<bucket>/<file_id>?...`;
   - `file_hash` MD5;
   - `file_size`;
   - `storage_path`;
   - metadata persistida en tabla `dbgpt_serve_file`.
6. Para `chat_excel`, valida que exista exactamente un archivo.
7. Si la extensión es `.xls`, `.xlsx`, `.csv`, `.json` o `.parquet`, marca `file_learning=true`.
8. Crea una conversación interna `ConversationVo` con:
   - `user_input="Learn from the file"`;
   - `chat_mode=chat_excel`;
   - `select_param=file_param`;
   - `user_name`;
   - `sys_code`.
9. Instancia `ChatExcel` y ejecuta `chat.prepare()`.
10. `ChatExcel` resuelve el archivo:
    - si `file_path` es `dbgpt-fs://`, lo descarga a `DATA_DIR`;
    - crea ruta DuckDB bajo `DATA_DIR/_chat_excel_tmp/_chat_excel_<file>.duckdb`;
    - si existe un DuckDB previo en storage con `file_id=<original_file_id>_<conv_uid>`, lo descarga y lo reutiliza.
11. `ExcelReader` carga el archivo a DuckDB:
    - intenta carga directa con DuckDB (`read_csv`, `read_xlsx`, `read_json_auto`, `read_parquet`);
    - si falla, cae a pandas;
    - normaliza columnas reemplazando espacios por `_`;
    - crea primero `temp_table`;
12. `ExcelLearning` genera profiling semántico con LLM:
    - sample de datos;
    - DDL/schema;
    - `SUMMARIZE`;
    - descripción del dataset;
    - análisis de columnas;
    - planes de análisis sugeridos.
13. Con la respuesta del LLM, `ExcelReader.transform_table` crea `data_analysis_table`:
    - renombra columnas;
    - agrega comentarios de tabla;
    - agrega comentarios de columnas.
14. Si se creó un `.duckdb`, DB-GPT lo sube otra vez a su storage usando `file_id=<original_file_id>_<conv_uid>`.
15. En preguntas posteriores, `ChatExcel.generate_input_values` entrega al LLM:
    - pregunta del usuario;
    - nombre de tabla;
    - tipos de visualización disponibles;
    - DDL con comentarios;
    - muestra pequeña de datos.
16. La respuesta esperada incluye SQL embebido en `api-call`; luego `display_sql_llmvis` ejecuta SQL y transforma el resultado a `chart-view`.

## Lógica real que conviene extraer como guía, sin tocar el flujo de archivos

### A. Fase de learning antes de responder

DB-GPT no intenta responder contra el Excel bruto. Su `ChatExcel.prepare()` crea una corrida `ExcelLearning` cuando el chat todavía no tiene historia.

Patrón:

```text
archivo -> tabla temporal DuckDB -> sample + DDL + SUMMARIZE -> LLM learning -> tabla final comentada
```

Para Analitrics esto no cambia el pipeline actual. Solo confirma una práctica que ya perseguimos: separar preparación, enriquecimiento semántico y respuesta.

Traducción conceptual:

```text
FileResolver -> DuckDbWorkspace -> ProfileEnricher -> CatalogRepository -> SemanticCatalogEnricher
```

El cambio importante no es copiar su prompt, sino copiar la separación mental:

- `ingest/profile` prepara el dataset;
- `semantic_enrich` entiende columnas y conceptos;
- `query_answer` responde preguntas.

### B. Loader con fallback explícito

DB-GPT intenta:

```text
DuckDB directo: SELECT * FROM '<file>'
si falla:
  read_csv / read_xlsx / read_json_auto / read_parquet
si falla:
  pandas/read_excel/read_csv
```

Para Analitrics esto no modifica la decisión actual de loaders del MVP. Solo queda como inspiración para errores más claros y fallback futuro:

- CSV: mantener `read_csv_auto` como primera vía.
- XLS/XLSX: mantener pandas/openpyxl como vía principal.
- Agregar fallback futuro para Excel difícil o CSV irregular.
- Registrar `loader_strategy`, `loader_error` y `warnings` en Postgres.

### C. Manifest público versus rutas privadas

DB-GPT separa dos representaciones:

- `SessionFileManifest`: seguro para el agente y UI.
- `SessionFilePrivateRecord`: contiene `storage_uri`, `sha256`, owner y datos privados.

También genera un `files_json_path` interno para que el proceso Python reciba el mapa `file_id -> path` por variable de entorno, no por texto en el prompt.

Para Analitrics debemos mantener este contrato sin cambiar las fuentes de verdad:

```text
LLM ve:
  file_id, filename, mime, size, status, ordinal, resumen/profiling

runtime ve:
  tenantId, userId, conversationId, storageKey, bucket, sha256, local_path
```

Esto evita que el modelo invente rutas, filtre paths internos o mezcle archivos entre usuarios.

### D. Errores indistinguibles para seguridad

En `attachment_react_adapter.py`, DB-GPT usa el mismo error para:

```text
archivo inexistente
archivo de otro usuario
archivo de otra sesión
archivo borrado
archivo fallido
```

Para Analitrics conviene adoptar el mismo patrón en APIs internas:

```text
404 ANALITRICS_FILE_NOT_FOUND
```

El usuario no debe poder enumerar `file_id` ajenos distinguiendo mensajes.

### E. Context management por capas

DB-GPT implementa una compactación progresiva:

1. truncar observaciones antiguas;
2. mantener rondas recientes;
3. resumir con LLM si el contexto se acerca al límite;
4. compactación reactiva si el modelo rechaza por contexto.

Para Analitrics este es el aporte más inmediato de DB-GPT al flujo de archivos, porque no cambia almacenamiento, DuckDB, catálogo ni SQL. Solo mejora qué contexto llega a cada paso:

- detectar si la pregunta es nueva, seguimiento o corrección;
- preservar `last_sql`, `last_answer` y últimos mensajes relevantes;
- enviar ese contexto analítico a scope/generate_sql/repair_sql;
- más adelante, reemplazar “pasar todo” por memoria analítica compactada.

### F. Visualización como salida estructurada

DB-GPT no trata el gráfico como texto decorativo. `ChartAction` ejecuta SQL, obtiene dataframe y produce un protocolo `vis-db-chart` con:

```text
type
sql
title
describe
data
```

Para Analitrics esto tampoco cambia el pipeline de archivos. Solo endurece la salida posterior a SQL:

```text
analitrics_chart:
  chart_type
  sql
  title
  x/y/series
  data points
  reason
```

La UI React debe renderizar ese contrato. El texto del LLM no debe incluir código de gráfico ni duplicar tablas si ya existe componente visual.

## Cambios pequeños ya alineados con esta guía

Se agregó en Analitrics una primera versión de contexto analítico conversacional:

```text
analitrics_agent/analytical_context.py
```

Objetivo:

- clasificar la pregunta como `new_question`, `follow_up` o `correction`;
- extraer `last_sql` desde la traza `analitrics_sql`;
- extraer `last_answer`;
- pasar `analytical_context` a:
  - validación de alcance;
  - generación SQL;
  - reparación SQL.

Esto cubre el caso tipo:

```text
Usuario: ¿Top cursos por ingresos?
Analitrics: responde tabla + SQL.
Usuario: No, usa producto en vez de curso.
Analitrics: debe interpretar la segunda pregunta como corrección del análisis anterior.
```

Limitación actual:

- es heurístico;
- no compacta todavía;
- no persiste memoria analítica separada;
- no modifica catálogo automáticamente por una corrección conversacional.

Próximo paso natural:

```text
CorrectionFeedbackExtractor
```

Este componente leerá correcciones explícitas del usuario y propondrá guardarlas como feedback del catálogo, idealmente con confirmación visual en el panel derecho.

## Piezas valiosas para rescatar sin reemplazar el flujo

### 1. Metadata de archivo explícita

DB-GPT modela metadata de archivo como entidad propia:

```text
bucket
file_id
file_name
file_size
storage_type
storage_path
uri
custom_metadata
file_hash
user_name
sys_code
created/modified timestamps
```

Analitrics ya tiene su contrato operativo. DB-GPT sirve como checklist para no perder campos:

```text
tenantId
userId
conversationId
messageId
file_id
filename
mimeType
bytes
storageKey
bucket
source
hash/checksum
createdAt
```

El punto rescatable es `file_hash` como disciplina de trazabilidad. En Analitrics debe convivir con nuestro contrato actual y no cambiar la propiedad del archivo original: RustFS sigue siendo la fuente persistente.

### 2. Storage separado de metadata

DB-GPT separa:

- bytes del archivo en storage;
- metadata consultable en DB;
- URI portable para volver a leer el archivo.

Analitrics ya va en esa dirección con RustFS + Mongo temporal + Postgres control plane. DB-GPT no reemplaza esa decisión.

### 3. Cache DuckDB derivada y reutilizable

DB-GPT no trata DuckDB como fuente primaria. Lo usa como derivado reconstruible del archivo y lo cachea por archivo/conversación.

Para Analitrics, la regla ya definida se mantiene:

```text
RustFS = fuente original
DuckDB = cache analítica derivada
Postgres control plane = catálogo/profiling/memoria analítica
```

La cache se mantiene aislada por `tenantId + userId + conversationId`. La invalidación y reconstrucción deben respetar ese aislamiento.

### 4. Learning inicial separado del análisis

DB-GPT separa dos fases:

- `ExcelLearning`: entiende y transforma dataset.
- `ChatExcel`: responde preguntas usando schema enriquecido.

Analitrics debe mantener esa separación conceptual dentro de su propio flujo:

- `ingest/profile`: carga archivo, detecta schema, crea catálogo técnico.
- `semantic_enrich`: crea descripciones, sinónimos, reglas y planes.
- `query_answer`: responde preguntas usando catálogo y DuckDB.

Esto evita reprocesar semántica en cada pregunta.

### 5. DDL comentado como contexto LLM

DB-GPT convierte el profiling semántico en comentarios DuckDB:

```sql
CREATE TABLE data_analysis_table (
  amount DOUBLE COMMENT '...'
) COMMENT '...';
```

Es un patrón útil de representación, no de persistencia. Para Analitrics, el LLM puede recibir un contexto parecido, pero generado desde nuestro catálogo en Postgres:

```text
tabla
columnas
tipos
descripciones
sinónimos
calidad
muestras pequeñas
reglas confirmadas por usuario
```

DuckDB no será dueño del catálogo. Si usamos DDL comentado, será solo una vista textual generada desde Postgres.

### 6. Fallback de lectura

DB-GPT intenta lectura directa con DuckDB y cae a pandas si falla.

Analitrics hoy:

- CSV: DuckDB `read_csv_auto`.
- Excel: pandas/openpyxl.

Podemos mejorar errores y trazabilidad tomando el patrón, sin cambiar el flujo base:

1. Probar DuckDB directo cuando aplique.
2. Caer a pandas/openpyxl.
3. Registrar en metadata qué estrategia funcionó.
4. Guardar advertencias de lectura.

### 7. Tipos de archivo más amplios

DB-GPT soporta en `chat_excel`:

```text
.xls, .xlsx, .csv, .json, .parquet
```

Analitrics por ahora prioriza:

```text
.csv, .xls, .xlsx, .ods
```

Para el MVP está bien. Como mejora natural, evaluar:

```text
.tsv, .json, .jsonl, .parquet
```

### 8. Visualización como contrato, no como HTML final

DB-GPT usa `chart-view` después de ejecutar SQL.

Para Analitrics conviene rescatar la idea, pero no depender del HTML:

```text
sql
rows/schema
chart_type
x/y/series
aggregation
filters
title
reason
```

Ese contrato luego puede transformarse en gráfico, reporte HTML o dashboard persistente.

## Qué no conviene copiar

- No copiar `sys_code` como garantía de aislamiento; en DB-GPT es metadata útil, no enforcement fuerte.
- No copiar storage local como fuente principal; Analitrics ya definió RustFS.
- No copiar el límite de un solo archivo para Excel; Analitrics debe soportar varios archivos adjuntos.
- No copiar el reprocesamiento por pregunta.
- No depender del streaming de `chat_excel`; en la versión probada falla en modo incremental.
- No usar HTML final como persistencia de reporte.
- No dejar que el LLM decida ejecutar herramientas fuera de contratos explícitos.

## Diseño recomendado para el input layer Analitrics

Primer alcance:

1. `UploadPolicy`
   - intercepta CSV/XLS/XLSX enviados como contexto;
   - fuerza preservación del original en RustFS;
   - respeta la metadata base que LibreChat deja en MongoDB.

2. `FileMetadataResolver`
   - resuelve archivos por `file_id`, `conversationId`, `messageId`;
   - valida `tenantId`;
   - rechaza archivos no tabulares;
   - recupera bucket/storageKey/mime/bytes/hash.

3. `FileFingerprint`
   - calcula o recupera hash real del objeto;
   - define si hay que reprocesar.

4. `TabularLoader`
   - intenta loader directo DuckDB;
   - fallback pandas/openpyxl;
   - soporta varias hojas y varios archivos;
   - normaliza nombres sin perder mapa original.

5. `DuckDbSessionCache`
   - cache por `tenantId + conversationId` o `analysisSessionId`;
   - lock por sesión;
   - tabla por archivo/hoja;
   - reconstruible desde RustFS.

6. `TechnicalProfiler`
   - row count;
   - columnas/tipos;
   - nulos;
   - cardinalidad;
   - min/max para fechas/números;
   - muestra pequeña;
   - warnings de calidad.

7. `SemanticCatalogBuilder`
   - inspirado en `ExcelLearning`;
   - genera descripción de dataset, columnas y planes de análisis;
   - marca inferencias como `inferred`;
   - permite corrección del usuario.

## Lectura final

La forma en que Analitrics consume archivos es mejor para nuestro negocio porque:

- conserva RustFS como fuente canónica;
- respeta tenant/control plane;
- puede soportar varios archivos;
- permite cache DuckDB propia;
- evita acoplar el producto a DB-GPT.

Lo que DB-GPT aporta como guía es la disciplina del pipeline:

```text
upload -> metadata -> storage URI -> hash -> DuckDB cache -> profiling semántico -> DDL comentado -> SQL -> visualización
```

Ese pipeline debe reimplementarse en Analitrics con nuestros límites de tenant, memoria y auditoría.
