import { useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { useLocalize } from '~/hooks';

type ChartPoint = {
  label: string;
  group?: string | null;
  value?: number;
  [key: string]: string | number | null | undefined;
};

type ChartPayload = {
  chart_required?: boolean;
  chart_type?: 'bar' | 'line';
  title?: string;
  category_field?: string;
  value_field?: string;
  y_keys?: string[];
  group_field?: string | null;
  points?: ChartPoint[];
};

type SortMode = 'original' | 'desc' | 'asc';

type TooltipState = {
  point: ChartPoint;
  metric: string;
  x: number;
  y: number;
} | null;

const colors = ['#22c55e', '#38bdf8', '#f59e0b', '#a78bfa'];

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

const isFiniteNumber = (value: unknown): value is number => {
  const number = Number(value);
  return Number.isFinite(number);
};

const metricLabel = (metric: string) =>
  metric
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
    .replace('Total Sales', 'Ventas')
    .replace('Unique Students', 'Alumnos');

const normalizePoints = (points?: ChartPoint[]) =>
  (Array.isArray(points) ? points : [])
    .map((point) => ({
      ...point,
      label: String(point?.label ?? ''),
    }))
    .filter((point) => point.label)
    .slice(0, 12);

function EmptyChart() {
  const localize = useLocalize();
  return (
    <div className="my-3 rounded-lg border border-border-light bg-surface-primary p-3 text-sm text-text-secondary">
      {localize('com_analitrics_chart_not_enough_data_render')}
    </div>
  );
}

function sortPoints(points: ChartPoint[], sortMode: SortMode, metric: string) {
  if (sortMode === 'desc') {
    return [...points].sort((a, b) => Number(b[metric] ?? 0) - Number(a[metric] ?? 0));
  }
  if (sortMode === 'asc') {
    return [...points].sort((a, b) => Number(a[metric] ?? 0) - Number(b[metric] ?? 0));
  }
  return points;
}

function ChartTooltip({ tooltip, metrics }: { tooltip: TooltipState; metrics: string[] }) {
  if (!tooltip) {
    return null;
  }
  return (
    <div
      className="pointer-events-none absolute z-10 rounded-md border border-border-light bg-surface-primary px-2.5 py-2 text-xs shadow-lg"
      style={{ left: tooltip.x + 12, top: tooltip.y + 12 }}
    >
      <div className="max-w-72 truncate font-medium text-text-primary">{tooltip.point.label}</div>
      <div className="mt-1 space-y-0.5">
        {metrics.map((metric) => (
          <div key={metric} className="flex justify-between gap-4 tabular-nums text-text-secondary">
            <span>{metricLabel(metric)}</span>
            <span>{numberFormat.format(Number(tooltip.point[metric] ?? 0))}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ChartShell({
  title,
  metrics,
  selectedMetric,
  sortMode,
  zoom,
  tooltip,
  onMetricChange,
  onSortChange,
  onZoomChange,
  children,
}: {
  title: string;
  metrics: string[];
  selectedMetric: string;
  sortMode: SortMode;
  zoom: number;
  tooltip: TooltipState;
  onMetricChange: (metric: string) => void;
  onSortChange: (sortMode: SortMode) => void;
  onZoomChange: (zoom: number) => void;
  children: ReactNode;
}) {
  const localize = useLocalize();
  return (
    <div className="relative my-3 rounded-lg border border-border-light bg-surface-primary p-3">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium text-text-primary">{title}</div>
          <div className="text-xs text-text-secondary">
            {metrics.length > 1 ? localize('com_analitrics_chart_select_metric') : metricLabel(selectedMetric)}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs text-text-secondary">
          {metrics.length > 1 && (
            <label className="flex items-center gap-1">
              <span>{localize('com_analitrics_chart_metric')}</span>
              <select
                className="rounded-md border border-border-light bg-surface-secondary px-2 py-1 text-text-primary outline-none"
                value={selectedMetric}
                onChange={(event) => onMetricChange(event.target.value)}
              >
                {metrics.map((metric) => (
                  <option key={metric} value={metric}>
                    {metricLabel(metric)}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="flex items-center gap-1">
            <span>{localize('com_analitrics_chart_order')}</span>
            <select
              className="rounded-md border border-border-light bg-surface-secondary px-2 py-1 text-text-primary outline-none"
              value={sortMode}
              onChange={(event) => onSortChange(event.target.value as SortMode)}
            >
              <option value="original">{localize('com_analitrics_chart_order_original')}</option>
              <option value="desc">{localize('com_analitrics_chart_order_desc')}</option>
              <option value="asc">{localize('com_analitrics_chart_order_asc')}</option>
            </select>
          </label>
          <label className="flex items-center gap-1">
            <span>{localize('com_analitrics_chart_zoom')}</span>
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
      <ChartTooltip tooltip={tooltip} metrics={metrics} />
    </div>
  );
}

function BarChart({
  points,
  metrics,
  selectedMetric,
  zoom,
  onTooltip,
}: {
  points: ChartPoint[];
  metrics: string[];
  selectedMetric: string;
  zoom: number;
  onTooltip: (tooltip: TooltipState) => void;
}) {
  const max = Math.max(...points.map((point) => Number(point[selectedMetric] ?? 0)), 1);

  return (
    <div className="overflow-x-auto pb-1">
      <div className="space-y-2" style={{ minWidth: `${zoom * 100}%` }}>
        {points.map((point, index) => {
          const value = Number(point[selectedMetric] ?? 0);
          const width = Math.max((value / max) * 100, 2);
          return (
            <div
              key={`${point.label}-${index}`}
              className="grid grid-cols-[minmax(10rem,18rem)_1fr_auto] items-center gap-3"
              onMouseLeave={() => onTooltip(null)}
            >
              <div className="min-w-0">
                <div className="truncate text-xs text-text-primary" title={point.label}>
                  {point.label}
                </div>
                {point.group && (
                  <div className="truncate text-[11px] text-text-secondary" title={String(point.group)}>
                    {point.group}
                  </div>
                )}
              </div>
              <div className="h-5 overflow-hidden rounded bg-surface-secondary">
                <div
                  className="h-full rounded transition-[width]"
                  style={{ width: `${width}%`, backgroundColor: colors[metrics.indexOf(selectedMetric) % colors.length] }}
                  onMouseMove={(event) =>
                    onTooltip({
                      point,
                      metric: selectedMetric,
                      x: event.nativeEvent.offsetX + event.currentTarget.offsetLeft,
                      y: event.currentTarget.offsetTop,
                    })
                  }
                />
              </div>
              <div className="min-w-16 text-right text-xs tabular-nums text-text-primary">
                {numberFormat.format(value)}
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
  selectedMetric,
  zoom,
  onTooltip,
  lineChartLabel,
}: {
  points: ChartPoint[];
  selectedMetric: string;
  zoom: number;
  onTooltip: (tooltip: TooltipState) => void;
  lineChartLabel: string;
}) {
  const width = 720;
  const height = 280;
  const padX = 44;
  const padY = 34;
  const max = Math.max(...points.map((point) => Number(point[selectedMetric] ?? 0)), 1);
  const min = Math.min(...points.map((point) => Number(point[selectedMetric] ?? 0)), 0);
  const range = Math.max(max - min, 1);
  const chartWidth = width - padX * 2;
  const chartHeight = height - padY * 2;
  const coords = points.map((point, index) => ({
    ...point,
    x: padX + (index / Math.max(points.length - 1, 1)) * chartWidth,
    y: height - padY - ((Number(point[selectedMetric] ?? 0) - min) / range) * chartHeight,
  }));
  const polyline = coords.map((point) => `${point.x},${point.y}`).join(' ');

  return (
    <div className="overflow-x-auto pb-1">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="h-auto"
        style={{ width: `${zoom * 100}%`, minWidth: '100%' }}
        role="img"
        aria-label={lineChartLabel}
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
                  point,
                  metric: selectedMetric,
                  x: event.nativeEvent.offsetX,
                  y: event.nativeEvent.offsetY,
                })
              }
            />
            <title>{`${point.label}: ${numberFormat.format(Number(point[selectedMetric] ?? 0))}`}</title>
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
  const localize = useLocalize();
  const payload = parsePayload(output);
  const rawPoints = normalizePoints(payload?.points);
  const metrics = useMemo(() => {
    const explicit = Array.isArray(payload?.y_keys) ? payload.y_keys : [];
    const fallback = payload?.value_field ? [payload.value_field] : ['value'];
    return (explicit.length > 0 ? explicit : fallback).filter((metric) =>
      rawPoints.some((point) => isFiniteNumber(point[metric])),
    );
  }, [payload?.value_field, payload?.y_keys, rawPoints]);
  const [sortMode, setSortMode] = useState<SortMode>('original');
  const [zoom, setZoom] = useState(1);
  const [tooltip, setTooltip] = useState<TooltipState>(null);
  const [selectedMetric, setSelectedMetric] = useState(metrics[0] ?? 'value');
  const effectiveMetric = metrics.includes(selectedMetric) ? selectedMetric : metrics[0];
  const points = useMemo(
    () => sortPoints(rawPoints, sortMode, effectiveMetric ?? 'value'),
    [rawPoints, sortMode, effectiveMetric],
  );

  if (!payload?.chart_required || points.length === 0 || !effectiveMetric) {
    return <EmptyChart />;
  }

  return (
    <ChartShell
      title={payload.title || localize('com_analitrics_dashboard_chart_fallback')}
      metrics={metrics}
      selectedMetric={effectiveMetric}
      sortMode={sortMode}
      zoom={zoom}
      tooltip={tooltip}
      onMetricChange={setSelectedMetric}
      onSortChange={setSortMode}
      onZoomChange={setZoom}
    >
      {payload.chart_type === 'line' ? (
        <LineChart
          points={points}
          selectedMetric={effectiveMetric}
          zoom={zoom}
          onTooltip={setTooltip}
          lineChartLabel={localize('com_analitrics_chart_line_label')}
        />
      ) : (
        <BarChart
          points={points}
          metrics={metrics}
          selectedMetric={effectiveMetric}
          zoom={zoom}
          onTooltip={setTooltip}
        />
      )}
    </ChartShell>
  );
}
