# Credenciales y cuentas de prueba - Analitrics

## URLs locales

- Aplicacion Analitrics: https://analitrics-test.com:3443
- Login Keycloak/OIDC: https://analitrics-test.com:3443/auth/realms/analitrics
- Admin Console Keycloak: https://analitrics-test.com:3443/auth/admin/
- LibreChat Admin Panel: https://analitrics-test.com:3443/admin

## Keycloak bootstrap admin

- `keycloak/.env` Origen: `KC_BOOTSTRAP_ADMIN_USERNAME`, `KC_BOOTSTRAP_ADMIN_PASSWORD`
- Uso:
  - Entrar a Keycloak Admin Console.
  - Administrar realm `analitrics`.
  - Crear/editar usuarios, grupos, mappers OIDC y proveedores de identidad.

## Usuario de prueba Keycloak

- `keycloak/.env` Origen: `KEYCLOAK_TEST_USERNAME`, `KEYCLOAK_TEST_PASSWORD`
- Uso:
  - Tenant esperado: `analitrics`
  - Grupo admin esperado: `analitrics-admins`

## Usuarios observados en LibreChat

Consulta:
```bash
docker exec analitrics-analitrics-mongodb mongosh LibreChat --quiet --eval \
'db.users.find({},{_id:0,email:1,username:1,name:1,role:1,provider:1,tenantId:1}).toArray()'
```

Nota:

- Para que un usuario tenga acceso al LibreChat Admin Panel debe quedar con role `ADMIN` en LibreChat.
- La configuracion actual intenta mapearlo desde el claim/grupo `analitrics-admins`.
- Si el usuario ya existe como `USER`, puede requerir cerrar sesion, limpiar sesion OIDC y volver a entrar para que LibreChat aplique el claim actualizado.
