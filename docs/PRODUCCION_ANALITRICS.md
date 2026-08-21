# Despliegue productivo Analitrics v0.1

Esta guia deja el despliegue pensado para una VM donde `analitrics.com` apunta por DNS al servidor.

## Dominio y rutas publicas

- Aplicacion Analitrics: `https://analitrics.com`
- Login OIDC Keycloak: `https://analitrics.com/auth/realms/analitrics`
- Consola Keycloak: `https://analitrics.com/auth/admin/`
- LibreChat Admin Panel: `https://analitrics.com/admin`
- Logout: `https://analitrics.com/login?redirect=false`

El gateway de Analitrics publica todo bajo el mismo origen. Esto evita dominios separados para LibreChat, Keycloak y Admin Panel.

## Archivos de entorno

Crear los `.env` desde los ejemplos:

```bash
cp keycloak/.env.example keycloak/.env
cp librechat/custom/.env.example librechat/custom/.env
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

## Orden de arranque

```bash
make keycloak up
make phoenix up
make librechat up
```

`make librechat up` prepara directorios, red Docker, storage, MongoDB, Postgres de control plane, agente analitico, gateway y LibreChat.

## Configuracion inicial

1. Entrar a `https://analitrics.com/auth/admin/`.
2. Crear o importar el realm `analitrics`.
3. Configurar el cliente OIDC `librechat`.
4. Validar redirect URIs:

```text
https://analitrics.com/oauth/openid/callback
https://analitrics.com/api/admin/oauth/openid/callback
```

5. Validar post logout redirect URI:

```text
https://analitrics.com/login?redirect=false
```

6. Crear usuarios o habilitar autoregistro segun el criterio vigente del MVP.

## Validacion rapida

```bash
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
curl -k https://analitrics.com/
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
