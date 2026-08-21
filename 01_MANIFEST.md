# MANIFEST.md - Contrato rector de Analitrics

Si cualquier README, documento, compose, prompt o código contradice este archivo, manda este archivo.

## 1. Producto

Analitrics es un chat analítico construido alrededor de LibreChat.

El usuario conversa en un chat, adjunta archivos y recibe respuestas apoyadas por herramientas analíticas externas. El objetivo primordial es resolver bien ese flujo base, apoyado de una capa de identidad basada en un tenant y usuarios, donde el tenant es la representación de la empresa.

Capacidades objetivo que buscamos lograr:

- registrar e iniciar sesión asociados a un tenant id
- recibir preguntas con o sin archivos adjuntos;
- reutilizar archivos cargados dentro del chat donde fueron adjuntados;
- analizar CSV/XLS/XLSX con DuckDB o Python según convenga;
- responder con texto y tabla o guía de gráfico (si el chat ya responde con tabla, no gráficar);
- renderizar gráficos de forma determinística del lado backend cuando la guía sea válida usando librerias gráficas embebidas interactivas;
- dejar observabilidad básica del flujo.

## 2. Primer hito obligatorio

Antes de definir una arquitectura final o modificar LibreChat, el primer paso será levantar un entorno base con:

- LibreChat upstream ejecutándose en contenedor;
- Keycloak ejecutándose en contenedor;
- integración entre LibreChat y Keycloak para autenticación;
- generación de `tenantId` desde Keycloak, tanto de forma manual como automática;
- recepción de `tenantId` en LibreChat por el mecanismo más simple y mantenible que soporte el producto base: OpenID claim, JWT claim, header confiable desde proxy/auth gateway, o la opción equivalente más directa que confirmemos en código y configuración.

Este hito existe para validar empíricamente cómo LibreChat recibe, persiste y propaga `tenantId` antes de construir DirectFlow, almacenamiento definitivo de archivos o lógica analítica.

## 3. Arquitectura obligatoria

La arquitectura activa del repo será:

- `librechat/fork/`: árbol fuente upstream de LibreChat clonado para desarrollar cambios React/controlados sobre el producto base.
- `librechat/custom/`: runtime, compose, gateway, configuración y parches de transición de Analitrics sobre LibreChat. Mientras migramos a cambios fuente reales, esta carpeta ensambla la imagen con parches explícitos.
- `keycloak/`: identidad, realm, theme y configuración de SSO.
- `analitrics-adapter/`: adaptador delgado entre LibreChat y la capa analítica. Aquí viven wrappers/proxies mínimos que median tráfico de LibreChat sin introducir lógica analítica.
- `analitrics-app/`: runtime Python donde debe concentrarse la lógica analítica.
- `docs/`: documentación de decisiones, rescates conceptuales del MVP anterior y operación.

Componentes de infraestructura:

- RustFS será levantado desde el compose de `librechat/custom/` como almacenamiento S3 compatible para archivos cargados.
- Postgres de control plane ya forma parte del MVP para catálogo/profiling derivado de archivos. La memoria analítica avanzada, diccionarios confirmados, permisos finos y dashboard/widgets quedan como evolución sobre ese control plane.

Carpetas retiradas del contrato activo:

- `analitrics-extension/`: contenía el MVP DirectFlow anterior en TypeScript. Se rescatarán aprendizajes a nivel documental, pero el código se elimina del nuevo repo.
- `librechat-build-src/`: contenía un árbol fuente/fork previo de LibreChat. Se elimina del nuevo repo hasta que exista una decisión explícita de mantener un fork.
- `librechat-fork-tmp/`: fue una carpeta temporal de exploración upstream. Se elimina del nuevo repo.
- `librechat-src/`: fue la carpeta previa de runtime/configuración. Se elimina y su contenido activo pasa a `librechat/custom/`.

Regla central:

- LibreChat no debe cargar reglas de negocio analítico salvo hooks mínimos inevitables.
- Toda lógica analítica debe ir a Python en analitrics-app.
- Node/TypeScript queda permitido cerca de LibreChat solo para transporte, adaptación y lectura de contexto interno del runtime.
- La lógica DirectFlow previa no se migra como código; solo se rescatan ideas útiles en documentación.

## 4. Qué sí puede vivir dentro de LibreChat (`librechat/custom` y `librechat/fork`)

Aceptable dentro de LibreChat:

- branding visual;
- iconos, logos y favicon;
- textos visibles;
- `librechat.yaml`;
- wiring MCP;
- pequeños ajustes de UX o layout;
- hooks mínimos de upload cuando el producto base no expone una extensión suficiente.

No aceptable dentro de LibreChat:

- directflow analítico;
- workers LLM;
- planificación SQL;
- generación de gráficos;
- reglas de selección de fuente;
- lógica de negocio sobre archivos/tablas más allá del hook mínimo necesario para enrutar.

## 5. Estado funcional real

El MVP anterior implementó una lógica llamada DirectFlow para recibir XLSX/CSV, preparar contexto tabular y pedir al LLM respuestas con resumen o intención de gráfico.

Ese código queda retirado del contrato activo. La nueva implementación debe reconstruir solo las ideas útiles bajo el flujo definido en este manifiesto:

- archivos originales preservados en RustFS;
- análisis tabular en `analitrics-app`;
- DuckDB como cache de trabajo para archivos;
- profiling, catálogo temporal y diccionario apoyado por feedback del usuario;
- NL-SQL validado y ejecutado como solo lectura.

## 6. Regla de tratamiento de archivos cargados por un usuario

Respetaremos como LibreChat maneja la carga de archivos globales por usuario, pero el almacenamiento persistente de archivos debe estar fuera del filesystem efímero del contenedor.

Decisión actual:

- LibreChat debe usar estrategia S3 compatible para uploads persistentes;
- el servicio S3 compatible local será RustFS;
- RustFS vivirá como componente `storage-rustfs`;
- sus datos persistentes estarán bajo `/var/analitrics/storage/`;
- el bucket inicial será `librechat`;
- RustFS no debe exponer puertos al host en el MVP, solo a `network-analitrics`;
- los objetos deben quedar organizados por tenant cuando LibreChat incluya ese dato en el storage key.

Matiz validado:

- una subida estándar de archivo de conversación queda en RustFS con `source=s3`;
- una subida CSV usada por LibreChat como `tool_resource=context` puede convertirse a texto y guardarse como `source=text`, con el contenido extraído en MongoDB y sin preservar necesariamente el archivo original en RustFS en ese flujo;
- por eso Analitrics no debe asumir que todo CSV/XLS/XLSX cargado por el usuario ya estará disponible como objeto RustFS bajo el flujo nativo de LibreChat.

Regla de decisión para CSV y Excel:

- CSV debe preservarse como objeto en RustFS y Analitrics debe procesarlo descargando el original;
- Excel (`.xls`, `.xlsx`, `.ods`) debe preservarse como objeto en RustFS para análisis tabular, porque la conversión a texto pierde información relevante como hojas, tipos, formatos, celdas vacías, merges, fórmulas y estructura;
- si LibreChat además genera una versión `source=text` de CSV o Excel, esa versión solo puede usarse como vista previa o contexto superficial, no como fuente analítica autoritativa.

Esta regla no queda resuelta por configuración pura de LibreChat: el flujo actual `tool_resource=context` convierte CSV/Excel a texto antes de pasar por storage S3.

Decisión mínima inicial:

- `analitrics-adapter` incluirá `upload-file-wrapper` delante de `POST /api/files`;
- si el wrapper detecta CSV/Excel con `tool_resource=context`, quitará `tool_resource=context` antes de reenviar a LibreChat;
- LibreChat entonces aplicará `fileStrategies: s3` y guardará el archivo como objeto en RustFS;
- no se modifica el código fuente de LibreChat para esta regla.

Regla para la capa analítica:

- Analitrics debe poder recibir o resolver `file_id`, `conversationId`, `messageId`, `tenantId` y `userId`;
- Analitrics debe leer metadata de archivos desde LibreChat/MongoDB o desde un hook explícito;
- Analitrics debe descargar el archivo original desde RustFS cuando exista como `source=s3`;
- si LibreChat convierte un CSV/XLS/XLSX a `source=text`, necesitaremos un hook mínimo de upload o una ruta controlada para preservar el original en RustFS antes de procesarlo analíticamente.

La lógica de análisis tabular no debe vivir dentro de LibreChat.

Responsabilidades esperadas de `analitrics-app`:

- detectar tipo real de archivo, encoding, separador, hojas de Excel y headers;
- persistir metadata de datasets y lineage de archivo;
- crear tablas de trabajo en DuckDB para archivos cargados por usuario;
- inferir schema, tipos, conteos, nulos, muestras y estadísticas básicas;
- exponer herramientas al LLM para listar datasets, inspeccionar schema, generar SQL, validar SQL, ejecutar SQL solo lectura y resumir resultados;
- devolver resultados como texto, tabla y especificación de gráfico cuando aplique.

## 7. Principios de implementación

- preferir la solución más simple que funcione;
- no sobreingenierizar;
- evitar modificar LibreChat si una configuración o wrapper lo resuelve;
- si una modificación a LibreChat es inevitable, debes detenerte e indicarlo. Lo conversaremos y si se decide aplicar esta debe ser pequeña, documentada y con ruta de salida;
- no agregar servicios nuevos si no cambian el resultado del MVP.

## 7.1 MVP analítico tabular

Antes de crear MCP servers productivos, el primer MVP NL-SQL tabular se hará con scripts Python.

Decisiones:

- LibreChat Agents + MCP será la interfaz objetivo, pero no se implementa todavía en esta etapa;
- `analitrics-app/` será el runtime Python para lógica analítica;
- LangGraph será la herramienta inicial de orquestación del agente analítico;
- Python descargará archivos desde RustFS usando metadata de MongoDB (`file_id`, `tenantId`, `source=s3`, `storageKey`);
- CSV se cargará inicialmente con DuckDB `read_csv_auto`;
- Excel se leerá inicialmente con `openpyxl` vía pandas, una tabla por hoja;
- no se intentará resolver todos los CSV/Excel mal formados en el MVP: el input tabular debe ser razonablemente limpio por parte del usuario;
- si `read_csv_auto` u `openpyxl` no pueden leer un archivo, Analitrics debe devolver un error específico del archivo y del paso de ingesta, no un error genérico del flujo completo;
- como tercera vía futura, cuando fallen `read_csv_auto` y `openpyxl`, se evaluará un flujo robusto de normalización/conversión con herramientas externas como LibreOffice headless, parsers alternativos o detección avanzada de estructura antes de cargar a DuckDB;
- NL-SQL generará SQL DuckDB;
- `sqlglot` validará SQL de solo lectura antes de ejecutar;
- el flujo incluirá una revisión del LLM sobre su propia respuesta: validación de alcance, plan/generación SQL, validación, ejecución, respuesta, crítica, ajuste final y generación de especificación de gráfico cuando aplique.

Queda fuera de esta etapa:

- crear MCP servers;
- persistir tablas definitivas por tenant en Postgres;
- federar motores externos;
- conectar bases de datos empresariales externas;
- mezclar catálogos derivados de archivos con catálogos de bases de datos externas;
- RAG vectorial para datos tabulares.

Principio:

- para datos tabulares, el LLM no debe recibir el archivo completo como texto bruto;
- debe recibir catálogo/schema/muestras y consultar datos mediante SQL validado.
- el catálogo del MVP pertenece únicamente a archivos cargados por el usuario y procesados con DuckDB.
- el agente solo debe responder preguntas relacionadas con la data cargada, su catálogo, profiling, diccionario o resultados derivados;
- si la pregunta no pertenece al ámbito analítico de los archivos disponibles, debe rechazarla de forma breve y no ejecutar SQL ni herramientas analíticas.

Herramientas controladas iniciales:

- `resolve_file_metadata`: resuelve `file_id`, `tenantId`, `storageKey` y metadata desde MongoDB;
- `download_file`: descarga el objeto original desde RustFS;
- `load_file_to_duckdb`: carga CSV/XLS/XLSX a DuckDB;
- `profile_tables`: genera catálogo técnico mínimo;
- `check_question_scope`: valida si la pregunta pertenece a la data disponible;
- `generate_sql`: genera SQL DuckDB;
- `validate_sql`: bloquea SQL no read-only;
- `execute_sql`: ejecuta solo SQL validado;
- `compose_answer`: redacta respuesta usando solo resultados;
- `critique_answer`: revisa consistencia de la respuesta;
- `generate_chart_spec`: genera una especificación de gráfico cuando los resultados lo justifiquen.

Salida visual inicial:

- el agente puede devolver `chart_spec` en formato Vega-Lite cuando los resultados lo justifiquen;
- en el MVP inmediato, LibreChat recibirá `chart_spec` como traza nativa `analitrics_chart`, junto con `analitrics_context` y `analitrics_sql`;
- esta traza permite auditar qué gráfico se propuso sin tocar todavía el frontend;
- la renderización visual embebida del gráfico en el chat queda como siguiente mejora de UI.

Evolución a dashboard:

- un chart aprobado por el usuario podrá convertirse en widget persistente;
- el widget debe guardar, como mínimo:
  - SQL validado;
  - conexión/dataset origen;
  - `chart_spec`;
  - filtros;
  - política de refresco (`refresh policy`);
  - tenantId, userId, conversationId/messageId/runId de origen;
- el widget debe vivir fuera del chat en una vista de dashboards, pero conservar lineage hacia la conversación y SQL que lo generó;
- para archivos cargados, el widget debe poder reconstruirse desde RustFS + Postgres control plane + DuckDB cache derivada;
- para bases de datos futuras, el widget debe apuntar a la conexión/dataset de solo lectura correspondiente sin mezclar catálogos con archivos hasta diseñar esa reconciliación.

Regla:

- el LLM no tendrá acceso a bash libre ni a ejecución arbitraria de Python en el MVP;
- toda acción debe pasar por herramientas con contrato explícito.

Observabilidad inicial:

- Arize Phoenix será la herramienta OSS inicial para visualizar traces del agente;
- Phoenix se levantará como componente `phoenix` y expondrá UI local en `http://localhost:6006`;
- Analitrics emitirá spans OpenTelemetry por cada paso del agente;
- los traces deben incluir metadata operativa: `tenantId`, `file_id`, filename, estado de scope, SQL generado, cantidad de filas, estado de validación, crítica y decisión de gráfico;
- no se deben registrar archivos completos, resultados completos, credenciales ni datos sensibles por defecto;
- si Phoenix no está disponible, el agente debe seguir funcionando y la trazabilidad se deshabilita o falla de forma no bloqueante.

Contrato de alcance:

- el flujo actual se desarrollará alrededor de carga de archivos, profiling, catálogo temporal, diccionario y feedback del usuario;
- no se diseñará todavía el flujo de conexión a bases de datos empresariales;
- si a futuro se conectan bases de datos externas, su catálogo se mantendrá separado del catálogo de archivos;
- no habrá merge entre catálogo DuckDB/archivos y catálogo de bases de datos hasta diseñar una estrategia explícita, validada y documentada.

### 7.1.1 Memoria, retención y compactación analítica

El flujo analítico no debe crecer el prompt de forma bruta con todos los mensajes, archivos, muestras y resultados anteriores.

Principio:

- LibreChat puede retener la conversación completa según su propio modelo de historial;
- Analitrics debe construir una memoria analítica separada, compacta y auditable;
- el LLM solo debe recibir el contexto mínimo útil para la pregunta actual.

Ámbito de memoria inicial:

- `tenantId`: separa empresas y políticas futuras;
- `userId`: identifica al usuario que ejecuta la pregunta;
- `conversationId`: aísla el contexto de análisis del chat;
- `messageId`: permite asociar una pregunta/respuesta y sus archivos adjuntos;
- `analysisSessionId` no será usado como identificador operativo del MVP; el estado analítico debe colgar siempre de `conversationId`.

Cache de procesamiento:

- para el MVP, DuckDB debe operar como cache analítica aislada por `tenantId + userId + conversationId`;
- no se debe reprocesar cada archivo en cada mensaje;
- cada archivo procesado debe registrarse con `file_id`, `storageKey`, `filename`, `mimeType`, tamaño, hash/checksum si existe, tablas DuckDB generadas y timestamp de procesamiento;
- en cada nuevo mensaje solo se procesan archivos nuevos o archivos cuyo hash cambió;
- si no hay archivos nuevos, se reutiliza el DuckDB existente y su catálogo derivado.

Memoria que sí puede crecer:

- diccionario confirmado por el usuario;
- definiciones entregadas en hojas de diccionario, catálogo o metadata;
- reglas de negocio explícitas;
- KPIs confirmados;
- correcciones del usuario sobre interpretaciones previas;
- relaciones entre tablas confirmadas o de alta confianza.

Memoria que no debe crecer sin control:

- texto completo de archivos;
- muestras extensas de datos;
- resultados completos de queries;
- historial completo de mensajes;
- explicaciones intermedias del LLM;
- SQL descartado o respuestas criticadas, salvo como auditoría resumida.

Compactación:

- Analitrics debe generar un `conversation_analytic_summary` actualizado cuando la conversación crezca;
- este resumen debe incluir solo hechos útiles: datasets disponibles, tablas, columnas relevantes, definiciones confirmadas, KPIs, filtros frecuentes, decisiones del usuario y advertencias de calidad;
- las correcciones del usuario tienen prioridad sobre inferencias previas;
- inferencias del LLM deben quedar marcadas como `inferred`, no como verdad confirmada;
- si una inferencia es corregida, debe pasar a `rejected` o ser reemplazada por una entrada `confirmed`.

Autoridad del diccionario:

- usuario explícito;
- diccionario o catálogo adjunto;
- profiling;
- inferencia del LLM.

Retención:

- para el MVP local, los `.duckdb` y catálogos temporales pueden vivir en disco persistente bajo una ruta de Analitrics, separados por tenant y conversación;
- a futuro, la metadata de memoria analítica debe moverse a Postgres de control plane;
- no debe existir TTL normal para borrar `.duckdb` de chats activos;
- el `.duckdb` se borra cuando el usuario borra explícitamente el chat asociado;
- una limpieza futura solo podrá borrar caches huérfanas: chats inexistentes, usuarios inexistentes o rutas sin registro en control plane.

Implementación MVP actual:

- el agente modular `analitrics_agent` acepta `tenantId`, `userId`, `conversationId` y `messageId` como argumentos operativos;
- el agente crea o reutiliza una cache DuckDB bajo `/var/analitrics/analytics/cache/<tenant>/<user>/<conversationId>.duckdb`;
- MongoDB se usa temporalmente para guardar metadata de sesión en `analitrics_analysis_sessions` y auditoría de corridas en `analitrics_agent_runs`;
- esta persistencia en MongoDB es una solución MVP local, no el control plane definitivo;
- los archivos originales siguen viviendo en RustFS y la cache DuckDB debe poder reconstruirse desde esos objetos.
- cuando LibreChat borra un archivo tabular, Analitrics debe invalidar inmediatamente el catálogo/perfiles asociados en Postgres (`active=false`);
- la tabla física dentro del `.duckdb` puede permanecer hasta que se borre el chat, porque un mismo `.duckdb` puede contener tablas derivadas de varios archivos;
- una tabla invalidada no debe volver al contexto analítico ni a la lista de tablas permitidas para SQL, aunque siga físicamente presente en la cache.
- `analytics-agent` expone un contexto gerencial del chat desde Postgres para UI lateral: archivos, tablas, columnas, filas, estado de cache y timestamps;
- LibreChat consume ese contexto en un panel derecho del chat;
- los límites iniciales del MVP son configurables por entorno: chats activos por usuario, preguntas por chat y peso máximo por archivo.

Endurecimiento del MVP:

- `analytics-agent` debe usar un usuario S3 dedicado de solo lectura, diferente a las credenciales root usadas por LibreChat para subir archivos;
- `analytics-agent` no debe heredar ni usar `RUSTFS_ACCESS_KEY_ID`/`RUSTFS_SECRET_ACCESS_KEY`; si faltan `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`, el flujo debe fallar explícitamente;
- las rutas DuckDB deben estar aisladas por `tenantId`, `userId` y `conversationId`, y deben validarse para permanecer bajo `ANALITRICS_CACHE_DIR`;
- las descargas desde RustFS deben escribirse solo dentro de un directorio temporal hijo validado;
- la metadata de MongoDB debe resolver archivos por `tenantId`, `userId`, `source=s3` y `file_id`/`filename`;
- el `storageKey` debe coincidir con la ruta esperada del usuario autenticado (`t/<tenant>/uploads/<user>/...`);
- el SQL generado por el LLM debe ser validado como consulta de solo lectura antes de ejecutarse;
- quedan bloqueadas operaciones SQL de escritura, DDL, `COPY`, `ATTACH`, `INSTALL`, `LOAD`, `PRAGMA` y funciones de lectura arbitraria de archivos como `read_csv`, `read_json`, `read_parquet` o `glob`;
- el agente no debe exponer shell ni Python arbitrario al usuario;
- el contenedor del agente debe ejecutarse con filesystem raíz de solo lectura, `/tmp` efímero, sin capabilities Linux y con `no-new-privileges`;
- a futuro se implementará un sandbox efímero por ejecución para permitir habilidades controladas de código, gráficos y análisis avanzados sin darle al agente acceso permanente al estado.

Separación futura explícita:

- RustFS será la fuente persistente de archivos originales cargados por usuarios: CSV, XLS, XLSX, diccionarios, catálogos u otros adjuntos;
- DuckDB será una cache analítica derivada, reconstruible y aislada por conversación o sesión de análisis;
- Postgres de control plane será la fuente persistente de metadata operativa y memoria analítica estructurada del flujo de archivos.

Límite con bases de datos externas:

- la conexión a bases de datos empresariales externas queda en etapa de diseño futuro;
- el catálogo de bases de datos externas, cuando exista, debe mantenerse separado del catálogo de archivos cargados por usuario;
- no se deben mezclar términos, relaciones, KPIs o reglas entre ambos catálogos sin una etapa explícita de reconciliación;
- DuckDB puede seguir siendo útil para archivos y análisis derivados, pero no define por sí mismo la estrategia de integración con bases externas.

Postgres de control plane deberá guardar, como mínimo:

- tenants, usuarios y referencias de conversación;
- sesiones analíticas y estado de procesamiento;
- archivos conocidos, `file_id`, `storageKey`, tamaño, tipo, hash/checksum y timestamps;
- datasets derivados, hojas, tablas DuckDB y columnas detectadas;
- profiling, advertencias de calidad y estadísticas resumidas;
- diccionario de negocio, términos, sinónimos, reglas y correcciones del usuario;
- KPIs confirmados, inferidos o ambiguos;
- relaciones entre tablas confirmadas o inferidas;
- historial resumido de queries, SQL validado, errores y decisiones relevantes.

Regla:

- Postgres de control plane no reemplaza RustFS como almacenamiento de archivos;
- DuckDB no debe ser tratado como base definitiva;
- si una cache DuckDB se borra, Analitrics debe poder reconstruirla desde RustFS y metadata de Postgres;
- si una entrada del diccionario nace del LLM, debe marcarse como inferida hasta que el usuario o un catálogo explícito la confirme.

## 8. Identidad de usuarios

- Buscamos que Librechat use un SSO contra Keycloak, lo que permitirá poder sincronizarnos a varias empresas cada una con diferentes metodos, o crear solo usuarios locales nuestros, asi como creación masiva. 

## 9. Mejora futura multi-tenant

El MVP puede operar con `tenantId=analitrics` fijo mientras validamos el flujo base.

Cuando exista el primer cliente empresarial, la evolución esperada será:

- Keycloak seguirá siendo la fuente de identidad;
- un único realm `analitrics` podrá federar distintos proveedores por empresa: Google Workspace, Azure AD, LDAP, GitHub u OIDC/SAML genérico;
- Keycloak emitirá `tenantId` desde atributo, grupo o regla de proveedor, no hardcoded;
- el gateway validará que el tenant esperado por host/subdominio coincida con el `tenantId` autenticado;
- el gateway inyectará `X-Tenant-Id` solo después de validar esa coincidencia;
- LibreChat no debe quedar expuesto directamente al navegador; todo tráfico de usuario debe pasar por el gateway.

## 10. Pendiente de recuperación de contraseña

Keycloak tiene habilitada la pantalla y lógica de recuperación de contraseña, pero el flujo no está completo operacionalmente hasta configurar correo saliente.

Pendientes antes de producción:

- configurar SMTP real del realm `analitrics`;
- validar envío de correo de recuperación;
- revisar y brandear plantillas de email como Analitrics;
- definir expiración final de action tokens de usuario;
- habilitar eventos/auditoría para intentos de recuperación;
- evaluar `verifyEmail=true` para cuentas auto creadas;
- agregar rate limiting/captcha en el borde si aparecen intentos abusivos.

## 11. Mejora futura de login con Google

Queremos permitir que un usuario se registre o inicie sesión usando Google desde la pantalla de Keycloak.

Principio:

- LibreChat no integrará Google directamente;
- Keycloak actuará como identity broker;
- LibreChat seguirá recibiendo una sesión OpenID desde Keycloak;
- el usuario autenticado por Google entrará inicialmente al tenant `analitrics` por defecto.

Flujo esperado:

- el usuario entra a Analitrics;
- el gateway lo envía a Keycloak;
- Keycloak muestra el formulario local y un botón `Continuar con Google`;
- Google autentica al usuario;
- Keycloak crea o vincula el usuario;
- Keycloak emite token OIDC hacia LibreChat;
- el gateway conserva/injecta `X-Tenant-Id=analitrics` durante el MVP.

Pendientes para habilitarlo:

- crear OAuth Client en Google Cloud;
- configurar redirect URI de Google hacia Keycloak;
- agregar Google como Identity Provider en el realm `analitrics`;
- usar scopes `openid email profile`;
- revisar el diseño del botón con icono de Google dentro del theme `analitrics`;
- mantener `tenantId=analitrics` como asignación por defecto mientras el producto sea mono-tenant.

## 12. Acceso administrativo a Keycloak

El administrador de la plataforma debe poder entrar al Admin Console de Keycloak para operar usuarios, credenciales temporales, proveedores de identidad y atributos como `tenantId`.

Estado inicial:

- usaremos un único dominio público base: `analitrics.com`;
- Analitrics app vivirá en `https://analitrics.com/`;
- Keycloak público vivirá bajo `https://analitrics.com/auth/`;
- Admin Console vivirá bajo `https://analitrics.com/auth/admin/`;
- en desarrollo local usaremos `https://analitrics-test.com:3443` para evitar colisionar con el dominio público real `analitrics.com`;
- en VM producción el reverse proxy deberá exponer `https://analitrics.com` por 443 sin puerto en la URL.

Pendientes de endurecimiento:

- mover `https://analitrics.com/auth/admin/` detrás de HTTPS real en producción;
- restringir acceso por VPN, túnel o allowlist de IP;
- no publicar puertos internos de Keycloak directamente;
- crear admins nominales y evitar compartir el bootstrap admin;
- activar MFA obligatorio para administradores;
- habilitar eventos/auditoría administrativa.

## 13. Contrato de URLs y reverse proxy

Producción debe operar con un único dominio público:

- aplicación: `https://analitrics.com/`;
- login OIDC: `https://analitrics.com/oauth/openid`;
- callback OIDC: `https://analitrics.com/oauth/openid/callback`;
- callback OIDC del LibreChat Admin Panel: `https://analitrics.com/api/admin/oauth/openid/callback`;
- LibreChat Admin Panel: `https://analitrics.com/admin`;
- Keycloak realm: `https://analitrics.com/auth/realms/analitrics`;
- Keycloak Admin Console: `https://analitrics.com/auth/admin/`.

Regla para la VM:

- el NGINX público debe tener `server_name analitrics.com`;
- `/auth/` debe proxyear a Keycloak por la red interna Docker;
- `/` debe proxyear al gateway o API de LibreChat por la red interna Docker;
- `/admin/` debe proxyear al Admin Panel de LibreChat;
- no se deben publicar directamente los puertos internos de LibreChat API, Keycloak, MongoDB o Postgres;
- en local se usa `https://analitrics-test.com:3443`; ese dominio y puerto son solo una concesión de desarrollo, no forma parte de la URL de producción.

Variables de producción esperadas:

- `PUBLIC_ORIGIN=https://analitrics.com`;
- `PUBLIC_PORT=443`;
- `DOMAIN_CLIENT=https://analitrics.com`;
- `DOMAIN_SERVER=https://analitrics.com`;
- `ADMIN_PANEL_URL=https://analitrics.com/admin`;
- `OPENID_ISSUER=https://analitrics.com/auth/realms/analitrics`;
- `KC_HOSTNAME=https://analitrics.com/auth`;
- `KC_HOSTNAME_ADMIN=https://analitrics.com/auth`.

Variables locales esperadas:

- `PUBLIC_HOST=analitrics-test.com`;
- `PUBLIC_ORIGIN=https://analitrics-test.com:3443`;
- `PUBLIC_PORT=3443`;
- `DOMAIN_CLIENT=https://analitrics-test.com:3443`;
- `DOMAIN_SERVER=https://analitrics-test.com:3443`;
- `ADMIN_PANEL_URL=https://analitrics-test.com:3443/admin`;
- `OPENID_ISSUER=https://analitrics-test.com:3443/auth/realms/analitrics`;
- `KC_HOSTNAME=https://analitrics-test.com:3443/auth`;
- `KC_HOSTNAME_ADMIN=https://analitrics-test.com:3443/auth`.

Redirect URIs locales que debe permitir el cliente OIDC `librechat` en Keycloak:

- `https://analitrics-test.com:3443/oauth/openid/callback`;
- `https://analitrics-test.com:3443/api/admin/oauth/openid/callback`.

Nota:

- `https://analitrics.com/admin` es el panel administrativo de LibreChat;
- `https://analitrics.com/auth/admin/` es el panel administrativo de Keycloak;
- el cliente OIDC `librechat` de Keycloak debe permitir ambos redirect URIs: `/oauth/openid/callback` para LibreChat y `/api/admin/oauth/openid/callback` para LibreChat Admin Panel;
- como LibreChat upstream solo detecta el flujo admin por origen distinto, Analitrics usa una imagen derivada mínima de LibreChat API para reconocer `ADMIN_PANEL_URL` por path (`/admin`) en el mismo origen;
- el acceso a LibreChat Admin Panel debe depender del rol `ADMIN` dentro de LibreChat;
- para administradores federados, Keycloak debe emitir un claim OIDC y LibreChat debe mapearlo con `OPENID_ADMIN_ROLE`;
- ambos deben endurecerse antes de producción con MFA, usuarios nominales y restricción de red/IP.

Estado actual de integración admin:

- Keycloak tiene el grupo `analitrics-admins`;
- el cliente OIDC `librechat` emite el claim `groups` en ID token, access token y userinfo;
- LibreChat está configurado para promover a `ADMIN` a usuarios cuyo ID token contenga `groups=analitrics-admins`;
- el usuario inicial `analitrics.user@example.com` está asignado al grupo `analitrics-admins`;
- el rol `ADMIN` se aplica en LibreChat al iniciar sesión por OIDC; si el usuario ya tenía sesión abierta, debe cerrar sesión y volver a entrar.

Logout local:

- LibreChat debe cerrar también la sesión SSO de Keycloak usando `OPENID_USE_END_SESSION_ENDPOINT=true`;
- después del logout se debe volver a `/login?redirect=false` para evitar que `OPENID_AUTO_REDIRECT=true` reinicie sesión inmediatamente;
- no se deben crear rutas paralelas de logout; la única vía soportada debe ser el flujo nativo de LibreChat hacia `/api/auth/logout` y posterior retorno a `/login?redirect=false`.
