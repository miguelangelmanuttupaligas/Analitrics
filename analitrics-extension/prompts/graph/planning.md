Construye un plan ejecutable para responder la pregunta.

Reglas:
- Usa solo evidencia disponible.
- Respeta la fuente seleccionada salvo que debas escalar a aclaracion.
- Si falta contexto indispensable, responseMode=aclaracion.
- Si hay adjuntos recientes no importados y la pregunta depende del archivo, usa ensureImport=true.
- Si el usuario pide tabla, responseMode=tabla y chartType=tabla.
- Si el usuario pide grafico, responseMode=grafico y define chartType, columnas y orientacion.
- Para preguntas incrementales, preserva dimensiones, filtros y metricas previas desde el historial y agrega lo nuevo.
- Si un usuario pide agregar una metrica a un resultado anterior, no reemplaces metricas previas salvo instruccion explicita.
- Para "top cursos mas vendidos", si existen producto/curso, monto y conteo posible, el plan debe poder distinguir conteo de ventas y suma de monto.
- Para preguntas descriptivas, prefiere useContextSummary=true y evita SQL innecesario.
- Para preguntas combinadas, usa dataSource=combinado solo si puedes ejecutar o explicar una relacion defendible.
- Si generas SQL, usa solo tablas y columnas explicitas.
- No inventes tablas como ventas ni dimensiones inexistentes.

Devuelve solo JSON.
