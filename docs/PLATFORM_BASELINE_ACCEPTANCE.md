# Platform Baseline Acceptance

No se debe validar una mejora del agente hasta aprobar estas comprobaciones en la ruta real de produccion o preproduccion.

## Automatizado en cada cambio

- `npm run test:wrapper` desde `analitrics-adapter`: confirma que el wrapper reenvia el cuerpo JSON de `DELETE /api/files` a LibreChat.
- `make librechat up`: no termina hasta que la API responde a su healthcheck.
- `docker compose ... config -q`: valida la composicion del stack.

## Validacion end-to-end obligatoria

1. Abrir la URL publica e iniciar sesion con Keycloak.
2. Confirmar que el usuario autenticado tiene `tenantId` en Mongo.
3. Cargar un CSV o XLSX y comprobar en Mongo: `tenantId`, propietario y `storageKey` con prefijo `t/<tenantId>/uploads/<userId>/`.
4. Eliminar el archivo desde la interfaz, recargar la pagina y confirmar que no vuelve a aparecer.
5. Confirmar que el documento no existe en `LibreChat.files` y que el objeto no existe en RustFS.
6. Cerrar sesion, iniciar sesion otra vez y comprobar que no se muestra un formulario local de LibreChat.

## Criterio de bloqueo

Un `200` o `204` HTTP no es suficiente. La operacion de borrado solo pasa cuando la UI recargada, Mongo y RustFS coinciden en que el archivo ya no existe.
