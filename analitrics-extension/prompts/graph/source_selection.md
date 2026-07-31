Elige la fuente de datos mas adecuada.

Modos validos:
- archivo: responder solo con archivos/tablas cargadas.
- corporativo: responder solo con datos corporativos PostgreSQL.
- combinado: unir ambos contextos de forma defendible.
- ninguno: no existe base suficiente.

Reglas:
- Elige combinado solo si la pregunta realmente requiere ambos mundos o si hay relacion analitica clara.
- Si el usuario pregunta por el archivo cargado, prioriza archivo.
- Si la pregunta es incremental, conserva la fuente anterior inferible del historial.
- No inventes joins ni correspondencias entre archivo y corporativo.

Devuelve solo JSON con mode, rationale, needsClarification y clarificationQuestion.
