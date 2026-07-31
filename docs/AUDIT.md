# Auditoria de Carpetas - DataAI5

Fecha de auditoria: 2026-07-28

## Resumen ejecutivo

La instalacion activa ya esta separada en tres capas:

- `librechat-upstream-src`: codigo base limpio de LibreChat
- `librechat-overrides`: overrides tecnicos minimos y scripts de build
- `analitrics-extension`: toda la logica propia de Analitrics

El despliegue activo compila desde `librechat-build-src`, que es un arbol generado a partir de `librechat-upstream-src` mas los parches de `librechat-overrides`.

## Matriz por carpeta

### `analitrics-extension`

Estado: activa

Tipo:
- extension propia

Responsabilidad:
- servidor auxiliar de Analitrics
- MCP propio
- ingesta de archivos CSV/XLS/XLSX
- persistencia y reutilizacion de contexto
- generacion de graficos
- conexion a PostgreSQL

Subcarpetas clave:
- `src`: codigo fuente propio
- `dist`: build compilado de la extension
- `docs`: documentacion funcional de la extension

Observaciones:
- esta carpeta concentra la mayor parte del valor propio del proyecto
- no depende de modificar el core de LibreChat para su logica de negocio

### `librechat`

Estado: activa

Tipo:
- runtime operativo

Responsabilidad:
- stack Docker en ejecucion
- variables de entorno
- `librechat.yaml`
- volumenes de uploads, logs y MongoDB

Archivos clave:
- `docker-compose.yml`
- `.env`
- `.env.example`
- `librechat.yaml`

Subcarpetas relevantes:
- `uploads`: archivos cargados por usuarios
- `logs`: logs de ejecucion
- `data-node`: datos persistidos de MongoDB

Observaciones:
- esta carpeta no es codigo fuente principal
- contiene configuracion operativa y datos de runtime
- aqui tambien quedan algunos artefactos historicos no activos, como `apply_branding.sh` y `README_BRANDING.txt`

### `librechat-build-src`

Estado: activa, generada

Tipo:
- build tree temporal/generado

Responsabilidad:
- fuente usada por Docker para compilar LibreChat customizado
- resultado de aplicar overrides sobre upstream limpio

Origen:
- generado desde `librechat-upstream-src`
- parcheado con `librechat-overrides/patches`

Observaciones:
- no debe ser tratado como fuente canonica del negocio
- se puede regenerar en cualquier momento

### `librechat-upstream-src`

Estado: activa

Tipo:
- upstream limpio

Responsabilidad:
- snapshot local del codigo base de LibreChat
- referencia para comparar diffs y regenerar overrides

Observaciones:
- debe permanecer limpio
- no se debe editar manualmente para cambios de Analitrics

### `librechat-overrides`

Estado: activa

Tipo:
- overrides residuales

Responsabilidad:
- almacenar los parches tecnicos minimos
- documentar por que siguen existiendo
- scripts para preparar y reconstruir el arbol final

Contenido clave:
- `patches/0001-tabular-upload-behavior.patch`
- `patches/0002-ui-resource-iframe-height.patch`
- `scripts/prepare-librechat-build.sh`
- `scripts/rebuild-analitrics-stack.sh`
- `docs/OVERRIDES.md`
- `docs/MECHANISM_EVALUATION.md`

Observaciones:
- esta carpeta representa la frontera entre lo externalizado y lo aun no soportado por LibreChat

### `librechat-custom-src`

Estado: legado

Tipo:
- fuente historica no activa

Responsabilidad historica:
- fue una etapa previa donde se modificaba una copia completa de LibreChat

Observaciones:
- el despliegue actual ya no compila desde aqui
- `docker-compose.yml` actual usa `../librechat-build-src`
- puede conservarse como referencia temporal, pero no deberia seguir recibiendo cambios

### `stack-overflow-lab`

Estado: activo como laboratorio de datos, no como parte del frontend/chat

Tipo:
- dataset/laboratorio auxiliar

Responsabilidad:
- transformacion y preparacion del laboratorio basado en Stack Overflow
- scripts, data y carga asociada a PostgreSQL

Observaciones:
- ocupa mucho espacio
- es soporte de demo/datos, no parte del core de LibreChat ni de la extension

## Que esta fuera del codigo base

Ya esta fuera del core de LibreChat:

- MCP de Analitrics
- logica de ingesta tabular
- lectura de uploads desde LibreChat
- persistencia del contexto en PostgreSQL
- graficos
- reglas e intenciones de negocio
- configuracion de despliegue y compose local

## Que sigue como override residual

Solo quedan dos overrides tecnicos obligatorios:

### `0001-tabular-upload-behavior.patch`

Hace lo siguiente:

- agrega una via dedicada de carga `Excel / CSV analítico`
- evita que `.csv/.xls/.xlsx` sean enviados al provider como documento nativo
- mantiene el enrutamiento correcto hacia el contexto interno/MCP

### `0002-ui-resource-iframe-height.patch`

Hace lo siguiente:

- amplía la visualizacion de recursos UI embebidos
- evita scroll interno y clipping en graficos
- hoy esta reducido a un ajuste CSS global

## Carpetas activas por rol

Fuente canonica:
- `analitrics-extension`
- `librechat-upstream-src`
- `librechat-overrides`

Generadas:
- `librechat-build-src`
- `analitrics-extension/dist`

Runtime:
- `librechat`

Legado:
- `librechat-custom-src`

Datos/laboratorio:
- `stack-overflow-lab`

## Recomendacion operativa

Para evitar confusion futura:

- seguir desarrollando negocio solo en `analitrics-extension`
- mantener `librechat-upstream-src` limpio
- tocar `librechat-overrides` solo si hay un limite real del producto base
- tratar `librechat-custom-src` como legado hasta decidir archivarlo o eliminarlo
