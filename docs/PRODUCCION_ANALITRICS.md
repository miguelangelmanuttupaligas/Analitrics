# Despliegue productivo Analitrics v0.1

Esta guia deja el despliegue pensado para una VM donde `analitrics.com` apunta por DNS al servidor.

## Dominio y rutas publicas

- Aplicacion Analitrics: `https://analitrics.com`
- Login OIDC Keycloak: `https://analitrics.com/auth/realms/analitrics`
- Consola Keycloak: `https://analitrics.com/auth/admin/`
- LibreChat Admin Panel: `https://analitrics.com/admin`
- Logout: `https://analitrics.com/login?redirect=false`

El gateway de Analitrics publica todo bajo el mismo origen. Esto evita dominios separados para LibreChat, Keycloak y Admin Panel.

## Repositorio GitHub

El remoto actual apunta a un repositorio llamado `librechat`. No conviene publicar este producto allí: el repositorio de Analitrics debe ser independiente y privado.

1. Crear un repositorio vacío privado, por ejemplo `github.com/<organizacion>/analitrics`.
2. Desde la copia local, preservar el remoto actual como referencia y agregar el nuevo remoto del producto:

```bash
git remote rename origin librechat-fork
git remote add origin git@github.com:<organizacion>/analitrics.git
git push -u origin master
```

No se versionan `.env`, certificados, credenciales ni resultados bajo `tmp/`. Antes del primer `push`, revisar el conjunto real de cambios:

```bash
git status --short
git diff --check
```

## Archivos de entorno

La plantilla local sigue usando `analitrics-test.com:3443`. En la VM se deben usar exclusivamente las plantillas de producción:

```bash
cp keycloak/.env.production.example keycloak/.env
cp librechat/custom/.env.production.example librechat/custom/.env
```

Valores esperados en produccion:

```env
PUBLIC_HOST=analitrics.com
PUBLIC_ORIGIN=https://analitrics.com
PUBLIC_PORT=443
DOMAIN_CLIENT=https://analitrics.com
DOMAIN_SERVER=https://analitrics.com
ADMIN_PANEL_URL=https://analitrics.com/admin
OPENID_ISSUER=https://analitrics.com/auth/realms/analitrics
OPENID_POST_LOGOUT_REDIRECT_URI=https://analitrics.com/login?redirect=false
KC_HOSTNAME=https://analitrics.com/auth
KC_HOSTNAME_ADMIN=https://analitrics.com/auth
```

Generar secretos reales para todos los valores `replace-with-*` antes de levantar servicios. No versionar los `.env`.

`KEYCLOAK_LIBRECHAT_CLIENT_SECRET` en `keycloak/.env` y `OPENID_CLIENT_SECRET` en `librechat/custom/.env` deben contener exactamente el mismo valor. Este secreto crea el cliente OIDC `librechat` durante el primer arranque de Keycloak.

La VM no usa Ollama ni otro servidor local: dejar `ANALITRICS_LLM_PROVIDER=openai`, definir `OPENAI_API_KEY` y el modelo OpenAI elegido.

## Nginx y TLS en la VM

Esta VM ya tiene Nginx compartido para otros dominios. Ese Nginx conserva los puertos públicos `80/443` y el certificado existente de Certbot:

```text
/etc/letsencrypt/live/analitrics.com/fullchain.pem
/etc/letsencrypt/live/analitrics.com/privkey.pem
```

El gateway Docker recibe tráfico de la aplicación solo en `127.0.0.1:3090`; Nginx del host hace proxy HTTP hacia ese puerto y termina TLS públicamente. El gateway además conserva `127.0.0.1:3443` con TLS interno para que LibreChat pueda descubrir el issuer OIDC `https://analitrics.com/auth/...` sin salir de Docker. Ese segundo puerto nunca se publica a Internet.

Copiar el certificado existente también al volumen del gateway interno:

```bash
make prepare-dirs
sudo install -m 644 /etc/letsencrypt/live/analitrics.com/fullchain.pem \
  /var/analitrics/librechat/certs/analitrics.crt
sudo install -m 600 /etc/letsencrypt/live/analitrics.com/privkey.pem \
  /var/analitrics/librechat/certs/analitrics.key
```

El site versionado está en [analitrics.com.conf](../deploy/nginx/analitrics.com.conf). Antes de cambiarlo, conservar una copia fuera de `sites-enabled`:

```bash
sudo install -d -m 700 /root/analitrics-migration-backup
sudo cp -a /etc/nginx/sites-enabled/analitrics.com \
  /root/analitrics-migration-backup/analitrics.com.legacy
```

Después de desplegar los contenedores nuevos, instalar el site, validar y recargar Nginx:

```bash
sudo install -m 644 deploy/nginx/analitrics.com.conf /etc/nginx/sites-enabled/analitrics.com
sudo nginx -t
sudo systemctl reload nginx
```

No se debe detener Nginx. Certbot y la renovación pública siguen siendo responsabilidad del Nginx del host. Como el gateway interno usa una copia de ese certificado para el discovery OIDC, instalar este hook una vez para sincronizarla después de cada renovación exitosa:

```bash
sudo install -d -m 755 /etc/letsencrypt/renewal-hooks/deploy
sudo tee /etc/letsencrypt/renewal-hooks/deploy/analitrics-gateway-cert.sh >/dev/null <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

domain="analitrics.com"
cert_dir="/etc/letsencrypt/live/${domain}"
target_dir="/var/analitrics/librechat/certs"

install -m 644 "${cert_dir}/fullchain.pem" "${target_dir}/analitrics.crt"
install -m 600 "${cert_dir}/privkey.pem" "${target_dir}/analitrics.key"

systemctl reload nginx
docker restart analitrics-analitrics-gateway
EOF
sudo chmod 700 /etc/letsencrypt/renewal-hooks/deploy/analitrics-gateway-cert.sh
```

Se puede probar el hook sin renovar el certificado:

```bash
sudo /etc/letsencrypt/renewal-hooks/deploy/analitrics-gateway-cert.sh
curl --resolve analitrics.com:3443:127.0.0.1 \
  -I https://analitrics.com:3443/auth/realms/analitrics/.well-known/openid-configuration
```

No ejecutar `certbot renew --dry-run --run-deploy-hooks`: podría sincronizar un certificado de staging con el gateway interno.

## Primer arranque

Antes de iniciar:

1. El DNS `analitrics.com` debe resolver a la IP pública de la VM.
2. Los puertos TCP `80` y `443` deben estar permitidos por el firewall o security group.
3. Nginx del host debe seguir activo y el site `analitrics.com` debe hacer proxy a `127.0.0.1:3090`.
4. El certificado existente de Certbot debe seguir legible por Nginx del host.

Al iniciar Keycloak por primera vez, importa [analitrics-realm.json](../keycloak/realm/analitrics-realm.json). El importador crea:

- realm `analitrics` en español;
- cliente OIDC confidencial `librechat`;
- redirects para `https://analitrics.com`;
- claim `tenantId=analitrics`;
- claim `groups` y grupo `analitrics-admins`;
- autoregistro y recuperación de contraseña habilitados.

El import solo crea realms ausentes. Una vez persistida la base de Keycloak, no sobrescribe cambios administrativos hechos desde la consola.

## Orden de arranque

```bash
make keycloak up
make phoenix up
make librechat up
```

`make librechat up` prepara directorios, red Docker, storage, MongoDB, Postgres de control plane, agente analitico, gateway y LibreChat.

## Migraciones del Control Plane

El control plane es el Postgres de Analitrics que conserva catalogos, feedback, estados analiticos y dashboards. Su esquema se versiona mediante Alembic en `analitrics-app/migrations/`.

Ejecutar una migracion solo cuando el `git pull` traiga una nueva revision dentro de esa carpeta. No se debe ejecutar antes de cada despliegue si no hay cambios de esquema.

En una actualizacion con migraciones:

```bash
cd /opt/Analitrics
git pull --ff-only origin master

# Asegura que control-postgres este disponible.
make librechat up

# Aplica todas las revisiones pendientes con el usuario administrador del control plane.
make control-plane-migrate

# Reafirma los permisos de solo lectura del usuario de runtime.
make control-plane-grants

# Recrea los servicios si el cambio tambien actualizo imagenes o configuracion.
make librechat up
```

`make control-plane-migrate` ejecuta `alembic upgrade head` desde una imagen efimera. No modifica el esquema desde el contenedor del agente durante una conversacion. `make control-plane-grants` mantiene al usuario de runtime sin permisos DDL, por lo que el agente no puede alterar tablas, catalogos ni migraciones. `make librechat up` lo invoca siempre despues de levantar el control plane para sincronizar la contrasena de `analitrics_runtime` con el `.env` activo.

Antes de aplicar una migracion relevante, revisar las revisiones entrantes y respaldar el Postgres de control plane:

```bash
git fetch origin
git diff --name-only HEAD..origin/master -- analitrics-app/migrations/

set -a
source <(grep -v '^UID=' librechat/custom/.env)
set +a
docker exec -e PGPASSWORD="$ANALITRICS_POSTGRES_ADMIN_PASSWORD" \
  analitrics-analitrics-control-postgres \
  pg_dump -U "$ANALITRICS_POSTGRES_ADMIN_USER" "$ANALITRICS_POSTGRES_DB" \
  > /root/analitrics-control-plane-$(date +%F-%H%M%S).sql
```

Nunca incluir el backup ni los secretos en Git.

## Reemplazo del MVP antiguo

En la VM identificada, el MVP anterior corresponde al proyecto Compose `librechat` con archivo `/opt/librechat/librechat/docker-compose.yml`. Detenerlo sin borrar contenedores, redes ni volúmenes:

```bash
docker compose -f /opt/librechat/librechat/docker-compose.yml stop
```

No usar `down -v`. El proyecto Odoo no forma parte de esta migración y no debe detenerse.

Con el repositorio nuevo en `/opt/Analitrics`, crear los `.env` de producción, completar secretos y levantar el stack:

```bash
cd /opt/Analitrics
cp keycloak/.env.production.example keycloak/.env
cp librechat/custom/.env.production.example librechat/custom/.env

# Editar ambos .env, generando secretos reales y usando el mismo secreto OIDC.
make keycloak up
make phoenix up
make librechat up
```

Antes de cambiar el site público, confirmar que el gateway nuevo responde únicamente en loopback:

```bash
curl -I http://127.0.0.1:3090/
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
```

Luego instalar [analitrics.com.conf](../deploy/nginx/analitrics.com.conf), validar la sintaxis y recargar Nginx. Si hubiera una incidencia, restaurar el archivo de `/root/analitrics-migration-backup/` y ejecutar `sudo systemctl reload nginx`; el MVP antiguo permanece detenido pero recuperable con `docker compose ... start`.

## Servicios administrativos por localhost

Los servicios de administracion/diagnostico no deben publicarse en `0.0.0.0`. Para poder accederlos por tunel SSH desde la VM, quedan publicados solo en `127.0.0.1`:

```text
Postgres control plane: 127.0.0.1:55432 -> control-postgres:5432
Phoenix UI:            127.0.0.1:6006  -> phoenix:6006
Phoenix OTLP/gRPC:     127.0.0.1:4317  -> phoenix:4317
RustFS Console:        127.0.0.1:9001  -> storage-rustfs:9001/rustfs/console/
```

Ejemplos de tunel desde tu maquina local hacia la VM:

```bash
ssh -L 6006:127.0.0.1:6006 usuario@IP_PUBLICA_VM
ssh -L 9001:127.0.0.1:9001 usuario@IP_PUBLICA_VM
ssh -L 55432:127.0.0.1:55432 usuario@IP_PUBLICA_VM
```

URLs locales despues del tunel:

```text
Phoenix:        http://127.0.0.1:6006
RustFS Console: http://127.0.0.1:9001/rustfs/console/
Postgres:       127.0.0.1:55432
```

El `gateway` si debe quedar publico en produccion, porque es la entrada HTTPS de `https://analitrics.com`.

## Configuración inicial

1. Entrar a `https://analitrics.com/auth/admin/` con las credenciales `KC_BOOTSTRAP_ADMIN_*`.
2. Confirmar que existe el realm `analitrics` y el cliente `librechat`.
3. Validar redirect URIs:

```text
https://analitrics.com/oauth/openid/callback
https://analitrics.com/api/admin/oauth/openid/callback
```

4. Validar post logout redirect URI:

```text
https://analitrics.com/login?redirect=false
```

5. Para habilitar LibreChat Admin Panel, asignar el usuario administrativo al grupo `analitrics-admins` y habilitar en `librechat/custom/.env`:

```env
OPENID_ADMIN_ROLE=analitrics-admins
OPENID_ADMIN_ROLE_PARAMETER_PATH=groups
OPENID_ADMIN_ROLE_TOKEN_KIND=id
```

Reiniciar LibreChat después de editarlo: `make librechat down && make librechat up`.

## Creación de cuentas

Sí, el flujo de creación de cuenta está permitido hoy. `https://analitrics.com/login` redirige a Keycloak y desde ahí el usuario puede seleccionar **Crear cuenta**.

- Keycloak crea la identidad; LibreChat no mantiene un segundo formulario de registro.
- El correo es el identificador de inicio de sesión.
- Todo usuario autocreado recibe el claim `tenantId=analitrics` en este MVP.
- La recuperación de contraseña está visible, pero requiere SMTP real del realm para enviar el correo.
- Para cerrar el registro futuro, en Keycloak ir a `Realm settings` -> `Login` y desactivar `User registration`. El login existente seguirá funcionando.

## Validacion rapida

```bash
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
curl -I https://analitrics.com/
```

Desde navegador:

1. Abrir `https://analitrics.com`.
2. Confirmar redireccion a Keycloak.
3. Iniciar sesion.
4. Crear chat, cargar `.xlsx` o `.csv`, preguntar sobre los datos.
5. Confirmar que el panel derecho muestra el resumen ejecutivo/catalogo.

## Consideraciones de v0.1

- El tenant por defecto sigue siendo `analitrics`.
- RustFS guarda archivos fuente.
- MongoDB conserva metadata operativa de LibreChat.
- Postgres de control plane conserva catalogo, profiling y feedback analitico.
- DuckDB se genera por `conversationId`.
- Al borrar chat, se elimina el contexto derivado asociado.
- El agente analitico no ejecuta shell/Python arbitrario y lee S3 con credenciales de solo lectura.
