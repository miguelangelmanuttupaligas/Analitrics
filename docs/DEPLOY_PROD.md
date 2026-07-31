# Despliegue Productivo Analitrics

## 1. Qué publicar

Carpeta base:

- `/home/miguel/DataAI5/librechat`

Repos/carpetas requeridas por `docker-compose.prod.yml`:

- `../librechat-build-src`
- `../analitrics-extension`

## 2. Variables mínimas

En `/home/miguel/DataAI5/librechat/.env` debes tener al menos:

```env
PORT=3080
RAG_PORT=8000
OPENAI_API_KEY=tu_clave_real
ANALITRICS_POSTGRES_DB=analitrics
ANALITRICS_POSTGRES_USER=analitrics
ANALITRICS_POSTGRES_PASSWORD=cambia_esta_clave
ANALITRICS_POSTGRES_PORT=5436

VECTOR_DB_NAME=mydatabase
VECTOR_DB_USER=myuser
VECTOR_DB_PASSWORD=mypassword

WORKER_MODEL=gpt-4.1-mini
CONTEXT_MAX_ASSETS=4
CONTEXT_MAX_TABLES_PER_ASSET=3
CONTEXT_MAX_COLUMNS_PER_TABLE=12
CONTEXT_MAX_SAMPLE_ROWS_PER_TABLE=3
```

## 3. PostgreSQL del stack

La instalación ahora crea una PostgreSQL propia dentro del stack Docker.

Hay dos usos distintos de PostgreSQL:

### A. PostgreSQL usada por `analitrics-extension`

Sirve para:

- guardar metadata de archivos importados;
- crear tablas `analitrics_uploads.*`;
- almacenar tus datos corporativos de demo en la misma base.

La conexión ya queda resuelta dentro del stack hacia:

- `analitrics-postgres:5432`

### B. PostgreSQL usada por el MCP visible en LibreChat

Esta conexión no sale desde el navegador.
La UI no conecta directo a PostgreSQL.

El flujo real es:

```text
Navegador
  -> LibreChat UI
  -> LibreChat backend
  -> MCP server configurado en librechat.yaml
  -> PostgreSQL interna del stack
```

En tu instalación actual, el MCP PostgreSQL está definido en:

- `/home/miguel/DataAI5/librechat/librechat.yaml`

Bloque actual:

```yaml
  analitrics-postgres:
    type: stdio
    title: "Datos corporativos PostgreSQL"
    command: npx
    args:
      - "-y"
      - "@yawlabs/postgres-mcp@latest"
    env:
      DATABASE_URL: "postgresql://analitrics:tu_clave@analitrics-postgres:5432/analitrics"
```

Eso significa:

- LibreChat levanta un proceso MCP local por `stdio`;
- ese proceso `@yawlabs/postgres-mcp` abre la conexión a PostgreSQL usando `DATABASE_URL`;
- el navegador nunca ve esas credenciales.

## 4. Qué debes editar antes de subir a producción

### Archivo 1

- `/home/miguel/DataAI5/librechat/.env`

Debes poner:

- `OPENAI_API_KEY`
- `ANALITRICS_POSTGRES_PASSWORD`

### Archivo 2

- `/home/miguel/DataAI5/librechat/librechat.yaml`

Debes reemplazar la contraseña en el `DATABASE_URL` de `analitrics-postgres` para que coincida con `ANALITRICS_POSTGRES_PASSWORD`.

Ambos, `analitrics-extension` y el MCP PostgreSQL, deben apuntar a la misma base interna para compartir:

- metadata de archivos;
- tablas importadas desde Excel/CSV;
- datos corporativos.

## 4.1 Si luego quieres volver a una PostgreSQL externa

La UI sigue sin conectar directo.
Solo tendrías que cambiar del lado servidor:

- `POSTGRES_URL` de `analitrics-extension`
- `DATABASE_URL` del bloque `analitrics-postgres` en `librechat.yaml`

El flujo seguiría siendo:

- navegador -> LibreChat -> MCP/backend -> PostgreSQL externa

## 5. Arranque en la VM

Desde:

- `/home/miguel/DataAI5/librechat`

Ejecuta:

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Verifica:

```bash
docker ps
docker logs -f analitrics-api
docker logs -f analitrics-extension
```

La web quedará sirviendo en:

- `http://127.0.0.1:3080`

## 6. Reapuntar Nginx

Si ya tienes un `sites-available/analitrics`, solo debes hacer que el `proxy_pass` apunte a:

- `http://127.0.0.1:3080`

Bloque típico:

```nginx
server {
    listen 80;
    server_name subdominio.dominio.com;

    location / {
        proxy_pass http://127.0.0.1:3080;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

Luego:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

## 7. Si usas HTTPS con certbot

Una vez que el subdominio resuelva a la VM:

```bash
sudo certbot --nginx -d subdominio.dominio.com
```

## 8. Qué puerto debe ver Nginx

Solo necesitas publicar:

- `3080/tcp`

No hace falta exponer públicamente:

- MongoDB
- VectorDB
- RAG API
- `analitrics-extension:3095`
- `analitrics-postgres:5432`

Todo eso debe quedar interno en Docker.

## 9. Resumen práctico

1. Edita `.env`
2. Edita `librechat.yaml`
3. Levanta con `docker compose -f docker-compose.prod.yml up -d --build`
4. Haz que Nginx apunte a `127.0.0.1:3080`
5. Recarga Nginx
6. Prueba el subdominio
