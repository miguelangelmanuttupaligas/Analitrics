# DirectFlow Legacy Notes

Este documento rescata aprendizajes del MVP anterior basado en `analitrics-extension`, `librechat-build-src` y lógica DirectFlow. El código de esa etapa no forma parte del contrato activo.

## Qué hacía DirectFlow

El flujo anterior intentaba:

- detectar archivos cargados por el usuario en LibreChat;
- resolver `userId`, `conversationId`, archivos recientes y contexto del chat;
- ingerir CSV/XLS/XLSX;
- perfilar datos tabulares;
- pedir al LLM planificación SQL o intención de gráfico;
- validar parcialmente SQL;
- generar una respuesta final con texto, tabla o guía de gráfico.

## Aprendizajes útiles

- La lógica analítica no debe vivir dentro de LibreChat.
- Un adaptador Node cerca de LibreChat es útil solo para resolver contexto del runtime y transportar requests.
- La lógica de profiling, NL-SQL, validación, ejecución y crítica debe concentrarse en Python.
- CSV y Excel no deben tratarse como texto bruto para análisis tabular.
- Excel pierde demasiada estructura si se convierte a texto: hojas, tipos, celdas vacías, fórmulas, merges y formatos.
- El LLM debe trabajar contra catálogo, schema, muestras pequeñas y herramientas de consulta, no contra el archivo completo.
- El SQL debe validarse como solo lectura antes de ejecutarse.
- El feedback del usuario debe convertirse en diccionario/catálogo confirmado, no quedar enterrado en el historial del chat.

## Qué no se migra

- Workers TypeScript del MVP anterior.
- Prompts acoplados a la implementación vieja.
- Overrides del fork anterior de LibreChat.
- Persistencia tabular anterior en PostgreSQL.
- MCP server anterior.
- DirectFlow como flujo monolítico.

## Qué se conserva como dirección

El nuevo flujo debe reconstruir esas capacidades de forma más simple:

```text
LibreChat
  -> analitrics-adapter
  -> analitrics-app Python
    -> RustFS
    -> DuckDB
    -> profiling/catalog/dictionary
    -> SQL validation
    -> answer/critique
```

El foco actual es archivos cargados por usuario. Las bases de datos externas quedan fuera hasta diseñar un contrato separado.
