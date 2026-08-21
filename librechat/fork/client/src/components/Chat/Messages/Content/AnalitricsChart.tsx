type ChartEncoding = {
  field?: string;
  title?: string;
  type?: string;
};

type VegaLiteSpec = {
  title?: string;
  mark?: string | { type?: string };
  data?: {
    values?: Record<string, unknown>[];
  };
  encoding?: {
    x?: ChartEncoding;
    y?: ChartEncoding;
  };
};

type ChartPayload = {
  chart_required?: boolean;
  reason?: string;
  spec?: VegaLiteSpec | null;
};

const numberFormat = new Intl.NumberFormat('es-PE', {
  maximumFractionDigits: 0,
});

const parsePayload = (output?: string | null): ChartPayload | null => {
  if (!output) {
    return null;
  }
  try {
    const parsed = JSON.parse(output);
    return parsed && typeof parsed === 'object' ? parsed : null;
  } catch {
    return null;
  }
};

const markType = (mark: VegaLiteSpec['mark']) =>
  typeof mark === 'string' ? mark : mark?.type || '';

const numericValue = (row: Record<string, unknown>, field?: string) => {
  if (!field) {
    return 0;
  }
  const value = row[field];
  return typeof value === 'number' ? value : Number(value ?? 0);
};

const textValue = (row: Record<string, unknown>, field?: string) => {
  if (!field) {
    return '';
  }
  return String(row[field] ?? '');
};

const isQuantitative = (encoding?: ChartEncoding) =>
  /quantitative|number|integer/i.test(encoding?.type || '');

function UnsupportedChart({ reason }: { reason?: string }) {
  return (
    <div className="my-3 rounded-lg border border-border-light bg-surface-secondary p-3 text-sm text-text-secondary">
      <div className="font-medium text-text-primary">Grafico sugerido</div>
      <p className="mt-1">{reason || 'El agente sugirio un grafico, pero la especificacion no es compatible con el renderer MVP.'}</p>
    </div>
  );
}

function HorizontalBarChart({
  spec,
  rows,
}: {
  spec: VegaLiteSpec;
  rows: Record<string, unknown>[];
}) {
  const xField = spec.encoding?.x?.field;
  const yField = spec.encoding?.y?.field;
  const max = Math.max(...rows.map((row) => numericValue(row, xField)), 1);
  const width = 680;
  const rowHeight = 34;
  const labelWidth = 230;
  const chartWidth = width - labelWidth - 80;
  const height = 50 + rows.length * rowHeight;
  const title = spec.title || spec.encoding?.x?.title || 'Grafico';

  return (
    <div className="my-3 overflow-hidden rounded-lg border border-border-light bg-surface-secondary p-3">
      <div className="mb-2 text-sm font-medium text-text-primary">{title}</div>
      <svg viewBox={`0 0 ${width} ${height}`} className="h-auto w-full" role="img" aria-label={title}>
        {rows.map((row, index) => {
          const y = 35 + index * rowHeight;
          const value = numericValue(row, xField);
          const label = textValue(row, yField);
          const barWidth = Math.max((value / max) * chartWidth, 1);
          return (
            <g key={`${label}-${index}`}>
              <text x="0" y={y + 15} className="fill-text-secondary text-[12px]">
                <title>{label}</title>
                {label.length > 32 ? `${label.slice(0, 31)}...` : label}
              </text>
              <rect
                x={labelWidth}
                y={y}
                width={barWidth}
                height="20"
                rx="4"
                className="fill-green-500"
              />
              <text x={labelWidth + barWidth + 8} y={y + 15} className="fill-text-primary text-[12px]">
                {numberFormat.format(value)}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function VerticalBarChart({
  spec,
  rows,
}: {
  spec: VegaLiteSpec;
  rows: Record<string, unknown>[];
}) {
  const xField = spec.encoding?.x?.field;
  const yField = spec.encoding?.y?.field;
  const max = Math.max(...rows.map((row) => numericValue(row, yField)), 1);
  const width = 680;
  const height = 320;
  const pad = 44;
  const chartHeight = height - pad * 2;
  const barGap = 8;
  const barWidth = Math.max((width - pad * 2 - barGap * (rows.length - 1)) / rows.length, 10);
  const title = spec.title || spec.encoding?.y?.title || 'Grafico';

  return (
    <div className="my-3 overflow-hidden rounded-lg border border-border-light bg-surface-secondary p-3">
      <div className="mb-2 text-sm font-medium text-text-primary">{title}</div>
      <svg viewBox={`0 0 ${width} ${height}`} className="h-auto w-full" role="img" aria-label={title}>
        {rows.map((row, index) => {
          const value = numericValue(row, yField);
          const label = textValue(row, xField);
          const barHeight = Math.max((value / max) * chartHeight, 1);
          const x = pad + index * (barWidth + barGap);
          const y = height - pad - barHeight;
          return (
            <g key={`${label}-${index}`}>
              <rect x={x} y={y} width={barWidth} height={barHeight} rx="4" className="fill-green-500" />
              <text
                x={x + barWidth / 2}
                y={height - 18}
                textAnchor="middle"
                className="fill-text-secondary text-[10px]"
              >
                <title>{label}</title>
                {label.length > 10 ? `${label.slice(0, 9)}...` : label}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function LineChart({ spec, rows }: { spec: VegaLiteSpec; rows: Record<string, unknown>[] }) {
  const xField = spec.encoding?.x?.field;
  const yField = spec.encoding?.y?.field;
  const values = rows.map((row, index) => ({
    x: index,
    label: textValue(row, xField),
    y: numericValue(row, yField),
  }));
  const max = Math.max(...values.map((row) => row.y), 1);
  const min = Math.min(...values.map((row) => row.y), 0);
  const width = 680;
  const height = 320;
  const pad = 44;
  const chartWidth = width - pad * 2;
  const chartHeight = height - pad * 2;
  const range = Math.max(max - min, 1);
  const title = spec.title || spec.encoding?.y?.title || 'Grafico';
  const points = values
    .map((row, index) => {
      const x = pad + (index / Math.max(values.length - 1, 1)) * chartWidth;
      const y = height - pad - ((row.y - min) / range) * chartHeight;
      return `${x},${y}`;
    })
    .join(' ');

  return (
    <div className="my-3 overflow-hidden rounded-lg border border-border-light bg-surface-secondary p-3">
      <div className="mb-2 text-sm font-medium text-text-primary">{title}</div>
      <svg viewBox={`0 0 ${width} ${height}`} className="h-auto w-full" role="img" aria-label={title}>
        <polyline fill="none" stroke="currentColor" strokeWidth="3" points={points} className="text-green-500" />
        {values.map((row, index) => {
          const x = pad + (index / Math.max(values.length - 1, 1)) * chartWidth;
          const y = height - pad - ((row.y - min) / range) * chartHeight;
          return <circle key={`${row.label}-${index}`} cx={x} cy={y} r="4" className="fill-green-500" />;
        })}
      </svg>
    </div>
  );
}

export default function AnalitricsChart({ output }: { output?: string | null }) {
  const payload = parsePayload(output);
  const spec = payload?.spec ?? null;
  const rows = Array.isArray(spec?.data?.values) ? spec.data.values : [];
  const mark = markType(spec?.mark).toLowerCase();

  if (!payload || !spec || rows.length === 0) {
    return <UnsupportedChart reason={payload?.reason} />;
  }

  if (mark === 'bar') {
    if (isQuantitative(spec.encoding?.x) && !isQuantitative(spec.encoding?.y)) {
      return <HorizontalBarChart spec={spec} rows={rows} />;
    }
    return <VerticalBarChart spec={spec} rows={rows} />;
  }

  if (mark === 'line') {
    return <LineChart spec={spec} rows={rows} />;
  }

  return <UnsupportedChart reason={payload.reason} />;
}
