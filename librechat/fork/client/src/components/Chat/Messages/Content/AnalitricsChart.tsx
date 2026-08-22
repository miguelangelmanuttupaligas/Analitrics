import { useMemo, useState } from 'react';
import type { ReactNode } from 'react';

type ChartPoint = {
  label: string;
  value: number;
};

type ChartPayload = {
  chart_required?: boolean;
  chart_type?: 'bar' | 'line';
  title?: string;
  category_field?: string;
  value_field?: string;
  points?: ChartPoint[];
};

type SortMode = 'original' | 'desc' | 'asc';

type TooltipState = {
  label: string;
  value: number;
  x: number;
  y: number;
} | null;

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

const normalizePoints = (points?: ChartPoint[]) =>
  (Array.isArray(points) ? points : [])
    .map((point) => ({
      label: String(point?.label ?? ''),
      value: Number(point?.value ?? 0),
    }))
    .filter((point) => point.label && Number.isFinite(point.value))
    .slice(0, 10);

function EmptyChart() {
  return (
    <div className="my-3 rounded-lg border border-border-light bg-surface-primary p-3 text-sm text-text-secondary">
      No hay datos suficientes para renderizar el gráfico.
    </div>
  );
}

function sortPoints(points: ChartPoint[], sortMode: SortMode) {
  if (sortMode === 'desc') {
    return [...points].sort((a, b) => b.value - a.value);
  }
  if (sortMode === 'asc') {
    return [...points].sort((a, b) => a.value - b.value);
  }
  return points;
}

function ChartTooltip({ tooltip }: { tooltip: TooltipState }) {
  if (!tooltip) {
    return null;
  }
  return (
    <div
      className="pointer-events-none absolute z-10 rounded-md border border-border-light bg-surface-primary px-2.5 py-2 text-xs shadow-lg"
      style={{ left: tooltip.x + 12, top: tooltip.y + 12 }}
    >
      <div className="max-w-64 truncate font-medium text-text-primary">{tooltip.label}</div>
      <div className="mt-0.5 tabular-nums text-text-secondary">{numberFormat.format(tooltip.value)}</div>
    </div>
  );
}

function ChartShell({
  title,
  valueLabel,
  sortMode,
  zoom,
  tooltip,
  onSortChange,
  onZoomChange,
  children,
}: {
  title: string;
  valueLabel: string;
  sortMode: SortMode;
  zoom: number;
  tooltip: TooltipState;
  onSortChange: (sortMode: SortMode) => void;
  onZoomChange: (zoom: number) => void;
  children: ReactNode;
}) {
  return (
    <div className="relative my-3 rounded-lg border border-border-light bg-surface-primary p-3">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-text-primary">{title}</div>
          <div className="text-xs text-text-secondary">{valueLabel}</div>
        </div>
        <div className="flex items-center gap-2 text-xs text-text-secondary">
          <label className="flex items-center gap-1">
            <span>Orden</span>
            <select
              className="rounded-md border border-border-light bg-surface-secondary px-2 py-1 text-text-primary outline-none"
              value={sortMode}
              onChange={(event) => onSortChange(event.target.value as SortMode)}
            >
              <option value="original">Original</option>
              <option value="desc">Mayor</option>
              <option value="asc">Menor</option>
            </select>
          </label>
          <label className="flex items-center gap-1">
            <span>Zoom</span>
            <select
              className="rounded-md border border-border-light bg-surface-secondary px-2 py-1 text-text-primary outline-none"
              value={String(zoom)}
              onChange={(event) => onZoomChange(Number(event.target.value))}
            >
              <option value="1">100%</option>
              <option value="1.25">125%</option>
              <option value="1.5">150%</option>
            </select>
          </label>
        </div>
      </div>
      {children}
      <ChartTooltip tooltip={tooltip} />
    </div>
  );
}

function BarChart({
  points,
  zoom,
  onTooltip,
}: {
  points: ChartPoint[];
  zoom: number;
  onTooltip: (tooltip: TooltipState) => void;
}) {
  const max = Math.max(...points.map((point) => point.value), 1);

  return (
    <div className="overflow-x-auto pb-1">
      <div className="space-y-2" style={{ minWidth: `${zoom * 100}%` }}>
        {points.map((point, index) => {
          const width = Math.max((point.value / max) * 100, 2);
          return (
            <div
              key={`${point.label}-${index}`}
              className="grid grid-cols-[minmax(8rem,15rem)_1fr_auto] items-center gap-3"
              onMouseLeave={() => onTooltip(null)}
            >
              <div className="truncate text-xs text-text-secondary" title={point.label}>
                {point.label}
              </div>
              <div className="h-5 overflow-hidden rounded bg-surface-secondary">
                <div
                  className="h-full rounded bg-green-500 transition-[width]"
                  style={{ width: `${width}%` }}
                  onMouseMove={(event) =>
                    onTooltip({
                      label: point.label,
                      value: point.value,
                      x: event.nativeEvent.offsetX + event.currentTarget.offsetLeft,
                      y: event.currentTarget.offsetTop,
                    })
                  }
                />
              </div>
              <div className="min-w-16 text-right text-xs tabular-nums text-text-primary">
                {numberFormat.format(point.value)}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function LineChart({
  points,
  zoom,
  onTooltip,
}: {
  points: ChartPoint[];
  zoom: number;
  onTooltip: (tooltip: TooltipState) => void;
}) {
  const width = 720;
  const height = 280;
  const padX = 44;
  const padY = 34;
  const max = Math.max(...points.map((point) => point.value), 1);
  const min = Math.min(...points.map((point) => point.value), 0);
  const range = Math.max(max - min, 1);
  const chartWidth = width - padX * 2;
  const chartHeight = height - padY * 2;
  const coords = points.map((point, index) => ({
    ...point,
    x: padX + (index / Math.max(points.length - 1, 1)) * chartWidth,
    y: height - padY - ((point.value - min) / range) * chartHeight,
  }));
  const polyline = coords.map((point) => `${point.x},${point.y}`).join(' ');

  return (
    <div className="overflow-x-auto pb-1">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="h-auto"
        style={{ width: `${zoom * 100}%`, minWidth: '100%' }}
        role="img"
        aria-label="Gráfico de línea"
        onMouseLeave={() => onTooltip(null)}
      >
        <line x1={padX} y1={height - padY} x2={width - padX} y2={height - padY} className="stroke-border-light" />
        <line x1={padX} y1={padY} x2={padX} y2={height - padY} className="stroke-border-light" />
        <polyline fill="none" stroke="currentColor" strokeWidth="3" points={polyline} className="text-green-500" />
        {coords.map((point, index) => (
          <g key={`${point.label}-${index}`}>
            <circle
              cx={point.x}
              cy={point.y}
              r="5"
              className="fill-green-500"
              onMouseMove={(event) =>
                onTooltip({
                  label: point.label,
                  value: point.value,
                  x: event.nativeEvent.offsetX,
                  y: event.nativeEvent.offsetY,
                })
              }
            />
            <title>{`${point.label}: ${numberFormat.format(point.value)}`}</title>
          </g>
        ))}
      </svg>
      <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-text-secondary sm:grid-cols-3">
        {points.map((point, index) => (
          <div key={`${point.label}-legend-${index}`} className="truncate" title={point.label}>
            {index + 1}. {point.label}
          </div>
        ))}
      </div>
    </div>
  );
}

export default function AnalitricsChart({ output }: { output?: string | null }) {
  const payload = parsePayload(output);
  const rawPoints = normalizePoints(payload?.points);
  const [sortMode, setSortMode] = useState<SortMode>('original');
  const [zoom, setZoom] = useState(1);
  const [tooltip, setTooltip] = useState<TooltipState>(null);
  const points = useMemo(() => sortPoints(rawPoints, sortMode), [rawPoints, sortMode]);

  if (!payload?.chart_required || points.length === 0) {
    return <EmptyChart />;
  }

  const title = payload.title || 'Gráfico';
  const valueLabel = payload.value_field || 'valor';

  return (
    <ChartShell
      title={title}
      valueLabel={valueLabel}
      sortMode={sortMode}
      zoom={zoom}
      tooltip={tooltip}
      onSortChange={setSortMode}
      onZoomChange={setZoom}
    >
      {payload.chart_type === 'line' ? (
        <LineChart points={points} zoom={zoom} onTooltip={setTooltip} />
      ) : (
        <BarChart points={points} zoom={zoom} onTooltip={setTooltip} />
      )}
    </ChartShell>
  );
}
