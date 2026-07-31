# Despliegue Productivo Analitrics

## 1. Estructura que debes copiar

La instalación productiva usa estas carpetas del repo:

- `./librechat`
- `./librechat-build-src`
- `./analitrics-extension`
- `./docs`

El `docker-compose.prod.yml` vive en:

- `./librechat/docker-compose.prod.yml`

## 2. Archivos principales de producción

- `.env` o `.env.prod`
  Ruta repo: `./librechat/.env`
- `librechat.yaml`
  Ruta repo: `./librechat/librechat.yaml`
- `docker-compose.prod.yml`
  Ruta repo: `./librechat/docker-compose.prod.yml`
- `nginx-analitrics.conf`
  Ruta repo: `./docs/nginx-analitrics.conf`
  Destino VM: `/etc/nginx/sites-available/analitrics`

## 3. Variables mínimas

En `./librechat/.env` debes tener al menos:

```env
HOST=0.0.0.0
PORT=3080
DOMAIN_CLIENT=https://analitrics.com
DOMAIN_SERVER=https://analitrics.com
PUBLIC_IP=167.86.78.111
PUBLIC_DOMAIN=analitrics.com

OPENAI_API_KEY=tu_clave_real
RAG_OPENAI_API_KEY=tu_clave_real

JWT_SECRET=64_hex
JWT_REFRESH_SECRET=64_hex
CREDS_KEY=64_hex
CREDS_IV=32_hex

VECTOR_DB_NAME=analitrics_rag
VECTOR_DB_USER=analitrics_rag
VECTOR_DB_PASSWORD=cambia_esta_clave

ANALITRICS_POSTGRES_DB=analitrics
ANALITRICS_POSTGRES_USER=analitrics
ANALITRICS_POSTGRES_PASSWORD=cambia_esta_clave
ANALITRICS_POSTGRES_PORT=5436

WORKER_MODEL=gpt-4.1-mini
CONTEXT_MAX_ASSETS=4
CONTEXT_MAX_TABLES_PER_ASSET=3
CONTEXT_MAX_COLUMNS_PER_TABLE=12
CONTEXT_MAX_SAMPLE_ROWS_PER_TABLE=3
```

## 4. Cómo usa PostgreSQL el stack

Hay tres usos distintos:

### A. `analitrics-postgres`

Es la PostgreSQL principal del producto.
Guarda:

- metadata de archivos importados
- tablas `analitrics_uploads.*`
- datos corporativos

### B. MCP PostgreSQL de LibreChat

LibreChat no conecta desde el navegador a la base.
El flujo es:

```text
Navegador
  -> LibreChat UI
  -> LibreChat backend
  -> MCP PostgreSQL
  -> analitrics-postgres
```

La contraseña definida en `librechat.yaml` debe coincidir con:

- `ANALITRICS_POSTGRES_PASSWORD`

### C. `rag_api` + `vectordb`

El RAG no usa la PostgreSQL principal.
Usa su propia base vectorial `vectordb`.

Importante:

- `vectordb` necesita `VECTOR_DB_*`
- `rag_api` también necesita explícitamente:
  - `POSTGRES_DB`
  - `POSTGRES_USER`
  - `POSTGRES_PASSWORD`

Eso ya quedó mapeado dentro de `docker-compose.prod.yml`.

## 5. Levantar la instalación

Desde:

- `./librechat`

Ejecuta:

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Verifica:

```bash
docker compose -f docker-compose.prod.yml ps
docker logs --tail 100 analitrics-api
docker logs --tail 100 analitrics-extension
docker logs --tail 100 analitrics-rag-api
```

Healthchecks esperados:

- `analitrics-mongodb`: `healthy`
- `analitrics-vectordb`: `healthy`
- `analitrics-rag-api`: `healthy`
- `analitrics-postgres`: `healthy`
- `analitrics-extension`: `healthy`
- `analitrics-api`: `healthy`

La app queda sirviendo en:

- `http://127.0.0.1:3080`

## 6. Nginx en una VM ya gestionada por Certbot

Si tu dominio `analitrics.com` ya existe y Certbot ya tocó el sitio, no necesitas rehacer SSL.
Solo cambias el upstream del sitio `analitrics` para que apunte a:

- `http://127.0.0.1:3080`

Template listo:

- [nginx-analitrics.conf](./nginx-analitrics.conf)

Destino en VM:

- `/etc/nginx/sites-available/analitrics`

Ese template sigue el patrón de un sitio ya manejado por Certbot:

- `server_name analitrics.com`
- bloque `443 ssl` con certificados existentes
- bloque `80` con redirección a HTTPS
- `proxy_pass http://127.0.0.1:3080`
- soporte WebSocket
- `client_max_body_size 100M`

Aplicación:

```bash
sudo cp ./docs/nginx-analitrics.conf /etc/nginx/sites-available/analitrics
sudo nginx -t
sudo systemctl reload nginx
```

## 7. Si necesitas reemitir o reparar el certificado

Solo si el certificado ya no existiera o estuviera roto:

```bash
sudo certbot --nginx -d analitrics.com
sudo nginx -t
sudo systemctl reload nginx
```

## 8. Puertos expuestos

Solo debe quedar expuesto públicamente:

- `3080/tcp` a través de Nginx

No expongas públicamente:

- MongoDB
- VectorDB
- RAG API
- `analitrics-extension:3095`
- `analitrics-postgres:5432`

## 9. Volúmenes persistentes definitivos

El stack productivo usa nombres fijos:

- `analitrics_mongodb_data`
- `analitrics_uploads_data`
- `analitrics_logs_data`
- `analitrics_rag_pgdata`
- `analitrics_postgres_data`

Esos son los volúmenes que debes respaldar si luego quieres migrar la instalación o conservar estado.

## 10. Reset limpio de la instalación

Si necesitas reconstruir completamente solo este stack:

```bash
cd ./librechat
docker compose -f docker-compose.prod.yml down --remove-orphans
docker volume rm analitrics_mongodb_data analitrics_uploads_data analitrics_logs_data analitrics_rag_pgdata analitrics_postgres_data
docker compose -f docker-compose.prod.yml up -d --build
```

## 11. Resumen corto

1. Copia el repo al directorio destino de tu VM
2. Completa `.env` o usa `.env.prod` como base
3. Revisa `librechat.yaml` para que el `DATABASE_URL` del MCP use la misma clave de `ANALITRICS_POSTGRES_PASSWORD`
4. Levanta `docker compose -f docker-compose.prod.yml up -d --build`
5. Reemplaza `/etc/nginx/sites-available/analitrics` con el template del repo
6. Recarga Nginx
7. Verifica que todos los contenedores estén `healthy`
