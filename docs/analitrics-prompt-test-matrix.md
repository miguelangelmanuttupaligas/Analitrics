# Matriz de Pruebas de Preguntas para Analitrics

Fecha de preparación: 2026-07-29

## Objetivo

Validar antes de producción que Analitrics:

- no genere gráficos cuando el usuario no los pide;
- genere tablas cuando el usuario explícitamente pide tabla;
- genere gráficos solo cuando la intención visual es clara;
- responda preguntas gerenciales y descriptivas sin desviarse a una visual;
- combine correctamente contexto de archivo cargado y contexto corporativo cuando corresponda.

## Preparación sugerida

Antes de ejecutar estas pruebas:

1. Abrir un chat nuevo.
2. Confirmar que el único modelo visible para la demo sea `Analitrics`.
3. Cargar un archivo Excel o CSV de prueba.
4. Esperar a que el archivo quede disponible en el contexto del chat.
5. Opcionalmente verificar que la conexión MCP corporativa esté operativa.

## Criterios generales de aceptación

- Si la pregunta no pide visual, no debe aparecer gráfico.
- Si la pregunta pide tabla, debe responder con tabla o con estructura tabular clara.
- Si la pregunta pide gráfico, debe responder con una visual y una explicación breve.
- Si no hay suficiente contexto, debe pedir aclaración útil o indicar que falta el archivo/fuente.
- No debe inventar tablas, columnas o conclusiones no sustentadas.

## Grupo A: Resumen y comprensión del archivo

### A1. Resumen simple

Prompt:

```text
Resume qué contiene este archivo y cuál parece ser su propósito de negocio.
```

Esperado:

- Respuesta narrativa en español.
- Sin gráfico.
- Sin tabla salvo que sea estrictamente necesaria.

Falla si:

- genera un gráfico;
- responde sobre un archivo distinto;
- dice que no tiene contexto cuando el archivo ya fue cargado.

### A2. Hallazgos ejecutivos

Prompt:

```text
Dame tres hallazgos gerenciales relevantes de este archivo.
```

Esperado:

- 3 hallazgos concretos.
- Sin gráfico.
- Sin pedir nombres de tabla o columnas al usuario.

### A3. Calidad de datos

Prompt:

```text
Identifica posibles problemas de calidad de datos en este archivo.
```

Esperado:

- Respuesta analítica.
- Puede mencionar nulos, formatos o inconsistencias.
- Sin gráfico por defecto.

## Grupo B: Preguntas que no deben generar gráfico

### B1. Conteo simple

Prompt:

```text
¿Cuántas filas tiene este archivo?
```

Esperado:

- Respuesta corta con cifra.
- Sin gráfico.

### B2. Cobertura de columnas

Prompt:

```text
¿Qué columnas importantes contiene este archivo?
```

Esperado:

- Lista o resumen de columnas.
- Sin gráfico.

### B3. Respuesta gerencial

Prompt:

```text
¿Qué debería revisar primero una gerencia antes de tomar decisiones con estos datos?
```

Esperado:

- Respuesta consultiva.
- Sin gráfico.

## Grupo C: Preguntas que deben devolver tabla

### C1. Tabla top 10

Prompt:

```text
Muéstrame una tabla con los 10 registros de mayor monto.
```

Esperado:

- Visualización tabular o respuesta estructurada como tabla.
- No gráfico.

Falla si:

- devuelve barras o torta;
- responde solo con texto sin la tabla solicitada.

### C2. Tabla agregada

Prompt:

```text
Dame una tabla con ventas totales por país, ordenada de mayor a menor.
```

Esperado:

- Tabla ordenada.
- Sin gráfico.

### C3. Tabla comparativa

Prompt:

```text
Muéstrame una tabla con país, curso y monto total.
```

Esperado:

- Tabla con esas columnas o equivalentes.
- Sin gráfico.

## Grupo D: Preguntas que sí deben generar gráfico

### D1. Ranking horizontal

Prompt:

```text
Dame un gráfico horizontal del curso más vendido por país usando monto total.
```

Esperado:

- Gráfico interactivo.
- Preferentemente barras horizontales.
- Explicación breve.

Falla si:

- devuelve solo texto;
- genera una tabla sin visual;
- grafica la dimensión equivocada.

### D2. Tendencia

Prompt:

```text
Muéstrame una tendencia mensual de ventas.
```

Esperado:

- Gráfico de líneas o equivalente temporal.
- No tabla como resultado principal.

### D3. Participación

Prompt:

```text
Muéstrame la participación por país en un gráfico.
```

Esperado:

- Torta o barras, según criterio del agente.
- Explicación breve.

## Grupo E: Preguntas ambiguas

### E1. Ambigua pero no visual

Prompt:

```text
¿Cuál es el dato más importante aquí?
```

Esperado:

- Respuesta interpretativa.
- Sin gráfico salvo que el usuario lo pida después.

### E2. Ambigua con posible visual

Prompt:

```text
Compárame los resultados principales.
```

Esperado:

- Puede responder con resumen textual.
- Puede pedir aclaración si hay varias comparaciones válidas.
- No debe saltar directamente a un gráfico sin justificarlo.

## Grupo F: Combinación archivo + datos corporativos

### F1. Enriquecimiento natural

Prompt:

```text
Usa este archivo y, si aporta valor, compáralo con los datos corporativos disponibles.
```

Esperado:

- Respuesta combinada o explicación de qué pudo cruzar.
- Sin gráfico por defecto.

### F2. Visual combinada

Prompt:

```text
Compara este archivo con los datos corporativos en un gráfico y dime la principal diferencia.
```

Esperado:

- Gráfico si el contexto corporativo está disponible.
- Explicación breve.

## Grupo G: Manejo de errores y límites

### G1. Sin archivo cargado

Prompt:

```text
Resume qué contiene este archivo.
```

Esperado:

- Debe indicar que no hay archivo activo o pedir que se cargue uno.
- No inventar contenido.

### G2. Columna inexistente

Prompt:

```text
Muéstrame ventas por región comercial avanzada.
```

Esperado:

- Debe decir que no encuentra esa dimensión o pedir precisión.
- No inventar la columna.

### G3. Petición incompatible

Prompt:

```text
Hazme un gráfico de una sola celda descriptiva del archivo.
```

Esperado:

- Debe reconducir la respuesta.
- No forzar un gráfico absurdo.

## Secuencia mínima recomendada para humo antes de producción

Ejecutar al menos estas 8 pruebas:

1. `Resume qué contiene este archivo y cuál parece ser su propósito de negocio.`
2. `¿Cuántas filas tiene este archivo?`
3. `Muéstrame una tabla con los 10 registros de mayor monto.`
4. `Dame una tabla con ventas totales por país, ordenada de mayor a menor.`
5. `Dame un gráfico horizontal del curso más vendido por país usando monto total.`
6. `Muéstrame una tendencia mensual de ventas.`
7. `¿Qué debería revisar primero una gerencia antes de tomar decisiones con estos datos?`
8. `Usa este archivo y, si aporta valor, compáralo con los datos corporativos disponibles.`

## Formato sugerido para registrar resultados

| ID | Prompt | Resultado esperado | Resultado observado | Estado |
|---|---|---|---|---|
| A1 | Resume qué contiene este archivo... | Texto sin gráfico |  |  |
| C1 | Muéstrame una tabla con los 10 registros... | Tabla |  |  |
| D1 | Dame un gráfico horizontal... | Gráfico interactivo |  |  |

## Recomendación operativa

Si una prueba falla, registrar:

- prompt exacto;
- si había archivo cargado;
- si había fuente corporativa activa;
- tipo de error observado:
  - generó gráfico cuando no debía,
  - no generó gráfico cuando debía,
  - devolvió tabla cuando no correspondía,
  - inventó contexto,
  - pidió columnas que ya debía inferir,
  - error técnico.
