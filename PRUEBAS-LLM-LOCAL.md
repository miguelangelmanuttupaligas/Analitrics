# Pruebas LLM Local Analitrics

Objetivo: ejecutar 10 conversaciones largas, una por una, usando LLM local, dos archivos Excel y trazas en Phoenix.

Reglas:

- No ejecutar en paralelo.
- Usar siempre `ANALITRICS_LLM_PROVIDER=local`.
- Mantener `ANALITRICS_TRACING_ENABLED=true`.
- Usar `ANALITRICS_DEBUG_LLM_STATS=true` para dejar tokens/duración también en stderr.
- Guardar cada turno en `tmp/llm-local/<conversation>/turn-XX.json` y `turn-XX.err`.
- Cada conversación usa el mismo `CONVERSATION_ID` en todos sus turnos para probar continuidad.
- Archivos usados:
  - `data_2023.xlsx`
  - `data_2024_2026.xlsx`

Preparación:

Estas baterías simulan conversaciones largas. Con `OLLAMA_CONTEXT_LENGTH=8192`, la Conversación 01 falló desde el turno 08 por exceso de contexto. Para ejecutar las 10 baterías completas sin recortar contexto, usar al menos `16384`; si el hardware lo tolera, `32768` deja más margen.

Comandos recomendados para ajustar Ollama en host:

```bash
sudo systemctl edit ollama
```

Contenido:

```ini
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
Environment="OLLAMA_MODELS=/home/miguel/.ollama/models"
Environment="OLLAMA_CONTEXT_LENGTH=16384"
```

Aplicar:

```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama
ollama ps
```

```bash
mkdir -p tmp/llm-local
make phoenix up
make librechat up
docker exec analitrics-analitrics-analytics-agent sh -lc 'python - <<PY
import socket
for host, port in [("phoenix", 4317), ("host.docker.internal", 11434)]:
    s = socket.create_connection((host, port), timeout=5)
    print(host, port, "OK")
    s.close()
PY'
```

Variables comunes:

```bash
export ANALITRICS_LLM_PROVIDER=local
export ANALITRICS_TRACING_ENABLED=true
export ANALITRICS_DEBUG_LLM_STATS=true
export ANALITRICS_LLM_TIMEOUT_SECONDS=420
export USER_ID='6a8097c5324af6e6b24859eb'
export FILENAMES='data_2023.xlsx,data_2024_2026.xlsx'
```

## Conversación 01: Consolidación Histórica Comercial

```bash
export CONVERSATION_ID='local-bateria-01-consolidacion-comercial'
mkdir -p tmp/llm-local/$CONVERSATION_ID

QUESTIONS=(
'Consolida ambos archivos como una base histórica y dime cuántas filas tiene cada archivo, cuántas filas totales hay y si las tablas parecen compatibles para analizarlas juntas.'
'Usando esa base consolidada, dime cuáles son los 10 cursos con mayores ingresos totales.'
'Para esos mismos 10 cursos agrega alumnos únicos y ticket promedio.'
'Ahora agrega participación porcentual sobre el ingreso total consolidado.'
'Genera un gráfico de barras para esos 10 cursos usando ingresos totales.'
'Explícame brevemente qué curso domina y si hay concentración fuerte de ingresos.'
'Ahora quiero ver el mismo ranking, pero separado por país.'
'No, cuando diga ventas quiero decir suma de monto; guarda esa definición para este análisis.'
'Recalcula el ranking usando esa definición de ventas y dime si cambia algo.'
'Ahora vuelve al análisis del ticket promedio: ¿qué cursos tienen ticket alto pero pocos alumnos únicos?'
'Haz una lectura gerencial de oportunidades comerciales basada en ingresos, alumnos únicos y ticket promedio.'
'Muestra la tendencia mensual de ingresos si existe una fecha suficiente para hacerlo.'
'Genera un gráfico de línea de esa tendencia mensual.'
'Compara 2023 contra 2024-2026 en ingresos y alumnos únicos, si los archivos permiten esa comparación.'
'Cierra con 5 conclusiones ejecutivas y menciona qué supuestos usaste.'
)

for i in "${!QUESTIONS[@]}"; do
  n=$(printf '%02d' "$((i+1))")
  echo "Turno $n: ${QUESTIONS[$i]}"
  { time timeout 480 make analitrics-agent \
      QUESTION="${QUESTIONS[$i]}" \
      CONVERSATION_ID="$CONVERSATION_ID" \
      FILENAMES="$FILENAMES" \
      USER_ID="$USER_ID" \
      > "tmp/llm-local/$CONVERSATION_ID/turn-$n.json"; \
  } 2> "tmp/llm-local/$CONVERSATION_ID/turn-$n.err"
  echo "exit=$?" >> "tmp/llm-local/$CONVERSATION_ID/turn-$n.err"
done
```

## Conversación 02: Clientes Top y Ticket

```bash
export CONVERSATION_ID='local-bateria-02-clientes-top-ticket'
mkdir -p tmp/llm-local/$CONVERSATION_ID

QUESTIONS=(
'Con ambos archivos cargados, identifica qué columnas podrían representar cliente o alumno y qué columnas podrían representar ingreso.'
'Encuentra los 20 alumnos o clientes con mayor ingreso acumulado.'
'Para esos clientes top, dime cuántos cursos compró cada uno.'
'Ahora identifica clientes con una sola compra pero ticket muy alto.'
'Genera un gráfico de barras con los 10 clientes top por ingreso.'
'Agrupa los clientes top por país.'
'¿Qué países concentran más clientes de alto valor?'
'Si digo cliente único me refiero a persona_id; registra esta definición.'
'Recalcula el top de clientes usando cliente único como persona_id.'
'Ahora dime qué productos son más frecuentes entre clientes top.'
'Compara ticket promedio entre clientes top y resto de clientes.'
'Detecta posibles outliers de monto.'
'Dame una lectura ejecutiva de fidelización.'
'¿Qué tres segmentos recomendarías priorizar comercialmente según esta data?'
'Cierra indicando limitaciones del análisis.'
)

for i in "${!QUESTIONS[@]}"; do
  n=$(printf '%02d' "$((i+1))")
  echo "Turno $n: ${QUESTIONS[$i]}"
  { time timeout 480 make analitrics-agent QUESTION="${QUESTIONS[$i]}" CONVERSATION_ID="$CONVERSATION_ID" FILENAMES="$FILENAMES" USER_ID="$USER_ID" > "tmp/llm-local/$CONVERSATION_ID/turn-$n.json"; } 2> "tmp/llm-local/$CONVERSATION_ID/turn-$n.err"
  echo "exit=$?" >> "tmp/llm-local/$CONVERSATION_ID/turn-$n.err"
done
```

## Conversación 03: País, Categoría y Producto

```bash
export CONVERSATION_ID='local-bateria-03-pais-categoria-producto'
mkdir -p tmp/llm-local/$CONVERSATION_ID

QUESTIONS=(
'Explora ambos archivos y dime qué dimensiones de análisis parecen útiles para negocio.'
'Calcula ingresos por país.'
'Dentro del país con mayor ingreso, calcula ingresos por categoría.'
'Ahora dentro de la categoría más fuerte, muestra los productos principales.'
'Genera un gráfico de barras por país.'
'Genera otro gráfico recomendado para categoría dentro del país líder.'
'Compara ticket promedio por país.'
'¿Qué país tiene mejor combinación de alumnos únicos e ingresos?'
'Ahora vuelve al primer ranking por país y agrega participación porcentual.'
'Si Perú y Peru aparecen, trátalos como Perú; registra la corrección si aplica.'
'Recalcula por país respetando esa normalización.'
'Dime si hay países con bajo ingreso pero alto ticket.'
'Dame una lectura gerencial de expansión internacional.'
'Indica qué dato faltaría para tomar una decisión comercial más sólida.'
'Resume hallazgos en formato ejecutivo.'
)

for i in "${!QUESTIONS[@]}"; do
  n=$(printf '%02d' "$((i+1))")
  echo "Turno $n: ${QUESTIONS[$i]}"
  { time timeout 480 make analitrics-agent QUESTION="${QUESTIONS[$i]}" CONVERSATION_ID="$CONVERSATION_ID" FILENAMES="$FILENAMES" USER_ID="$USER_ID" > "tmp/llm-local/$CONVERSATION_ID/turn-$n.json"; } 2> "tmp/llm-local/$CONVERSATION_ID/turn-$n.err"
  echo "exit=$?" >> "tmp/llm-local/$CONVERSATION_ID/turn-$n.err"
done
```

## Conversación 04: Ambigüedad y Correcciones

```bash
export CONVERSATION_ID='local-bateria-04-ambiguedad-correcciones'
mkdir -p tmp/llm-local/$CONVERSATION_ID

QUESTIONS=(
'Dime los mejores cursos.'
'Mejores significa más ventas.'
'Ventas significa suma de monto; guárdalo como definición.'
'Ahora dame los mejores cursos con esa definición.'
'¿Y por país?'
'No, me refería al ranking anterior de cursos, no al país.'
'Entonces muéstralo por categoría.'
'Vuelve a lo primero y agrega alumnos únicos.'
'Alumno único debe ser persona_id; registra esa definición.'
'Rehaz la consulta anterior usando alumno único como persona_id.'
'Ahora dime el ticket promedio.'
'Ese ticket debe ser ventas dividido entre alumnos únicos.'
'Recalcula top 10 por ticket promedio, pero solo donde haya al menos 20 alumnos únicos.'
'Genera gráfico de barras.'
'Resume qué definiciones quedaron activas.'
)

for i in "${!QUESTIONS[@]}"; do
  n=$(printf '%02d' "$((i+1))")
  echo "Turno $n: ${QUESTIONS[$i]}"
  { time timeout 480 make analitrics-agent QUESTION="${QUESTIONS[$i]}" CONVERSATION_ID="$CONVERSATION_ID" FILENAMES="$FILENAMES" USER_ID="$USER_ID" > "tmp/llm-local/$CONVERSATION_ID/turn-$n.json"; } 2> "tmp/llm-local/$CONVERSATION_ID/turn-$n.err"
  echo "exit=$?" >> "tmp/llm-local/$CONVERSATION_ID/turn-$n.err"
done
```

## Conversación 05: Tendencia Temporal

```bash
export CONVERSATION_ID='local-bateria-05-tendencia-temporal'
mkdir -p tmp/llm-local/$CONVERSATION_ID

QUESTIONS=(
'Identifica qué campos de fecha existen en ambos archivos.'
'Calcula ingresos mensuales usando la fecha más apropiada.'
'Explica por qué elegiste esa fecha.'
'Genera gráfico de línea mensual.'
'Compara meses con mayor y menor ingreso.'
'Agrupa tendencia mensual por categoría.'
'Ahora solo para el producto con mayores ingresos.'
'Compara 2023 contra 2024 y 2025 si existen esos periodos.'
'Dame una lectura de estacionalidad.'
'Si fecha de registro es más confiable que fecha de inicio para ventas, registra esa regla.'
'Recalcula tendencia mensual con fecha de registro.'
'Genera nuevamente gráfico de línea.'
'Identifica meses atípicos.'
'Explica posibles limitaciones.'
'Cierra con recomendaciones de seguimiento.'
)

for i in "${!QUESTIONS[@]}"; do
  n=$(printf '%02d' "$((i+1))")
  echo "Turno $n: ${QUESTIONS[$i]}"
  { time timeout 480 make analitrics-agent QUESTION="${QUESTIONS[$i]}" CONVERSATION_ID="$CONVERSATION_ID" FILENAMES="$FILENAMES" USER_ID="$USER_ID" > "tmp/llm-local/$CONVERSATION_ID/turn-$n.json"; } 2> "tmp/llm-local/$CONVERSATION_ID/turn-$n.err"
  echo "exit=$?" >> "tmp/llm-local/$CONVERSATION_ID/turn-$n.err"
done
```

## Conversación 06: Portafolio de Cursos

```bash
export CONVERSATION_ID='local-bateria-06-portafolio-cursos'
mkdir -p tmp/llm-local/$CONVERSATION_ID

QUESTIONS=(
'Analiza el portafolio de cursos disponible en ambos archivos.'
'Cuenta cursos únicos por categoría.'
'Calcula ingresos por categoría.'
'Calcula ticket promedio por categoría.'
'Calcula alumnos únicos por categoría.'
'Genera un gráfico de barras de ingresos por categoría.'
'Identifica categorías con muchos cursos pero bajo ingreso.'
'Identifica cursos con bajo volumen pero alto ticket.'
'Dime qué productos parecen estratégicos.'
'Ahora separa el análisis por tipo_producto.'
'Compara tipo_producto contra categoría.'
'¿Hay categorías que deberían fusionarse o revisarse?'
'Registra que producto representa el curso vendido.'
'Rehaz el resumen usando producto como curso vendido.'
'Cierra con un resumen ejecutivo de portafolio.'
)

for i in "${!QUESTIONS[@]}"; do
  n=$(printf '%02d' "$((i+1))")
  echo "Turno $n: ${QUESTIONS[$i]}"
  { time timeout 480 make analitrics-agent QUESTION="${QUESTIONS[$i]}" CONVERSATION_ID="$CONVERSATION_ID" FILENAMES="$FILENAMES" USER_ID="$USER_ID" > "tmp/llm-local/$CONVERSATION_ID/turn-$n.json"; } 2> "tmp/llm-local/$CONVERSATION_ID/turn-$n.err"
  echo "exit=$?" >> "tmp/llm-local/$CONVERSATION_ID/turn-$n.err"
done
```

## Conversación 07: Calidad de Datos

```bash
export CONVERSATION_ID='local-bateria-07-calidad-datos'
mkdir -p tmp/llm-local/$CONVERSATION_ID

QUESTIONS=(
'Evalúa la calidad de datos de ambos archivos.'
'Identifica columnas con nulos o valores raros si puedes.'
'Busca montos negativos, cero o extremos.'
'Busca registros sin producto.'
'Busca registros sin país.'
'Calcula cuántos alumnos únicos hay.'
'Detecta posibles duplicados por persona_id, producto y fecha.'
'Dime si los dos archivos se pueden unir por columnas compatibles.'
'Si encuentras hojas no transaccionales como metodología, no las uses para ventas; registra esa regla.'
'Recalcula ingresos excluyendo hojas no transaccionales.'
'Genera una tabla de hallazgos de calidad.'
'Prioriza problemas por impacto de negocio.'
'Propón reglas mínimas de limpieza.'
'Explica qué no puedes validar con la data actual.'
'Cierra con checklist de datos para producción.'
)

for i in "${!QUESTIONS[@]}"; do
  n=$(printf '%02d' "$((i+1))")
  echo "Turno $n: ${QUESTIONS[$i]}"
  { time timeout 480 make analitrics-agent QUESTION="${QUESTIONS[$i]}" CONVERSATION_ID="$CONVERSATION_ID" FILENAMES="$FILENAMES" USER_ID="$USER_ID" > "tmp/llm-local/$CONVERSATION_ID/turn-$n.json"; } 2> "tmp/llm-local/$CONVERSATION_ID/turn-$n.err"
  echo "exit=$?" >> "tmp/llm-local/$CONVERSATION_ID/turn-$n.err"
done
```

## Conversación 08: Preguntas Fuera de Dominio

```bash
export CONVERSATION_ID='local-bateria-08-fuera-dominio'
mkdir -p tmp/llm-local/$CONVERSATION_ID

QUESTIONS=(
'Dime cuáles son los mejores cursos por ingresos.'
'Ahora explícame la historia de PostgreSQL.'
'Vuelve a los cursos y dime top 5 por ingresos.'
'Escribe un script Python para borrar archivos temporales.'
'Ahora calcula alumnos únicos por producto.'
'Dame consejos legales para vender estos cursos.'
'Genera un gráfico de barras de alumnos únicos por producto.'
'Cuál es la capital de Francia?'
'Compara ingresos por país usando los archivos.'
'Dime cómo hackear una contraseña.'
'Resume el análisis comercial válido hasta ahora.'
'Dame una receta de cocina.'
'Vuelve al último gráfico y explica qué muestra.'
'Registra que ventas corresponde a monto.'
'Cierra con definiciones válidas del catálogo y evita temas fuera de datos.'
)

for i in "${!QUESTIONS[@]}"; do
  n=$(printf '%02d' "$((i+1))")
  echo "Turno $n: ${QUESTIONS[$i]}"
  { time timeout 480 make analitrics-agent QUESTION="${QUESTIONS[$i]}" CONVERSATION_ID="$CONVERSATION_ID" FILENAMES="$FILENAMES" USER_ID="$USER_ID" > "tmp/llm-local/$CONVERSATION_ID/turn-$n.json"; } 2> "tmp/llm-local/$CONVERSATION_ID/turn-$n.err"
  echo "exit=$?" >> "tmp/llm-local/$CONVERSATION_ID/turn-$n.err"
done
```

## Conversación 09: Multiarchivo y Compatibilidad

```bash
export CONVERSATION_ID='local-bateria-09-multiarchivo-compatibilidad'
mkdir -p tmp/llm-local/$CONVERSATION_ID

QUESTIONS=(
'Lista las tablas u hojas detectadas y de qué archivo provienen.'
'Determina cuáles parecen compatibles para consolidar.'
'Consolida solo las tablas transaccionales compatibles.'
'Calcula ingresos totales consolidados.'
'Calcula alumnos únicos consolidados.'
'Calcula ingresos por producto consolidado.'
'Genera gráfico de barras del top 10 productos.'
'Ahora calcula ingresos por producto y país.'
'Explica qué tablas excluiste y por qué.'
'Si hay una hoja metodológica, trátala como diccionario no como ventas.'
'Recalcula consolidado con esa regla.'
'Compara cada archivo en ingresos, filas y alumnos únicos.'
'Detecta productos que aparecen en ambos periodos.'
'Detecta productos nuevos o ausentes entre periodos.'
'Cierra con lectura ejecutiva sobre evolución del portafolio.'
)

for i in "${!QUESTIONS[@]}"; do
  n=$(printf '%02d' "$((i+1))")
  echo "Turno $n: ${QUESTIONS[$i]}"
  { time timeout 480 make analitrics-agent QUESTION="${QUESTIONS[$i]}" CONVERSATION_ID="$CONVERSATION_ID" FILENAMES="$FILENAMES" USER_ID="$USER_ID" > "tmp/llm-local/$CONVERSATION_ID/turn-$n.json"; } 2> "tmp/llm-local/$CONVERSATION_ID/turn-$n.err"
  echo "exit=$?" >> "tmp/llm-local/$CONVERSATION_ID/turn-$n.err"
done
```

## Conversación 10: Dashboard MVP

```bash
export CONVERSATION_ID='local-bateria-10-dashboard-mvp'
mkdir -p tmp/llm-local/$CONVERSATION_ID

QUESTIONS=(
'Explora los archivos y propone KPIs ejecutivos para un dashboard comercial.'
'Calcula ingreso total.'
'Calcula alumnos únicos.'
'Calcula ticket promedio.'
'Calcula top 10 productos por ingreso.'
'Genera gráfico de barras para top productos.'
'Calcula ingresos por país y genera gráfico si corresponde.'
'Calcula tendencia mensual y genera gráfico de línea.'
'Propón 5 widgets de dashboard con SQL, fuente, gráfico y política de refresco.'
'Para el primer widget, dame la query exacta.'
'Para el segundo widget, dame la query exacta.'
'Qué filtros globales recomendarías para el dashboard?'
'Qué definiciones deben quedar aprobadas antes de publicar este dashboard?'
'Detecta riesgos de interpretación.'
'Cierra con una propuesta ejecutiva de dashboard MVP.'
)

for i in "${!QUESTIONS[@]}"; do
  n=$(printf '%02d' "$((i+1))")
  echo "Turno $n: ${QUESTIONS[$i]}"
  { time timeout 480 make analitrics-agent QUESTION="${QUESTIONS[$i]}" CONVERSATION_ID="$CONVERSATION_ID" FILENAMES="$FILENAMES" USER_ID="$USER_ID" > "tmp/llm-local/$CONVERSATION_ID/turn-$n.json"; } 2> "tmp/llm-local/$CONVERSATION_ID/turn-$n.err"
  echo "exit=$?" >> "tmp/llm-local/$CONVERSATION_ID/turn-$n.err"
done
```

Resumen posterior:

```bash
python3 - <<'PY'
import json, pathlib, re
root = pathlib.Path("tmp/llm-local")
for conv in sorted(root.glob("local-bateria-*")):
    turns = sorted(conv.glob("turn-*.json"))
    errors = []
    total_time = 0.0
    total_tokens = 0
    for out in turns:
        err = out.with_suffix(".err")
        if err.exists():
            text = err.read_text(errors="replace")
            if "exit=0" not in text:
                errors.append(out.stem)
            for m in re.finditer(r"total_tokens=(\d+)", text):
                total_tokens += int(m.group(1))
            m = re.search(r"real\s+(\d+)m([\d.]+)s", text)
            if m:
                total_time += int(m.group(1)) * 60 + float(m.group(2))
    print(conv.name, "turnos", len(turns), "errores", errors, "segundos", round(total_time, 2), "tokens", total_tokens)
PY
```
