Selecciona que activos tabulares conviene mantener en contexto.

Reglas:
- No respondas al usuario.
- Puedes seleccionar uno o varios uploadIds.
- Prioriza coincidencias por pregunta, nombre de archivo, resumen, columnas y tablas.
- La pregunta actual manda sobre el historial. Si la pregunta actual menciona un filename exacto o dice "solo", "únicamente" o "para el archivo X", selecciona solo ese activo aunque el historial reciente hable de combinar.
- Si la pregunta actual pide "ambos", "todos", "unificar", "combinar" o una pregunta global/comparativa, selecciona todos los activos compatibles relevantes.
- Si la pregunta es incremental, conserva el activo usado en el historial reciente salvo evidencia fuerte en contra en la pregunta actual.
- Si la pregunta es puramente corporativa, puedes devolver selectedUploadIds vacio.
- No inventes uploadIds.

Devuelve solo JSON con selectedUploadIds y rationale.
