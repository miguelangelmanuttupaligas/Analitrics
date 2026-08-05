# Deuda futura: compaction worker y memoria estructurada

## Contexto

El flujo productivo actual `direct_file` usa fuerza bruta de contexto para estabilizar respuestas:

- hasta 5 archivos activos;
- hasta 60 mensajes recientes;
- hasta 4000 caracteres por mensaje;
- metadata tabular enriquecida por archivo, hoja y columna.

Esto es aceptable para MVP, pero no escala indefinidamente en costo, latencia ni precisión. Cuando una conversación crece, el modelo recibe demasiado historial bruto y puede mezclar decisiones antiguas, aclaraciones obsoletas o respuestas previas incorrectas.

## Deuda

Implementar un `conversation_compaction_worker` y una memoria estructurada por conversación para que `direct_file` pueda seguir funcionando de forma estable durante más tiempo sin depender solo de enviar historial bruto.

## Objetivo

Mantener suficiente contexto conversacional y técnico para responder bien, pero enviando al modelo:

- últimos mensajes completos;
- resumen estructurado de la conversación anterior;
- decisiones y aclaraciones vigentes;
- archivos activos;
- metadata/catálogo relevante.

## Componentes Requeridos

### 1. Tabla de memoria estructurada

Guardar por `conversation_id` y `user_id` un estado compacto, versionado y auditable.

Contenido esperado:

- archivos activos y propósito conocido;
- nombres de tablas físicas asociadas;
- columnas relevantes y tipos conocidos;
- aclaraciones confirmadas por usuario;
- decisiones semánticas vigentes;
- supuestos de negocio;
- preguntas frecuentes ya resueltas;
- errores o ambigüedades detectadas.

### 2. Compaction worker

Worker LLM que reciba:

- memoria estructurada anterior;
- bloque de mensajes recientes aún no compactados;
- últimos `agent_runs`;
- assets/tablas/columnas disponibles.

Debe producir JSON estructurado, no texto libre.

Ejemplo objetivo:

```json
{
  "activeFiles": [
    "data_2024_2026.xlsx",
    "ventas_2024_convertidas_a_2023.xlsx"
  ],
  "confirmedClarifications": [
    "FECHA_REGISTRO es la columna que debe usarse para extraer el año de venta.",
    "Cuando el usuario diga ambos archivos en este chat, se refiere a los dos Excels de ventas."
  ],
  "columnKnowledge": {
    "fecha_registro": {
      "data_2024_2026.xlsx": "timestamptz",
      "ventas_2024_convertidas_a_2023.xlsx": "text con formato DD/MM/YYYY HH24:MI:SS"
    },
    "producto": {
      "businessMeaning": "curso/producto vendido"
    },
    "monto": {
      "businessMeaning": "importe monetario de la venta"
    }
  },
  "semanticAssumptions": [
    "curso normalmente se refiere a producto, no necesariamente a tipo_producto"
  ],
  "knownResults": [
    "El curso más vendido por año en ambos archivos fue Especialización en Power BI para 2023, 2024 y 2025."
  ],
  "pendingClarification": null
}
```

### 3. Integración con `ContextSnapshot`

`ContextSnapshot` debe incluir:

- memoria compactada;
- últimos mensajes completos;
- assets activos;
- metadata tabular;
- historial reciente no compactado.

El snapshot no debe depender solo de recencia.

### 4. Política de Retención

Propuesta inicial:

- mantener últimos 20-30 mensajes completos;
- compactar mensajes más antiguos;
- preservar literalmente mensajes con archivos adjuntos;
- preservar literalmente aclaraciones explícitas;
- descartar conversación social o texto sin efecto analítico;
- recompactar cada N turnos o cuando el prompt supere un umbral.

### 5. Observabilidad

Registrar:

- cuándo se compactó;
- qué mensajes cubre;
- tokens usados;
- versión del resumen;
- cambios principales contra la memoria anterior;
- worker/modelo utilizado.

## Criterios de Éxito

- Una conversación larga mantiene decisiones de usuario aunque ya no estén en los últimos mensajes.
- El modelo no pregunta nuevamente aclaraciones ya respondidas.
- El modelo no mezcla archivos antiguos fuera del estado vigente.
- Se reduce el tamaño promedio de prompts sin degradar calidad.
- `direct_file` conserva precisión en pruebas multiarchivo y aclaraciones largas.

## Riesgos

- Una mala compactación puede borrar información importante.
- Un resumen demasiado libre puede introducir supuestos falsos.
- Si no se versiona, será difícil auditar por qué una respuesta usó cierto contexto.
- Si se compactan mensajes con archivos adjuntos sin preservar referencias, se puede perder trazabilidad.

## Estado

No implementado.

Prioridad recomendada: alta después del MVP multiarchivo, antes de intentar soportar conversaciones largas o multiusuario en producción real.
