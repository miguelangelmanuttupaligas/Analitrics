# Customizaciones de Analitrics

Fecha: 2026-07-28

## Objetivo

Este documento describe exactamente que parte del comportamiento actual pertenece a:

- overrides tecnicos sobre LibreChat
- extension propia de Analitrics
- configuracion operativa del despliegue

## 1. Overrides tecnicos sobre LibreChat

Ubicacion:
- `librechat-overrides/patches`

### `0001-tabular-upload-behavior.patch`

Archivos afectados en el build generado:

- `api/app/clients/BaseClient.js`
- `client/src/components/Chat/Input/Files/AttachFileMenu.tsx`
- `client/src/components/Chat/Input/Files/DragDropModal.tsx`
- `client/src/locales/es/translation.json`

Funcion exacta:

- agrega una opcion visible `Excel / CSV analítico`
- mantiene `Subir como texto`
- relabela la opcion del provider a `PDF / imagen / formatos del modelo`
- fuerza que archivos tabulares no entren por el flujo nativo del provider
- evita errores de MIME en proveedores que no aceptan Excel nativamente

Motivo:

- LibreChat hoy no expone un hook oficial para este routing

### `0002-ui-resource-iframe-height.patch`

Archivo afectado en el build generado:

- `client/src/style.css`

Funcion exacta:

- aumenta la altura visible de iframes para recursos UI embebidos
- mejora la lectura de graficos generados por el MCP

Motivo:

- LibreChat hoy no expone una configuracion oficial de altura para estos recursos

## 2. Extension propia de Analitrics

Ubicacion:
- `analitrics-extension/src`

### `server.ts`

Funcion:

- servidor HTTP de la extension
- expone healthcheck y endpoint MCP

### `services/mcpServer.ts`

Funcion:

- define herramientas MCP de Analitrics
- expone operaciones para importar contexto, resumirlo, consultarlo y graficarlo

### `services/ingestion.ts`

Funcion:

- procesa CSV/XLS/XLSX
- normaliza contenido
- lo persiste en PostgreSQL
- conserva historia de contexto reutilizable

### `services/librechatFiles.ts`

Funcion:

- localiza archivos previamente cargados en LibreChat
- resuelve rutas y metadatos operativos necesarios para su ingestion

### `services/charts.ts`

Funcion:

- genera graficos a partir del contexto cargado
- produce recursos UI embebibles en el chat

### `db.ts`

Funcion:

- encapsula conexion a PostgreSQL para la extension

### `config.ts`, `types.ts`, `utils.ts`

Funcion:

- configuracion tipada
- tipos compartidos
- utilidades auxiliares

## 3. Configuracion operativa activa

Ubicacion:
- `librechat/docker-compose.yml`
- `librechat/librechat.yaml`
- `librechat/.env`

### `docker-compose.yml`

Define:

- `librechat-api-local`
- `librechat-mongodb-local`
- `librechat-vectordb-local`
- `librechat-rag-api-local`
- `analitrics-extension-local`

Punto clave:

- la imagen `api` se construye desde `../librechat-build-src`
- la extension se construye desde `../analitrics-extension`

### `librechat.yaml`

Define:

- branding funcional de Analitrics
- `customWelcome`
- modelo por defecto
- limites de archivos
- MCP `analitrics-context`
- MCP `analitrics-postgres`

## 4. Flujo actual de build

Script:
- `librechat-overrides/scripts/prepare-librechat-build.sh`

Hace:

1. copia `librechat-upstream-src` a `librechat-build-src`
2. aplica todos los `.patch` de `librechat-overrides/patches`
3. deja una marca `.analitrics-build-origin`

Script:
- `librechat-overrides/scripts/rebuild-analitrics-stack.sh`

Hace:

1. prepara el build tree
2. recompila Docker para `api` y `analitrics-extension`
3. levanta el stack actualizado

## 5. Componentes legacy

### `librechat-custom-src`

Estado:
- legado

Significado:
- fue una etapa anterior de customizacion directa sobre una copia completa de LibreChat

Decision actual:
- no es la fuente activa del build
- no deberia seguir recibiendo cambios

### `librechat/apply_branding.sh`

Estado:
- legado operativo

Significado:
- parcheaba HTML compilado dentro del contenedor

Decision actual:
- la estrategia actual prioriza recompilar desde fuente y no depender de este mecanismo

## 6. Regla de mantenimiento

Orden correcto para cambios futuros:

1. primero intentar resolverlo en `analitrics-extension`
2. si es configuracion, resolverlo en `librechat.yaml` o `docker-compose.yml`
3. si de verdad no existe hook oficial, documentar y agregar override minimo en `librechat-overrides`
4. no modificar `librechat-upstream-src`
5. no retomar `librechat-custom-src` como fuente principal
