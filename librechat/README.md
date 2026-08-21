# LibreChat en Analitrics

Esta carpeta separa el codigo fuente upstream de LibreChat de la capa custom de Analitrics.

## Estructura

- `fork/`: codigo fuente de LibreChat clonado desde upstream para cambios controlados en React/API.
- `custom/`: runtime actual de Analitrics: compose, gateway, `librechat.yaml`, Dockerfile y parches de transicion.

## Upstream

- Repositorio: `https://github.com/danny-avila/LibreChat.git`
- Commit inicial clonado: `b4593f80b7ec0a5e3c0e3eb0f51941dd34349230`

El `.git` interno de `fork/` fue removido para evitar que este repo lo trate como submodulo accidental. El codigo queda versionado por el repositorio Analitrics.

## Regla de trabajo

- Cambios React reales deben implementarse en `fork/`.
- Parches temporales sobre imagen compilada deben vivir en `custom/fork/patches`.
- `custom/api/Dockerfile` debe mantenerse como ensamblador, no como lugar de logica larga.
