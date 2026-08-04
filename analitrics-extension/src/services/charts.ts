import type { TopLevelSpec } from 'vega-lite';

type ChartType = 'barras' | 'lineas' | 'torta' | 'tabla';

type ChartSpecOverrides = {
  orientation?: 'horizontal' | 'vertical';
  xField?: string;
  yField?: string;
  colorField?: string;
  topN?: number;
  sort?: 'ascending' | 'descending' | 'none';
  spec?: Record<string, unknown>;
};

type ChartBuildResult = {
  summary: string;
  resource: {
    type: 'resource';
    resource: {
      uri: string;
      mimeType: 'text/html';
      text: string;
      name: string;
    };
  };
};

function escapeHtml(value: unknown): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function slugifyUri(value: string): string {
  return value
    .normalize('NFKD')
    .replace(/[^\w\s-]/g, '')
    .trim()
    .replace(/[-\s]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .toLowerCase();
}

function serializeForScript(value: unknown): string {
  return JSON.stringify(value).replace(/</g, '\\u003c').replace(/>/g, '\\u003e');
}

function isNumericValue(value: unknown): boolean {
  if (typeof value === 'number') {
    return Number.isFinite(value);
  }
  if (typeof value === 'string') {
    const normalized = value.replace(/,/g, '').trim();
    return normalized.length > 0 && !Number.isNaN(Number(normalized));
  }
  return false;
}

function toNumeric(value: unknown): number | null {
  if (!isNumericValue(value)) {
    return null;
  }
  return typeof value === 'number' ? value : Number(String(value).replace(/,/g, '').trim());
}

function distinctCount(values: unknown[]): number {
  return new Set(
    values.map((value) => String(value ?? '').trim()).filter((value) => value.length > 0),
  ).size;
}

function scoreLabelColumn(column: string, rows: Record<string, unknown>[]): number {
  const values = rows.map((row) => row[column]);
  const distinct = distinctCount(values);
  const numericRatio =
    values.length === 0 ? 1 : values.filter((value) => toNumeric(value) !== null).length / values.length;
  const lower = column.toLowerCase();

  let score = distinct * 10;
  if (distinct <= 1) {
    score -= 1000;
  }
  if (numericRatio > 0.7) {
    score -= 150;
  }
  if (
    /(etiqueta|label|nombre|pais|país|producto|curso|categoria|categoría|segmento|canal|region|región|fecha|mes|anio|año|unidad|tipo)/.test(
      lower,
    )
  ) {
    score += 120;
  }

  return score;
}

function scoreValueColumn(column: string, rows: Record<string, unknown>[]): number {
  const values = rows.map((row) => row[column]);
  const numericValues = values.map(toNumeric).filter((value): value is number => value !== null);
  const distinct = distinctCount(numericValues);
  const numericRatio = values.length === 0 ? 0 : numericValues.length / values.length;
  const lower = column.toLowerCase();

  let score = numericRatio * 200 + distinct * 5;
  if (numericValues.length === 0) {
    score -= 1000;
  }
  if (
    /(valor|value|monto|importe|ingreso|revenue|total|ventas|cantidad|conteo|count|metric|metrica|métrica)/.test(
      lower,
    )
  ) {
    score += 140;
  }

  return score;
}

function inferChartColumns(rows: Record<string, unknown>[]): {
  labelColumn: string;
  valueColumn: string;
} {
  if (!rows.length) {
    throw new Error('La consulta no devolvió filas para generar el gráfico.');
  }

  const columns = Object.keys(rows[0]);
  if (columns.length < 2) {
    throw new Error('El gráfico requiere al menos dos columnas: una etiqueta y una métrica.');
  }

  const explicitLabel =
    columns.find((column) => /^(etiqueta|label|dimension|x)$/i.test(column)) ?? null;
  const explicitValue =
    columns.find((column) => /^(valor|value|metrica|m[eé]trica|y)$/i.test(column)) ?? null;

  const valueColumn =
    explicitValue ??
    [...columns].sort((a, b) => scoreValueColumn(b, rows) - scoreValueColumn(a, rows))[0] ??
    columns[1];

  if (!rows.some((row) => toNumeric(row[valueColumn]) !== null)) {
    throw new Error('No encontré una columna numérica utilizable para el gráfico.');
  }

  const labelCandidates = columns.filter((column) => column !== valueColumn);
  const labelColumn =
    explicitLabel && explicitLabel !== valueColumn
      ? explicitLabel
      : [...labelCandidates].sort((a, b) => scoreLabelColumn(b, rows) - scoreLabelColumn(a, rows))[0] ??
        columns[0];

  return { labelColumn, valueColumn };
}

function buildPalette(size: number): string[] {
  const base = [
    '#2563eb',
    '#dc2626',
    '#16a34a',
    '#f59e0b',
    '#7c3aed',
    '#0891b2',
    '#ea580c',
    '#4f46e5',
    '#65a30d',
    '#db2777',
    '#0f766e',
    '#9333ea',
  ];
  return Array.from({ length: size }, (_, index) => base[index % base.length] ?? '#2563eb');
}

function buildShell(title: string, subtitle: string, body: string): string {
  return `<!doctype html>
<html lang="es">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>${escapeHtml(title)}</title>
    <style>
      :root {
        color-scheme: light;
        --bg: #ffffff;
        --panel: #f8f5ff;
        --border: #ddd6fe;
        --text: #221b44;
        --muted: #6b6590;
      }
      * { box-sizing: border-box; }
      body {
        margin: 0;
        padding: 0;
        font-family: Inter, ui-sans-serif, system-ui, sans-serif;
        background: linear-gradient(180deg, #ffffff 0%, #fbf8ff 100%);
        color: var(--text);
      }
      .card {
        width: 100%;
        border: 1px solid var(--border);
        border-radius: 18px;
        background: var(--bg);
        box-shadow: 0 12px 36px rgba(94, 70, 168, 0.08);
        overflow: hidden;
      }
      .header {
        padding: 18px 20px 10px;
        background: linear-gradient(135deg, #faf7ff 0%, #f3ecff 100%);
        border-bottom: 1px solid var(--border);
      }
      .title {
        margin: 0;
        font-size: 20px;
        font-weight: 700;
      }
      .subtitle {
        margin: 6px 0 0;
        color: var(--muted);
        font-size: 13px;
      }
      .content {
        padding: 18px 20px 22px;
      }
      .meta {
        margin-bottom: 16px;
        padding: 10px 12px;
        border-radius: 12px;
        background: var(--panel);
        color: var(--muted);
        font-size: 13px;
      }
      .table-wrap {
        overflow: auto;
        border: 1px solid var(--border);
        border-radius: 14px;
      }
      table {
        width: 100%;
        border-collapse: collapse;
        font-size: 13px;
      }
      th, td {
        padding: 10px 12px;
        border-bottom: 1px solid #eee8ff;
        text-align: left;
        white-space: nowrap;
      }
      th {
        background: #faf7ff;
      }
      tr:last-child td {
        border-bottom: 0;
      }
      .viz {
        overflow-x: auto;
      }
      .viz svg {
        display: block;
        width: 100%;
        height: auto;
      }
      .interactive-viz {
        min-height: 420px;
        border: 1px solid var(--border);
        border-radius: 16px;
        background: linear-gradient(180deg, #ffffff 0%, #fcfaff 100%);
        padding: 10px;
      }
      .toolbar {
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
        align-items: center;
        margin-bottom: 14px;
      }
      .ghost-btn {
        border: 1px solid var(--border);
        background: #fff;
        color: var(--text);
        border-radius: 999px;
        padding: 8px 14px;
        font-size: 13px;
        cursor: pointer;
      }
      .toolbar-note {
        font-size: 12px;
        color: var(--muted);
      }
      .chart-error {
        padding: 18px;
        color: #9f1239;
        font-size: 13px;
      }
    </style>
  </head>
  <body>
    <div class="card">
      <div class="header">
        <h1 class="title">${escapeHtml(title)}</h1>
        <p class="subtitle">${escapeHtml(subtitle)}</p>
      </div>
      <div class="content">
        ${body}
      </div>
    </div>
  </body>
</html>`;
}

function buildTableHtml(rows: Record<string, unknown>[]): string {
  const limitedRows = rows.slice(0, 50);
  const columns = limitedRows.length ? Object.keys(limitedRows[0]).slice(0, 10) : [];
  const header = columns.map((column) => `<th>${escapeHtml(column)}</th>`).join('');
  const body = limitedRows
    .map((row) => {
      const cells = columns.map((column) => `<td>${escapeHtml(row[column] ?? '')}</td>`).join('');
      return `<tr>${cells}</tr>`;
    })
    .join('');
  return `<div class="table-wrap"><table><thead><tr>${header}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function buildInteractiveChartHtml(params: {
  spec: TopLevelSpec;
  labelColumn: string;
  valueColumn: string;
  total: number;
}): string {
  const { spec, labelColumn, valueColumn, total } = params;
  const serializedSpec = serializeForScript(spec);

  return `
    <div class="meta">
      Métrica graficada: <strong>${escapeHtml(valueColumn)}</strong> con dimensión <strong>${escapeHtml(labelColumn)}</strong>.
      Total visible: <strong>${escapeHtml(total.toLocaleString('es-PE', { maximumFractionDigits: 2 }))}</strong>.
    </div>
    <div class="toolbar">
      <button type="button" id="reset-view" class="ghost-btn">Restablecer vista</button>
      <span class="toolbar-note">Pase el cursor o haga clic sobre el gráfico para ver más detalle.</span>
    </div>
    <div id="chart-host" class="viz interactive-viz"></div>
    <script src="https://cdn.jsdelivr.net/npm/vega@5"></script>
    <script src="https://cdn.jsdelivr.net/npm/vega-lite@5"></script>
    <script src="https://cdn.jsdelivr.net/npm/vega-embed@6"></script>
    <script>
      const spec = ${serializedSpec};
      const host = document.getElementById('chart-host');
      const resetButton = document.getElementById('reset-view');

      vegaEmbed(host, spec, {
        actions: {
          export: true,
          source: false,
          compiled: false,
          editor: false,
        },
        renderer: 'svg',
        tooltip: true,
      }).then((result) => {
        const { view } = result;
        resetButton?.addEventListener('click', () => {
          view.runAsync();
        });
      }).catch((error) => {
        host.innerHTML = '<div class="chart-error">No se pudo renderizar el gráfico interactivo.</div>';
        console.error(error);
      });
    </script>
  `;
}

function coerceRow(row: Record<string, unknown>): Record<string, unknown> {
  const normalized: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(row)) {
    normalized[key] = toNumeric(value) ?? value;
  }
  return normalized;
}

function chooseOrientation(rows: Record<string, unknown>[], labelColumn: string): 'horizontal' | 'vertical' {
  const labels = rows.map((row) => String(row[labelColumn] ?? ''));
  const averageLength = labels.length
    ? labels.reduce((sum, label) => sum + label.length, 0) / labels.length
    : 0;
  return averageLength > 18 || rows.length > 6 ? 'horizontal' : 'vertical';
}

function buildSort(sort: 'ascending' | 'descending' | 'none' | undefined, axisRef: '-x' | '-y') {
  if (sort === 'none') {
    return null;
  }
  if (sort === 'ascending') {
    return axisRef === '-x' ? 'x' : 'y';
  }
  return axisRef;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function buildVegaLiteSpec(params: {
  title: string;
  chartType: ChartType;
  rows: Record<string, unknown>[];
  labelColumn: string;
  valueColumn: string;
  overrides?: ChartSpecOverrides;
}): TopLevelSpec {
  const { title, chartType, labelColumn, valueColumn, overrides } = params;
  const rows = params.rows.map(coerceRow);
  const colorRange = buildPalette(Math.min(rows.length, 12));

  if (isObject(overrides?.spec)) {
    const overrideTitle = overrides.spec.title as TopLevelSpec['title'] | undefined;
    const mergedSpec = {
      $schema: 'https://vega.github.io/schema/vega-lite/v5.json',
      autosize: { type: 'fit-x', contains: 'padding' },
      width: 920,
      ...overrides.spec,
      data: { values: rows },
      config: {
        axis: {
          labelColor: '#4b4665',
          titleColor: '#221b44',
          gridColor: '#ebe5ff',
          domainColor: '#d7cff7',
          tickColor: '#d7cff7',
          labelFontSize: 12,
          titleFontSize: 13,
        },
        legend: {
          labelColor: '#4b4665',
          titleColor: '#221b44',
        },
        range: {
          category: colorRange,
        },
        ...(isObject(overrides.spec.config) ? overrides.spec.config : {}),
      },
      title:
        overrideTitle ??
        ({
          text: title,
          color: '#221b44',
          fontSize: 20,
          anchor: 'start',
        } as const),
    } as TopLevelSpec;
    return mergedSpec;
  }

  if (chartType === 'torta') {
    return {
      $schema: 'https://vega.github.io/schema/vega-lite/v5.json',
      width: 920,
      height: 420,
      autosize: { type: 'fit-x', contains: 'padding' },
      data: { values: rows },
      mark: { type: 'arc', outerRadius: 170 },
      encoding: {
        theta: { field: valueColumn, type: 'quantitative' },
        color: {
          field: overrides?.colorField ?? labelColumn,
          type: 'nominal',
          scale: { range: colorRange },
          legend: { title: null, orient: 'right' },
        },
        tooltip: [
          { field: labelColumn, type: 'nominal', title: labelColumn },
          { field: valueColumn, type: 'quantitative', title: valueColumn },
        ],
      },
      params: [
        {
          name: 'seleccion_torta',
          select: { type: 'point', on: 'click' },
        },
      ],
      title: { text: title, color: '#221b44', fontSize: 20, anchor: 'start' },
      config: {
        view: { stroke: null },
        legend: { labelColor: '#4b4665', titleColor: '#221b44' },
      },
    };
  }

  if (chartType === 'lineas') {
    const xField = overrides?.xField ?? labelColumn;
    const yField = overrides?.yField ?? valueColumn;
    return {
      $schema: 'https://vega.github.io/schema/vega-lite/v5.json',
      width: 920,
      height: 420,
      autosize: { type: 'fit-x', contains: 'padding' },
      data: { values: rows },
      mark: { type: 'line', point: { filled: true, size: 80 }, strokeWidth: 3 },
      encoding: {
        x: { field: xField, type: 'ordinal', title: xField },
        y: { field: yField, type: 'quantitative', title: yField },
        color: overrides?.colorField
          ? {
              field: overrides.colorField,
              type: 'nominal',
              scale: { range: colorRange },
            }
          : { value: '#2563eb' },
        tooltip: Object.keys(rows[0] ?? {}).map((field) => ({
          field,
          type: field === yField ? 'quantitative' : 'nominal',
        })),
      },
      params: [
        {
          name: 'zoom_linea',
          select: 'interval',
          bind: 'scales',
        },
      ],
      title: { text: title, color: '#221b44', fontSize: 20, anchor: 'start' },
      config: {
        view: { stroke: null },
        axis: {
          labelColor: '#4b4665',
          titleColor: '#221b44',
          gridColor: '#ebe5ff',
          domainColor: '#d7cff7',
          tickColor: '#d7cff7',
        },
      },
    };
  }

  const orientation = overrides?.orientation ?? chooseOrientation(rows, labelColumn);
  const categoryField =
    orientation === 'horizontal'
      ? overrides?.yField ?? labelColumn
      : overrides?.xField ?? labelColumn;
  const metricField =
    orientation === 'horizontal'
      ? overrides?.xField ?? valueColumn
      : overrides?.yField ?? valueColumn;
  const height = Math.max(360, rows.length * (orientation === 'horizontal' ? 42 : 20));

  return {
    $schema: 'https://vega.github.io/schema/vega-lite/v5.json',
    width: 920,
    height,
    autosize: { type: 'fit-x', contains: 'padding' },
    data: { values: rows },
    mark: { type: 'bar', cornerRadiusEnd: 8 },
    params: [
      {
        name: 'seleccion_barra',
        select: { type: 'point', on: 'click' },
      },
    ],
    encoding:
      orientation === 'horizontal'
        ? {
            x: { field: metricField, type: 'quantitative', title: metricField },
            y: {
              field: categoryField,
              type: 'nominal',
              title: null,
              sort: buildSort(overrides?.sort, '-x') ?? '-x',
              axis: { labelLimit: 260 },
            },
            color: overrides?.colorField
              ? {
                  field: overrides.colorField,
                  type: 'nominal',
                  scale: { range: colorRange },
                }
              : {
                  field: categoryField,
                  type: 'nominal',
                  scale: { range: colorRange },
                  legend: null,
                },
            tooltip: Object.keys(rows[0] ?? {}).map((field) => ({
              field,
              type: field === metricField ? 'quantitative' : 'nominal',
            })),
          }
        : {
            x: {
              field: categoryField,
              type: 'nominal',
              title: null,
              sort: buildSort(overrides?.sort, '-y') ?? '-y',
              axis: { labelAngle: -25, labelLimit: 180 },
            },
            y: { field: metricField, type: 'quantitative', title: metricField },
            color: overrides?.colorField
              ? {
                  field: overrides.colorField,
                  type: 'nominal',
                  scale: { range: colorRange },
                }
              : {
                  field: categoryField,
                  type: 'nominal',
                  scale: { range: colorRange },
                  legend: null,
                },
            tooltip: Object.keys(rows[0] ?? {}).map((field) => ({
              field,
              type: field === metricField ? 'quantitative' : 'nominal',
            })),
          },
    title: { text: title, color: '#221b44', fontSize: 20, anchor: 'start' },
    config: {
      view: { stroke: null },
      axis: {
        labelColor: '#4b4665',
        titleColor: '#221b44',
        gridColor: '#ebe5ff',
        domainColor: '#d7cff7',
        tickColor: '#d7cff7',
      },
      legend: {
        labelColor: '#4b4665',
        titleColor: '#221b44',
      },
    },
  };
}

export async function buildChartResource(params: {
  title: string;
  chartType: ChartType;
  rows: Record<string, unknown>[];
  labelColumn?: string;
  valueColumn?: string;
  overrides?: ChartSpecOverrides;
}): Promise<ChartBuildResult> {
  const { title, chartType, overrides } = params;

  if (chartType === 'tabla') {
    const subtitle = `${params.rows.length} filas devueltas por la consulta`;
    return {
      summary: `Se preparó una tabla con ${params.rows.length} filas de resultado.`,
      resource: {
        type: 'resource',
        resource: {
          uri: `ui://analitrics/${slugifyUri(title || 'tabla')}`,
          mimeType: 'text/html',
          text: buildShell(title, subtitle, buildTableHtml(params.rows)),
          name: title,
        },
      },
    };
  }

  const inferred = inferChartColumns(params.rows);
  const requestedLabelColumn = params.labelColumn;
  const requestedValueColumn = params.valueColumn;
  const labelColumn =
    requestedLabelColumn && params.rows.some((row) => Object.hasOwn(row, requestedLabelColumn))
      ? requestedLabelColumn
      : inferred.labelColumn;
  const valueColumn =
    requestedValueColumn && params.rows.some((row) => Object.hasOwn(row, requestedValueColumn))
      ? requestedValueColumn
      : inferred.valueColumn;

  const validRows = [...params.rows].filter((row) => toNumeric(row[valueColumn]) !== null);
  const sortedRows =
    chartType === 'lineas'
      ? validRows
      : validRows.sort((left, right) => (toNumeric(right[valueColumn]) ?? 0) - (toNumeric(left[valueColumn]) ?? 0));
  const defaultLimit = chartType === 'lineas' ? 200 : chartType === 'torta' ? 8 : 12;
  const limitedRows = sortedRows.slice(0, overrides?.topN ?? defaultLimit);

  if (!limitedRows.length) {
    throw new Error('La consulta no devolvió pares etiqueta-métrica válidos para graficar.');
  }

  const spec = buildVegaLiteSpec({
    title,
    chartType,
    rows: limitedRows,
    labelColumn,
    valueColumn,
    overrides,
  });
  const total = limitedRows.reduce((sum, row) => sum + (toNumeric(row[valueColumn]) ?? 0), 0);
  const subtitle = `${limitedRows.length} filas visibles usando ${labelColumn} y ${valueColumn}`;
  const body = buildInteractiveChartHtml({
    spec,
    labelColumn,
    valueColumn,
    total,
  });

  return {
    summary: `Se generó un gráfico de ${chartType} con ${limitedRows.length} filas usando ${labelColumn} como dimensión principal y ${valueColumn} como métrica.`,
    resource: {
      type: 'resource',
      resource: {
        uri: `ui://analitrics/${slugifyUri(title || `grafico-${chartType}`)}`,
        mimeType: 'text/html',
        text: buildShell(title, subtitle, body),
        name: title,
      },
    },
  };
}
