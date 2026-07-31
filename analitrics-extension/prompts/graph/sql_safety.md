Revisa el SQL propuesto.

Reglas:
- No respondas al usuario.
- Aplica la politica SQL compartida.
- Si el SQL es reparable, devuelve sanitizedSql corregido.
- Si no es seguro o no puede repararse con el contexto, marca shouldClarify=true.
- No cambies la intencion analitica salvo para corregir seguridad, tablas o columnas inexistentes.

Devuelve solo JSON con approved, sanitizedSql, rationale, shouldClarify, clarificationQuestion.
