import { useEffect, useMemo, useRef, useState } from 'react';
import * as echarts from 'echarts';
import { ArrowDownAZ, ArrowUpAZ, Maximize2, RotateCcw } from 'lucide-react';
import { useLocalize } from '~/hooks';
import { cn } from '~/utils';

type AnalitricsChartSpec = {
  version?: number;
  renderer?: string;
  type?: 'bar' | 'line' | 'pie' | string;
  title?: string;
  xField?: string;
  yFields?: string[];
  sort?: 'preserve' | 'asc' | 'desc' | string;
  limit?: number;
  valueFormat?: string;
  categoryLabel?: string;
  notes?: string;
};

type SortMode = 'preserve' | 'asc' | 'desc';

const numberFormat = new Intl.NumberFormat('es-PE', {
  maximumFractionDigits: 2,
});

function numericValue(value: unknown): number {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function formatValue(value: unknown, valueFormat?: string) {
  const number = numericValue(value);
  if (valueFormat === 'percent') {
    return `${numberFormat.format(number)}%`;
  }
  return numberFormat.format(number);
}

function normalizeRows(
  rows: Array<Record<string, unknown>>,
  spec: AnalitricsChartSpec,
  sortMode: SortMode,
) {
  const xField = spec.xField;
  const yFields = spec.yFields?.filter(Boolean) ?? [];
  if (!xField || yFields.length === 0) {
    return [];
  }
  const limit = Math.max(1, Math.min(Number(spec.limit || 12), 50));
  const sortField = yFields[0];
  const mapped = rows
    .map((row) => ({
      ...row,
      __label: String(row[xField] ?? ''),
      __value: numericValue(row[sortField]),
    }))
    .filter((row) => row.__label);
  if (sortMode === 'asc') {
    mapped.sort((left, right) => left.__value - right.__value);
  }
  if (sortMode === 'desc') {
    mapped.sort((left, right) => right.__value - left.__value);
  }
  return mapped.slice(0, limit);
}

export default function AnalitricsEChart({
  spec,
  rows,
  className,
}: {
  spec?: AnalitricsChartSpec | Record<string, unknown>;
  rows: Array<Record<string, unknown>>;
  className?: string;
}) {
  const localize = useLocalize();
  const chartRef = useRef<HTMLDivElement | null>(null);
  const chartInstance = useRef<echarts.ECharts | null>(null);
  const safeSpec = (spec ?? {}) as AnalitricsChartSpec;
  const [sortMode, setSortMode] = useState<SortMode>((safeSpec.sort as SortMode) || 'preserve');
  const [expanded, setExpanded] = useState(false);

  const data = useMemo(() => normalizeRows(rows, safeSpec, sortMode), [rows, sortMode, safeSpec]);
  const yFields = safeSpec.yFields?.filter(Boolean) ?? [];
  const option = useMemo<echarts.EChartsOption>(() => {
    if (!safeSpec.xField || yFields.length === 0 || data.length === 0) {
      return {};
    }
    const primaryYField = yFields[0];
    if (safeSpec.type === 'pie') {
      return {
        tooltip: {
          trigger: 'item',
          formatter: (params) => `${params.name}: ${formatValue(params.value, safeSpec.valueFormat)}`,
        },
        series: [
          {
            name: primaryYField,
            type: 'pie',
            radius: ['42%', '72%'],
            data: data.map((row) => ({ name: row.__label, value: numericValue(row[primaryYField]) })),
            label: { overflow: 'truncate', width: 120 },
          },
        ],
      };
    }
    return {
      grid: { top: 28, right: 24, bottom: 80, left: 72 },
      tooltip: {
        trigger: 'axis',
        valueFormatter: (value) => formatValue(value, safeSpec.valueFormat),
      },
      dataZoom: [
        { type: 'inside', throttle: 60 },
        { type: 'slider', height: 18, bottom: 32 },
      ],
      xAxis: {
        type: 'category',
        data: data.map((row) => row.__label),
        axisLabel: { interval: 0, rotate: data.length > 6 ? 28 : 0, hideOverlap: true },
      },
      yAxis: { type: 'value' },
      legend: yFields.length > 1 ? { top: 0, type: 'scroll' } : undefined,
      series: yFields.map((field) => ({
        name: field,
        type: safeSpec.type === 'line' ? 'line' : 'bar',
        smooth: safeSpec.type === 'line',
        data: data.map((row) => numericValue(row[field])),
      })),
    };
  }, [data, safeSpec, yFields]);

  useEffect(() => {
    if (!chartRef.current) {
      return;
    }
    chartInstance.current = echarts.init(chartRef.current, null, { renderer: 'canvas' });
    return () => {
      chartInstance.current?.dispose();
      chartInstance.current = null;
    };
  }, []);

  useEffect(() => {
    chartInstance.current?.setOption(option, true);
  }, [option]);

  useEffect(() => {
    if (!chartRef.current) {
      return;
    }
    const observer = new ResizeObserver(() => chartInstance.current?.resize());
    observer.observe(chartRef.current);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    setTimeout(() => chartInstance.current?.resize(), 0);
  }, [expanded]);

  if (!safeSpec.xField || yFields.length === 0 || data.length === 0) {
    return (
      <div className="rounded-lg border border-border-light bg-surface-secondary p-4 text-sm text-text-secondary">
        {localize('com_analitrics_chart_not_enough_data')}
      </div>
    );
  }

  return (
    <div
      className={cn(
        'rounded-lg border border-border-light bg-surface-primary p-3',
        expanded && 'fixed inset-6 z-50',
        className,
      )}
    >
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h4 className="truncate text-sm font-semibold text-text-primary">
            {safeSpec.title || localize('com_analitrics_dashboard_chart_fallback')}
          </h4>
          <p className="mt-0.5 text-xs text-text-secondary">
            {localize('com_analitrics_chart_by', {
              category: safeSpec.categoryLabel || safeSpec.xField,
              metrics: yFields.join(', '),
            })}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            className="rounded-lg p-2 text-text-secondary hover:bg-surface-hover hover:text-text-primary"
            onClick={() => setSortMode('desc')}
            aria-label={localize('com_analitrics_chart_sort_desc')}
          >
            <ArrowDownAZ className="size-4" aria-hidden="true" />
          </button>
          <button
            type="button"
            className="rounded-lg p-2 text-text-secondary hover:bg-surface-hover hover:text-text-primary"
            onClick={() => setSortMode('asc')}
            aria-label={localize('com_analitrics_chart_sort_asc')}
          >
            <ArrowUpAZ className="size-4" aria-hidden="true" />
          </button>
          <button
            type="button"
            className="rounded-lg p-2 text-text-secondary hover:bg-surface-hover hover:text-text-primary"
            onClick={() => setSortMode('preserve')}
            aria-label={localize('com_analitrics_chart_sort_restore')}
          >
            <RotateCcw className="size-4" aria-hidden="true" />
          </button>
          <button
            type="button"
            className="rounded-lg p-2 text-text-secondary hover:bg-surface-hover hover:text-text-primary"
            onClick={() => setExpanded((value) => !value)}
            aria-label={
              expanded ? localize('com_analitrics_chart_close_zoom') : localize('com_analitrics_chart_expand')
            }
          >
            <Maximize2 className="size-4" aria-hidden="true" />
          </button>
        </div>
      </div>
      <div ref={chartRef} className={cn('h-80 w-full', expanded && 'h-[calc(100vh-9rem)]')} />
    </div>
  );
}
