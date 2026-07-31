# LibreChat Local

Despliegue local de `LibreChat` con `docker compose`, aislado del resto del repo.

## URLs

- Chat: `http://localhost:3080`

## Archivos

- `docker-compose.yml`: stack local con LibreChat, MongoDB, Meilisearch, pgvector y RAG API.
- `.env`: configuracion activa local.
- `.env.example`: plantilla para replicar el despliegue.
- `librechat.yaml`: configuracion basica del frontend/endpoints.

## Arranque

```bash
cd external_apps/librechat
./run.sh
```

## Parada

```bash
cd external_apps/librechat
./stop.sh
```

## Importante

- El chat arranca sin una clave OpenAI fija porque `OPENAI_API_KEY=user_provided`.
- Para que funcionen las cargas de `CSV/XLSX`, debes rellenar `RAG_OPENAI_API_KEY` en `.env`.
- La siguiente fase de integracion con `PostgreSQL` conviene hacerla como herramienta/controlador adicional, no abriendo SQL libre al modelo.
