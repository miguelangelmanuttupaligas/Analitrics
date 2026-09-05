# Analitrics LibreChat Fork

Esta carpeta contiene los cambios propios de Analitrics sobre la imagen base de LibreChat.

Objetivo:

- Identificar rapido que codigo no pertenece a LibreChat upstream.
- Mantener el fork controlado y revisable.
- Preparar una migracion progresiva desde parches en Dockerfile hacia archivos fuente claros.

## Estructura

```text
fork/
  api/
    routes/
      analitrics.js
  patches/
    conversation-cleanup.js
    direct-agent-controller.js
    files-invalidation.js
    install-analitrics-route.js
  docs/
```

## Componentes actuales

- `api/routes/analitrics.js`: endpoint LibreChat-side para exponer el contexto analitico del chat desde `analytics-agent`.
- `patches/*.js`: modificaciones controladas aplicadas sobre el build del fork fuente de LibreChat.
- El panel lateral Analitrics vive como componente React en `librechat/fork/client/src/components/Analitrics`.

## Politica de autenticacion

La ruta Analitrics no debe usar el `refreshToken` httpOnly como mecanismo propio de autenticacion.

Metodos permitidos:

- `Authorization: Bearer <jwt>` emitido por LibreChat.
- Cookie `openid_user_id` firmada por LibreChat cuando `OPENID_REUSE_TOKENS=true`.
- Sesion OpenID server-side ya presente en LibreChat.

## Parches del fork

Estos cambios se aplican desde `api/Dockerfile`, pero su codigo vive en `fork/patches`:

- `files-invalidation.js`: notifica a `analytics-agent` cuando LibreChat elimina archivos tabulares.
- `conversation-cleanup.js`: notifica a `analytics-agent` cuando LibreChat elimina una conversacion.
- `direct-agent-controller.js`: fuerza el flujo Analitrics como controlador principal del endpoint `agents`.
- `install-analitrics-route.js`: registra `/api/analitrics/*` dentro del server de LibreChat.
- `openid-tenant.js`: exige el claim OIDC configurado por `OPENID_TENANT_ID_CLAIM` y lo persiste en el usuario de LibreChat. Asi, las cargas S3 nuevas usan `t/<tenantId>/uploads/<userId>/...`.

El `api/Dockerfile` debe mantenerse como ensamblador: compilar `librechat/fork`, copiar `custom/fork/` y ejecutar parches backend. No debe acumular logica larga inline.

## Agente unico de LibreChat

LibreChat requiere que todo recurso `agent` tenga un autor persistido, incluso cuando Analitrics deriva la ejecucion al controlador directo. Por eso `make librechat up` crea de forma idempotente el principal tecnico `analitrics-system@internal.invalid` y el unico recurso `agent_analitrics`.

Ese principal no es un usuario operativo: usa `provider: system`, no tiene contrasena ni identidad OpenID, no es administrador y no existe en Keycloak. Su unica responsabilidad es ser el autor tecnico y propietario ACL del agente unico. Los usuarios reales solo reciben permiso de uso; no pueden crear, modificar ni compartir agentes.

El soporte de admin panel bajo `/admin` ya existe en el fork fuente de LibreChat mediante `packages/api/src/auth/exchange.ts`; no se parchea post-build.

## UI Analitrics

El panel lateral ya no se inyecta con JavaScript post-build. Ahora se integra en el layout React real de LibreChat mediante:

- `client/src/components/Analitrics/AnalitricsContextPanel.tsx`
- `client/src/hooks/Analitrics/useAnalitricsContext.ts`
- `client/src/components/SidePanel/SidePanelGroup.tsx`
