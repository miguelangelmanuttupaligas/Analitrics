# Analitrics

Repositorio de despliegue y personalización de Analitrics sobre LibreChat.

## Carpetas principales

- [librechat](./librechat): configuración, `.env`, `librechat.yaml` y `docker-compose`
- [analitrics-extension](./analitrics-extension): orquestador, workers IA, contexto tabular y MCP interno
- [librechat-build-src](./librechat-build-src): código fuente base de LibreChat usado para compilar la imagen personalizada
- [docs](./docs): documentación operativa y técnica

## Archivos que normalmente editarás

- [librechat/.env.prod](./librechat/.env.prod): plantilla productiva basada en `analitrics.com`
- [librechat/.env.example](./librechat/.env.example): plantilla mínima
- [librechat/librechat.yaml](./librechat/librechat.yaml): branding, modelo Analitrics y MCPs
- [librechat/docker-compose.prod.yml](./librechat/docker-compose.prod.yml): stack productivo
- [docs/nginx-analitrics.conf](./docs/nginx-analitrics.conf): sitio Nginx para `analitrics.com`
- [docs/DEPLOY_PROD.md](./docs/DEPLOY_PROD.md): guía de despliegue productivo

## Despliegue productivo

La guía principal está aquí:

- [DEPLOY_PROD.md](./docs/DEPLOY_PROD.md)

Flujo resumido:

1. Copiar el repo a `/opt/librechat`
2. Ajustar `/opt/librechat/librechat/.env`
3. Verificar `/opt/librechat/librechat/librechat.yaml`
4. Levantar `docker compose -f docker-compose.prod.yml up -d --build`
5. Reemplazar el sitio Nginx `analitrics`
6. Validar contenedores `healthy`

## Notas

- El frontend y backend de LibreChat se sirven desde `analitrics-api` en `127.0.0.1:3080`
- `rag_api` usa `vectordb` y requiere `POSTGRES_DB`, `POSTGRES_USER` y `POSTGRES_PASSWORD` mapeados desde `VECTOR_DB_*`
- La lógica del producto vive en `analitrics-extension`; los cambios recientes de esta fase fueron de infraestructura y despliegue
