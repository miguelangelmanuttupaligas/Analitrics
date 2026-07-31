Branding local aplicado sobre el frontend compilado de LibreChat.

Archivos relevantes:
- images/logo-app.png
- images/logo-login.png
- apply_branding.sh

El script parchea /app/client/dist/index.html dentro del contenedor y:
- cambia titulo y favicon
- reemplaza el logo por uno tipo DataAI4
- oculta varias rutas de la barra lateral por CSS/JS

Se ejecuta automaticamente desde run.sh despues de docker compose up -d.
