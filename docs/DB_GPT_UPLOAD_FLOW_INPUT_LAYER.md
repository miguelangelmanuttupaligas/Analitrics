# DB-GPT Upload Flow como guía para Analitrics

Este documento describe cómo DB-GPT trata uploads tabulares y qué patrones conviene rescatar para el input layer de Analitrics. DB-GPT queda como referencia de diseño, no como motor obligatorio del MVP.

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

## Piezas valiosas para rescatar

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

Para Analitrics conviene usar un contrato similar, adaptado:

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

El punto más rescatable es `file_hash`: Analitrics debe usar hash real del objeto para invalidar cache DuckDB, no solo filename, `file_id` o tamaño.

### 2. Storage separado de metadata

DB-GPT separa:

- bytes del archivo en storage;
- metadata consultable en DB;
- URI portable para volver a leer el archivo.

Analitrics ya va en esa dirección con RustFS + Mongo temporal. A futuro, Postgres control plane debe asumir catálogo, profiling y memoria analítica, no duplicar innecesariamente la metadata base de archivo que LibreChat ya captura.

### 3. Cache DuckDB derivada y reutilizable

DB-GPT no trata DuckDB como fuente primaria. Lo usa como derivado reconstruible del archivo y lo cachea por archivo/conversación.

Para Analitrics, la regla correcta es:

```text
RustFS = fuente original
DuckDB = cache analítica derivada
Postgres control plane = catálogo/profiling/memoria analítica
```

La cache debe invalidarse por hash de archivo, no solo por filename o `file_id`.

### 4. Learning inicial separado del análisis

DB-GPT separa dos fases:

- `ExcelLearning`: entiende y transforma dataset.
- `ChatExcel`: responde preguntas usando schema enriquecido.

Analitrics debería copiar esa separación:

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

Es un patrón útil. Para Analitrics, el LLM debería recibir un contexto parecido, pero generado desde nuestro catálogo:

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

No necesitamos que DuckDB sea dueño del catálogo, pero sí podemos renderizar el catálogo como DDL comentado para el prompt.

### 6. Fallback de lectura

DB-GPT intenta lectura directa con DuckDB y cae a pandas si falla.

Analitrics hoy:

- CSV: DuckDB `read_csv_auto`.
- Excel: pandas/openpyxl.

Podemos mejorar tomando el patrón:

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
