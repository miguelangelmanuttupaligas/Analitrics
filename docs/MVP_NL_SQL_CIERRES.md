# MVP NL-to-SQL: cierres pequeños

Estos puntos cierran el MVP sin agregar arquitectura innecesaria.

## 1. Graficos reales en la respuesta

Objetivo: cuando el agente genere `analitrics_chart`, LibreChat debe renderizar un grafico visible, no solo mostrar la traza.

Alcance MVP:

- Soportar graficos `bar` y `line`.
- Leer especificacion Vega-Lite simple desde `chart_spec.spec`.
- Usar `data.values` embebido en la spec.
- Mantener la traza `analitrics_chart` colapsable para auditoria.
- Si la spec no es compatible, mostrar una tarjeta de grafico sugerido sin romper el chat.

No incluye todavia:

- Editor de graficos.
- Dashboards.
- Persistencia de widgets aprobados.
- Vega-Lite completo.

## 2. Usar feedback del catalogo en el agente

Objetivo: que lo escrito por el usuario en el panel derecho afecte respuestas futuras.

Abordaje:

- Leer `analysis_catalog_feedback` por `tenant_id`, `user_id`, `conversation_id` y `source_file_id`.
- Inyectarlo al contexto del agente como definiciones confirmadas/correcciones/reglas.
- Priorizar feedback del usuario sobre inferencias automaticas.

## 3. Limpiar seleccion de modelo/agente

Objetivo: que el producto se sienta cerrado como Analitrics.

Abordaje:

- Ocultar o resolver automaticamente `Select a model`.
- Evitar `Please select an Agent`.
- Mantener `Analitrics` como unica opcion visible por ahora.

## 4. Estados de progreso mas claros

Objetivo: que el usuario vea que su pregunta esta siendo trabajada.

Abordaje:

- Mantener eventos: resolviendo archivos, cargando DuckDB, generando SQL, ejecutando consulta, redactando respuesta, generando grafico.
- Revisar que se vean en el chat durante streaming.
- Evitar mensajes tecnicos largos.

## 5. Panel derecho mas compacto

Objetivo: que el panel sea gerencial y no parezca un formulario permanente.

Abordaje:

- Mantener resumen ejecutivo arriba.
- Mostrar selector de archivo.
- Convertir "Enriquecer catalogo" a acordeones.
- Dejar solo el paso activo expandido.

## 6. Errores entendibles

Objetivo: que errores de archivo, SQL o ambiguedad sean accionables.

Abordaje:

- Traducir errores tecnicos a mensajes de negocio.
- Distinguir lectura de archivo, falta de columnas, SQL vacio, permisos y timeout.
- Cuando haya ambiguedad, pedir aclaracion en vez de inventar.
