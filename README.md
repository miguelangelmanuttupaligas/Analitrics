# Analitrics

Analitrics es un chat analítico construido sobre LibreChat, con identidad vía Keycloak, almacenamiento persistente de archivos en RustFS y una capa analítica Python enfocada inicialmente en archivos CSV/XLS/XLSX.

El contrato rector está en [01_MANIFEST.md](./01_MANIFEST.md). Si otro documento contradice el manifiesto, manda el manifiesto.

## Estructura activa

- `librechat-src/`: runtime y configuración de LibreChat, gateway, RustFS y dependencias del chat.
- `keycloak/`: SSO, realm y theme Analitrics.
- `analitrics-adapter/`: wrappers/proxies mínimos cerca de LibreChat.
- `analitrics-app/`: lógica analítica Python, DuckDB, profiling y NL-SQL.
- `docs/`: decisiones y notas de arquitectura.

## Comandos principales

```bash
make keycloak up
make librechat up
make storage-metadata
make analitrics-build
```

Para detener:

```bash
make librechat down
make keycloak down
```

## Alcance del MVP

El MVP trabaja con archivos cargados por usuario:

- CSV/XLS/XLSX se preservan como objetos en RustFS.
- Analitrics descarga los originales y los procesa con DuckDB.
- El LLM recibe catálogo, profiling, muestras pequeñas y diccionario, no archivos completos.
- El feedback del usuario puede corregir o confirmar el diccionario analítico de la conversación.

Queda fuera del MVP:

- conectar bases de datos empresariales externas;
- crear MCP servers productivos;
- mezclar catálogos de archivos con catálogos de bases de datos;
- mantener un fork fuente de LibreChat sin una decisión explícita.
