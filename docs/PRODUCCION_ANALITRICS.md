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

## TLS

El gateway espera certificados en:

```text
/var/analitrics/librechat/certs/analitrics.crt
/var/analitrics/librechat/certs/analitrics.key
```

En produccion deben ser certificados validos para `analitrics.com`. El certificado autofirmado local no debe usarse en la VM publica.

### Obtener certificado con Certbot

Primero validar que el DNS apunte a la VM:

```text
analitrics.com -> IP_PUBLICA_VM
```

Instalar Certbot:

```bash
sudo apt update
sudo apt install certbot
```

Emitir certificado con modo standalone. El puerto `80` debe estar libre temporalmente:

```bash
sudo certbot certonly --standalone -d analitrics.com
```

Certbot genera:

```text
/etc/letsencrypt/live/analitrics.com/fullchain.pem
/etc/letsencrypt/live/analitrics.com/privkey.pem
```

### Opcion simple: copiar certificados

Funciona con el `docker-compose.yml` actual:

```bash
sudo mkdir -p /var/analitrics/librechat/certs

sudo cp /etc/letsencrypt/live/analitrics.com/fullchain.pem \
  /var/analitrics/librechat/certs/analitrics.crt

sudo cp /etc/letsencrypt/live/analitrics.com/privkey.pem \
  /var/analitrics/librechat/certs/analitrics.key

sudo chmod 644 /var/analitrics/librechat/certs/analitrics.crt
sudo chmod 600 /var/analitrics/librechat/certs/analitrics.key
```

Esta opcion requiere volver a copiar los archivos cuando Certbot renueve el certificado.

### Opcion recomendada: montar `/etc/letsencrypt`

No basta con crear symlinks desde `/var/analitrics/librechat/certs` hacia `/etc/letsencrypt/live/...`, porque el contenedor solo ve las rutas montadas. El symlink puede quedar roto dentro de Docker.

Para evitar copias manuales, montar `/etc/letsencrypt` en el gateway como solo lectura:

```yaml
gateway:
  volumes:
    - /etc/letsencrypt:/etc/letsencrypt:ro
```

Y cambiar el Nginx del gateway para leer directamente:

```nginx
ssl_certificate /etc/letsencrypt/live/analitrics.com/fullchain.pem;
ssl_certificate_key /etc/letsencrypt/live/analitrics.com/privkey.pem;
```

Con este enfoque, la renovacion de Certbot queda disponible para el contenedor. Luego de renovar, recargar o reiniciar el gateway:

```bash
docker restart analitrics-analitrics-gateway
```

## Primer arranque

Antes de iniciar:

1. El DNS `analitrics.com` debe resolver a la IP pública de la VM.
2. Los puertos TCP `80` y `443` deben estar permitidos por el firewall o security group.
3. Ningún Nginx/Apache del host debe ocupar los puertos `80` y `443`; el gateway Docker de Analitrics será el único endpoint público.
4. Deben existir los certificados válidos en `/var/analitrics/librechat/certs/analitrics.crt` y `/var/analitrics/librechat/certs/analitrics.key`.

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
