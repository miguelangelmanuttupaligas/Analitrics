import { useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  AlertCircle,
  CalendarDays,
  CheckCircle2,
  FileSpreadsheet,
  LayoutDashboard,
  PencilLine,
  RefreshCw,
  Sigma,
  Tags,
  X,
  type LucideIcon,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Button, Sidebar, TooltipAnchor } from '@librechat/client';
import { Constants } from 'librechat-data-provider';
import type {
  AnalitricsColumn,
  AnalitricsFeedback,
  AnalitricsFile,
  AnalitricsProfile,
  AnalitricsAnalysisState,
  AnalitricsTable,
} from '~/hooks';
import {
  useAnalitricsContext,
  useAnalitricsDashboards,
  useCreateAnalitricsDashboard,
  useLocalize,
  useSaveAnalitricsCatalogFeedback,
} from '~/hooks';
import type { TranslationKeys } from '~/hooks/useLocalize';
import { cn } from '~/utils';

type AnalitricsContextPanelProps = {
  conversationId?: string | null;
  onCollapsePanel?: () => void;
};

type NormalizedColumn = {
  name: string;
  type: string;
  distinctCount?: number | null;
  average?: number | null;
  sum?: number | null;
  min?: number | null;
  max?: number | null;
};

type DatasetInsight = {
  fileId: string;
  name: string;
  filename?: string | null;
  rowCount: number;
  columnCount: number;
  metricCandidates: string[];
  dateCandidates: string[];
  segmentCandidates: string[];
  numericCount: number;
  columns: NormalizedColumn[];
};

type ExecutiveKpi = {
  key: string;
  label: string;
  value: string;
  detail: string;
  confidence: 'known' | 'estimated' | 'pending';
};

type FeedbackSource = {
  fileId: string;
  label: string;
  filename?: string;
};

type CatalogFeedbackStep = {
  step: number;
  labelKey: TranslationKeys;
  promptKey: TranslationKeys;
  placeholderKey: TranslationKeys;
};

type PanelView = 'general' | 'catalog';
type LocalizeFn = ReturnType<typeof useLocalize>;

const feedbackSteps: CatalogFeedbackStep[] = [
  {
    step: 1,
    labelKey: 'com_analitrics_step_1_label',
    promptKey: 'com_analitrics_step_1_prompt',
    placeholderKey: 'com_analitrics_step_1_placeholder',
  },
  {
    step: 2,
    labelKey: 'com_analitrics_step_2_label',
    promptKey: 'com_analitrics_step_2_prompt',
    placeholderKey: 'com_analitrics_step_2_placeholder',
  },
  {
    step: 3,
    labelKey: 'com_analitrics_step_3_label',
    promptKey: 'com_analitrics_step_3_prompt',
    placeholderKey: 'com_analitrics_step_3_placeholder',
  },
  {
    step: 4,
    labelKey: 'com_analitrics_step_4_label',
    promptKey: 'com_analitrics_step_4_prompt',
    placeholderKey: 'com_analitrics_step_4_placeholder',
  },
  {
    step: 5,
    labelKey: 'com_analitrics_step_5_label',
    promptKey: 'com_analitrics_step_5_prompt',
    placeholderKey: 'com_analitrics_step_5_placeholder',
  },
  {
    step: 6,
    labelKey: 'com_analitrics_step_6_label',
    promptKey: 'com_analitrics_step_6_prompt',
    placeholderKey: 'com_analitrics_step_6_placeholder',
  },
];

const numberFormat = new Intl.NumberFormat('es-PE');

const formatNumber = (value?: number | null) =>
  numberFormat.format(Number.isFinite(value ?? NaN) ? Number(value) : 0);

const businessSourceName = (index: number, localize: LocalizeFn) =>
  localize('com_analitrics_business_scope', { index: index + 1 });

const fileDisplayName = (file: AnalitricsFile, index: number, localize: LocalizeFn) =>
  file.filename ||
  file.storageKey?.split('/').at(-1) ||
  localize('com_analitrics_file_fallback', { index: index + 1 });

const fileId = (file: AnalitricsFile, index: number) =>
  file.file_id || file.storageKey || file.filename || `file-${index}`;

const buildFeedbackSources = (files: AnalitricsFile[], localize: LocalizeFn): FeedbackSource[] =>
  files.map((file, index) => {
    const filename = fileDisplayName(file, index, localize);
    return {
      fileId: fileId(file, index),
      filename,
      label: files.length === 1 ? filename : `${index + 1}. ${filename}`,
    };
  });

const normalizeColumn = (column: AnalitricsColumn, localize: LocalizeFn): NormalizedColumn => {
  if (typeof column === 'string') {
    return { name: column, type: '' };
  }
  return {
    name: column?.name || localize('com_analitrics_column_fallback'),
    type: column?.type || '',
    distinctCount: column?.distinct_count,
    average: column?.avg,
    sum: column?.sum,
    min: column?.min,
    max: column?.max,
  };
};

const hasAnyTerm = (name: string, terms: string[]) =>
  terms.some((term) => name.toLowerCase().includes(term));

const isNumericType = (type?: string) =>
  /\b(decimal|double|float|real|numeric|number|int|bigint|smallint|tinyint|hugeint)\b/i.test(
    type || '',
  );

const isDateType = (type?: string) => /\b(date|time|timestamp)\b/i.test(type || '');

const isLikelyKpi = (name: string, type?: string) =>
  isNumericType(type) &&
  hasAnyTerm(name, [
    'amount',
    'cantidad',
    'cost',
    'costo',
    'importe',
    'ingreso',
    'monto',
    'precio',
    'price',
    'qty',
    'rate',
    'ratio',
    'revenue',
    'sales',
    'score',
    'ticket',
    'total',
    'valor',
    'venta',
  ]);

const isLikelySegment = (name: string, type?: string) =>
  !isNumericType(type) &&
  !isDateType(type) &&
  hasAnyTerm(name, [
    'area',
    'canal',
    'categoria',
    'category',
    'channel',
    'cliente',
    'country',
    'curso',
    'customer',
    'estado',
    'pais',
    'product',
    'producto',
    'region',
    'sede',
    'segment',
    'segmento',
    'status',
    'tipo',
    'type',
    'unidad',
  ]);

const unique = (items: string[]) => [...new Set(items.filter(Boolean))];

const currencyFormat = new Intl.NumberFormat('es-PE', {
  maximumFractionDigits: 0,
});

const compactText = (value: string, fallback: string) =>
  value.trim().length > 0 ? value.trim() : fallback;

const latestFeedbackForSteps = (feedback: AnalitricsFeedback[], steps: number[]) =>
  feedback
    .filter((item) => steps.includes(item.step) && item.content?.trim())
    .sort((left, right) => String(right.updatedAt || '').localeCompare(String(left.updatedAt || '')))[0];

const normalizeForMatch = (value: string) =>
  value
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9_ ]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();

const findColumnByTerms = (columns: NormalizedColumn[], terms: string[]) =>
  columns.find((column) => hasAnyTerm(normalizeForMatch(column.name), terms));

const formatMetricValue = (value?: number | null) => {
  if (value == null || !Number.isFinite(value)) {
    return '';
  }
  return Math.abs(value) >= 1000 ? currencyFormat.format(value) : formatNumber(value);
};

const preferredMetricColumn = (columns: NormalizedColumn[]) => {
  const numericColumns = columns.filter((column) => isNumericType(column.type));
  return (
    numericColumns.find((column) => isLikelyKpi(column.name, column.type) && column.sum != null) ||
    numericColumns.find((column) => column.sum != null) ||
    numericColumns.find((column) => column.average != null) ||
    numericColumns[0]
  );
};

const preferredDimensionColumn = (columns: NormalizedColumn[]) =>
  findColumnByTerms(columns, ['curso', 'producto', 'cliente', 'canal', 'categoria', 'pais', 'sede']) ||
  columns.find((column) => isLikelySegment(column.name, column.type) && column.distinctCount != null) ||
  columns.find((column) => !isNumericType(column.type) && !isDateType(column.type) && column.distinctCount != null);

const buildExecutiveKpis = (
  dataset: DatasetInsight | undefined,
  localize: LocalizeFn,
): ExecutiveKpi[] => {
  const columns = dataset?.columns ?? [];
  const metricColumn = preferredMetricColumn(columns);
  const dimensionColumn = preferredDimensionColumn(columns);
  const dateCount = columns.filter((column) => isDateType(column.type)).length;

  return [
    {
      key: 'rows',
      label: localize('com_analitrics_rows'),
      value: formatNumber(dataset?.rowCount ?? 0),
      detail: localize('com_analitrics_rows_detail'),
      confidence: dataset?.rowCount ? 'known' : 'pending',
    },
    {
      key: 'columns',
      label: localize('com_analitrics_variables'),
      value: formatNumber(dataset?.columnCount ?? 0),
      detail: localize('com_analitrics_variables_detail'),
      confidence: dataset?.columnCount ? 'known' : 'pending',
    },
    {
      key: 'main_metric',
      label: metricColumn?.sum != null ? `Total ${metricColumn.name}` : metricColumn?.name || localize('com_analitrics_main_indicator'),
      value: formatMetricValue(metricColumn?.sum ?? metricColumn?.average) || localize('com_analitrics_pending'),
      detail:
        metricColumn?.sum != null
          ? localize('com_analitrics_sum_detected', { field: metricColumn.name })
          : metricColumn?.average != null
            ? localize('com_analitrics_average_detected', { field: metricColumn.name })
            : localize('com_analitrics_confirm_main_indicator'),
      confidence: metricColumn?.sum != null || metricColumn?.average != null ? 'estimated' : 'pending',
    },
    {
      key: 'main_dimension',
      label: dimensionColumn?.name || localize('com_analitrics_main_dimension'),
      value: dimensionColumn?.distinctCount != null ? formatNumber(dimensionColumn.distinctCount) : localize('com_analitrics_pending'),
      detail:
        dimensionColumn?.distinctCount != null
          ? localize('com_analitrics_distinct_values_detected', { field: dimensionColumn.name })
          : dateCount > 0
            ? localize('com_analitrics_time_fields_detected', { count: dateCount })
            : localize('com_analitrics_confirm_main_dimension'),
      confidence: dimensionColumn?.distinctCount != null ? 'estimated' : 'pending',
    },
  ];
};

const buildExecutiveSummary = (
  dataset: DatasetInsight | undefined,
  feedback: AnalitricsFeedback[],
  localize: LocalizeFn,
) => {
  if (!dataset) {
    return localize('com_analitrics_select_processed_file');
  }
  const metric = preferredMetricColumn(dataset.columns);
  const dimension = preferredDimensionColumn(dataset.columns);
  const userDefinition = latestFeedbackForSteps(feedback, [1, 2, 3, 4, 6])?.content;
  const parts = [
    localize('com_analitrics_file_contains', {
      filename: dataset.filename || dataset.name,
      rows: formatNumber(dataset.rowCount),
      columns: formatNumber(dataset.columnCount),
    }),
    dataset.metricCandidates.length > 0
      ? localize('com_analitrics_detected_indicators', { items: dataset.metricCandidates.slice(0, 3).join(', ') })
      : localize('com_analitrics_missing_business_metrics'),
    dimension ? localize('com_analitrics_obvious_dimension', { field: dimension.name }) : undefined,
    metric ? localize('com_analitrics_useful_numeric_indicator', { field: metric.name }) : undefined,
    userDefinition ? localize('com_analitrics_user_definition', { definition: userDefinition }) : undefined,
  ].filter(Boolean);

  return parts.slice(0, 4).join(' ');
};

const buildDatasetInsights = (
  tables: AnalitricsTable[],
  profiles: AnalitricsProfile[],
  localize: LocalizeFn,
): DatasetInsight[] => {
  const sourceProfiles =
    profiles.length > 0
      ? profiles.filter((profile) => !profile.system_table)
      : tables.map((table) => ({
          row_count: table.rowCount,
          columns: table.columns,
          source_file_id: table.sourceFileId,
          source_filename: table.sourceFilename,
          system_table: table.systemTable,
        }));

  const grouped = new Map<string, AnalitricsProfile[]>();
  for (const profile of sourceProfiles) {
    const key =
      profile.source_file_id ||
      profile.source_filename ||
      profile.table ||
      `dataset-${grouped.size + 1}`;
    grouped.set(key, [...(grouped.get(key) ?? []), profile]);
  }

  return [...grouped.entries()].map(([key, group], index) => {
    const columns = group.flatMap((profile) => profile.columns ?? []).map((column) => normalizeColumn(column, localize));
    const numericColumns = columns.filter((column) => isNumericType(column.type));
    const explicitMetricCandidates = columns
      .filter((column) => isLikelyKpi(column.name, column.type))
      .map((column) => column.name);

    return {
      fileId: key,
      name: businessSourceName(index, localize),
      filename: group.find((profile) => profile.source_filename)?.source_filename,
      rowCount: group.reduce((total, profile) => total + Number(profile.row_count || 0), 0),
      columnCount: columns.length,
      metricCandidates: unique(
        explicitMetricCandidates.length > 0
          ? explicitMetricCandidates
          : numericColumns.map((column) => column.name),
      ).slice(0, 5),
      dateCandidates: unique(
        columns.filter((column) => isDateType(column.type)).map((column) => column.name),
      ).slice(0, 3),
      segmentCandidates: unique(
        columns
          .filter((column) => isLikelySegment(column.name, column.type))
          .map((column) => column.name),
      ).slice(0, 5),
      numericCount: numericColumns.length,
      columns,
    };
  });
};

function KpiCard({ kpi, localize }: { kpi: ExecutiveKpi; localize: LocalizeFn }) {
  const statusLabel =
    kpi.confidence === 'known'
      ? localize('com_analitrics_validated')
      : kpi.confidence === 'estimated'
        ? localize('com_analitrics_estimated')
        : localize('com_analitrics_pending');

  return (
    <article className="rounded-lg border border-border-light bg-surface-secondary p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate text-xs font-medium text-text-secondary">{kpi.label}</h3>
          <p className="mt-1 truncate text-xl font-semibold text-text-primary" title={kpi.value}>
            {kpi.value}
          </p>
        </div>
        <span className="shrink-0 rounded-md border border-border-light px-1.5 py-0.5 text-[10px] text-text-secondary">
          {statusLabel}
        </span>
      </div>
      <p className="mt-2 line-clamp-2 text-xs text-text-secondary" title={kpi.detail}>
        {kpi.detail}
      </p>
    </article>
  );
}

function InsightSection({
  icon: Icon,
  title,
  action,
  children,
}: {
  icon: LucideIcon;
  title: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="rounded-lg border border-border-light bg-surface-primary-alt p-3 text-sm">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2 font-medium text-text-primary">
          <Icon className="size-4 shrink-0 text-text-secondary" aria-hidden="true" />
          <h3 className="truncate">{title}</h3>
        </div>
        {action}
      </div>
      <div className="text-text-secondary">{children}</div>
    </section>
  );
}

function ChipList({ items, empty }: { items: string[]; empty: string }) {
  if (items.length === 0) {
    return <p className="text-xs text-text-secondary">{empty}</p>;
  }

  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((item) => (
        <span
          key={item}
          className="max-w-full truncate rounded-md border border-border-light bg-surface-secondary px-2 py-1 text-xs text-text-primary"
          title={item}
        >
          {item}
        </span>
      ))}
    </div>
  );
}

function FeedbackHistory({
  items,
  localize,
}: {
  items: AnalitricsFeedback[];
  localize: LocalizeFn;
}) {
  if (items.length === 0) {
    return <p className="text-xs text-text-secondary">{localize('com_analitrics_no_saved_contributions')}</p>;
  }

  return (
    <div className="space-y-2">
      {items.slice(0, 3).map((item) => (
        <div key={item.feedbackId ?? `${item.step}-${item.updatedAt}`} className="rounded-md bg-surface-secondary p-2">
          <p className="line-clamp-3 text-xs text-text-secondary">{item.content}</p>
        </div>
      ))}
    </div>
  );
}

function SourceSelector({
  sources,
  selectedFileId,
  onChange,
  localize,
}: {
  sources: FeedbackSource[];
  selectedFileId: string;
  onChange: (fileId: string) => void;
  localize: LocalizeFn;
}) {
  if (sources.length === 0) {
    return (
      <div className="rounded-lg border border-border-light bg-surface-secondary p-3 text-xs text-text-secondary">
        {localize('com_analitrics_source_missing')}
      </div>
    );
  }

  const selected = sources.find((source) => source.fileId === selectedFileId);

  return (
    <div className="rounded-lg border border-border-light bg-surface-secondary p-3">
      <label className="text-xs font-medium text-text-primary" htmlFor="analitrics-feedback-source">
        {localize('com_analitrics_source_enrich')}
      </label>
      <select
        id="analitrics-feedback-source"
        className="mt-2 w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-text-primary outline-none transition-colors focus:border-border-heavy"
        value={selectedFileId}
        onChange={(event) => onChange(event.target.value)}
      >
        {sources.map((source) => (
          <option key={source.fileId} value={source.fileId}>
            {source.label}
          </option>
        ))}
      </select>
      <p className="mt-2 text-xs text-text-secondary">
        {localize('com_analitrics_source_feedback_saved_for', {
          filename: selected?.filename || localize('com_analitrics_selected_file'),
        })}
      </p>
    </div>
  );
}

function ExecutiveFileSelector({
  sources,
  selectedFileId,
  onChange,
  localize,
}: {
  sources: FeedbackSource[];
  selectedFileId: string;
  onChange: (fileId: string) => void;
  localize: LocalizeFn;
}) {
  if (sources.length === 0) {
    return null;
  }

  return (
    <div className="rounded-lg border border-border-light bg-surface-secondary p-3">
      <label className="text-xs font-medium text-text-primary" htmlFor="analitrics-executive-source">
        {localize('com_analitrics_source_analyzed')}
      </label>
      <select
        id="analitrics-executive-source"
        className="mt-2 w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-text-primary outline-none transition-colors focus:border-border-heavy"
        value={selectedFileId}
        onChange={(event) => onChange(event.target.value)}
      >
        {sources.map((source) => (
          <option key={source.fileId} value={source.fileId}>
            {source.label}
          </option>
        ))}
      </select>
    </div>
  );
}

function ViewSwitch({
  activeView,
  onChange,
  localize,
}: {
  activeView: PanelView;
  onChange: (view: PanelView) => void;
  localize: LocalizeFn;
}) {
  const items: Array<{
    id: PanelView;
    titleKey: TranslationKeys;
    icon: LucideIcon;
  }> = [
    {
      id: 'general',
      titleKey: 'com_analitrics_context_general',
      icon: FileSpreadsheet,
    },
    {
      id: 'catalog',
      titleKey: 'com_analitrics_context_catalog',
      icon: PencilLine,
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-2">
      {items.map((item) => {
        const Icon = item.icon;
        const active = activeView === item.id;
        return (
          <button
            key={item.id}
            type="button"
            className={cn(
              'rounded-lg border p-3 text-left transition-colors focus:outline-none focus:ring-2 focus:ring-border-heavy',
              active
                ? 'border-border-heavy bg-surface-secondary text-text-primary'
                : 'border-border-light bg-surface-primary-alt text-text-secondary hover:bg-surface-hover hover:text-text-primary',
            )}
            onClick={() => onChange(item.id)}
            aria-pressed={active}
          >
            <div className="flex items-center gap-2">
              <Icon className="size-4 shrink-0" aria-hidden="true" />
              <span className="text-sm font-semibold">{localize(item.titleKey)}</span>
            </div>
          </button>
        );
      })}
    </div>
  );
}

const feedbackBelongsToSource = (item: AnalitricsFeedback, source: FeedbackSource | undefined) => {
  if (!source) {
    return false;
  }
  if (item.sourceFileId) {
    return item.sourceFileId === source.fileId;
  }
  if (item.sourceFilename && source.filename) {
    return item.sourceFilename === source.filename;
  }
  return false;
};

const suggestedFeedbackBelongsToSource = (
  item: { sourceFileId?: string | null; sourceFilename?: string | null } | null | undefined,
  source: FeedbackSource | undefined,
) => {
  if (!item || !source) {
    return false;
  }
  if (item.sourceFileId) {
    return item.sourceFileId === source.fileId;
  }
  if (item.sourceFilename && source.filename) {
    return item.sourceFilename === source.filename;
  }
  return false;
};

const isDashboardReadyState = (state: AnalitricsAnalysisState) => {
  const sql = String(state.last_sql || '').trim();
  const confidence = String(state.state?.confidence || '').toLowerCase();
  const intent = String(state.intent || state.state?.conversation_plan?.request_kind || '').toLowerCase();
  return Boolean(sql) && confidence !== 'low' && intent !== 'metadata_literal' && intent !== 'out_of_scope';
};

function CatalogFeedbackCard({
  step,
  conversationId,
  saved,
  disabled,
  source,
  expanded,
  onToggle,
  suggestedContent,
  localize,
}: {
  step: CatalogFeedbackStep;
  conversationId?: string | null;
  saved: AnalitricsFeedback[];
  disabled: boolean;
  source?: FeedbackSource;
  expanded: boolean;
  onToggle: () => void;
  suggestedContent?: string;
  localize: LocalizeFn;
}) {
  const [content, setContent] = useState('');
  const saveFeedback = useSaveAnalitricsCatalogFeedback(conversationId);
  const canSave = !disabled && content.trim().length > 0 && !saveFeedback.isLoading;

  useEffect(() => {
    if (expanded && suggestedContent && !content.trim()) {
      setContent(suggestedContent);
    }
  }, [content, expanded, suggestedContent]);

  const handleSave = () => {
    if (!canSave) {
      return;
    }
    saveFeedback.mutate(
      {
        sourceFileId: source?.fileId,
        sourceFilename: source?.filename,
        step: step.step,
        label: localize(step.labelKey),
        content,
      },
      {
        onSuccess: () => {
          setContent('');
        },
      },
    );
  };

  return (
    <article className="rounded-lg border border-border-light bg-surface-primary-alt">
      <div className="flex w-full items-start gap-2 p-3">
        <div className="flex size-6 shrink-0 items-center justify-center rounded-full bg-surface-secondary text-xs font-semibold text-text-primary">
          {step.step}
        </div>
        <div className="min-w-0 flex-1">
          <h4 className="text-sm font-medium text-text-primary">{localize(step.labelKey)}</h4>
          <p className="mt-1 text-xs text-text-secondary">{localize(step.promptKey)}</p>
          {!expanded && (
            <div className="mt-2">
              <FeedbackHistory items={saved} localize={localize} />
            </div>
          )}
        </div>
        {saved.length > 0 && (
          <CheckCircle2
            className="mt-0.5 size-4 shrink-0 text-green-500"
            aria-label={localize('com_analitrics_has_saved_contributions')}
          />
        )}
        <button
          type="button"
          className="rounded-md p-1.5 text-text-secondary transition-colors hover:bg-surface-hover hover:text-text-primary focus:outline-none focus:ring-2 focus:ring-border-heavy"
          onClick={onToggle}
          aria-label={
            expanded
              ? localize('com_analitrics_close_edit', { label: localize(step.labelKey) })
              : localize('com_analitrics_edit_label', { label: localize(step.labelKey) })
          }
          aria-expanded={expanded}
        >
          {expanded ? <X className="size-4" aria-hidden="true" /> : <PencilLine className="size-4" aria-hidden="true" />}
        </button>
      </div>
      {expanded && (
        <div className="border-t border-border-light p-3 pt-2">
          <textarea
            className="min-h-20 w-full resize-none rounded-lg border border-border-light bg-transparent px-3 py-2 text-sm text-text-primary outline-none transition-colors placeholder:text-text-tertiary focus:border-border-heavy disabled:cursor-not-allowed disabled:opacity-60"
            value={content}
            placeholder={localize(step.placeholderKey)}
            disabled={disabled || saveFeedback.isLoading}
            onChange={(event) => setContent(event.target.value)}
          />
          <div className="mt-2 flex items-center justify-between gap-2">
            <span className="text-xs text-text-secondary">
              {saveFeedback.isError
                ? localize('com_analitrics_save_error')
                : saved.length > 0
                  ? localize('com_analitrics_saved_contributions', { count: saved.length })
                  : localize('com_analitrics_optional')}
            </span>
            <button
              type="button"
              className="inline-flex items-center gap-1.5 rounded-lg border border-border-light px-2.5 py-1.5 text-xs font-medium text-text-primary transition-colors hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-50"
              disabled={!canSave}
              onClick={handleSave}
            >
              <PencilLine className="size-3.5" aria-hidden="true" />
              {localize('com_analitrics_save')}
            </button>
          </div>
          {saved.length > 0 && (
            <div className="mt-3">
              <FeedbackHistory items={saved} localize={localize} />
            </div>
          )}
        </div>
      )}
    </article>
  );
}

export default function AnalitricsContextPanel({
  conversationId,
  onCollapsePanel,
}: AnalitricsContextPanelProps) {
  const localize = useLocalize();
  const navigate = useNavigate();
  const hasConversation = Boolean(conversationId && conversationId !== Constants.NEW_CONVO);
  const { data, error, isFetching, refetch } = useAnalitricsContext(conversationId);
  const dashboardsQuery = useAnalitricsDashboards();
  const createDashboard = useCreateAnalitricsDashboard();
  const files = data?.files ?? [];
  const tables = (data?.tables ?? []).filter((table) => !table.systemTable);
  const profiles = (data?.profiles ?? []).filter((profile) => !profile.system_table);
  const datasets = buildDatasetInsights(tables, profiles, localize);
  const feedbackSources = buildFeedbackSources(files, localize);
  const [selectedFileId, setSelectedFileId] = useState('');
  const [activeView, setActiveView] = useState<PanelView>('general');
  const [activeFeedbackStep, setActiveFeedbackStep] = useState(0);
  const effectiveSelectedFileId = selectedFileId || feedbackSources[0]?.fileId || '';
  const selectedSource = feedbackSources.find((source) => source.fileId === effectiveSelectedFileId);
  const selectedDataset =
    datasets.find(
      (dataset) =>
        dataset.fileId === effectiveSelectedFileId ||
        (selectedSource?.filename != null && dataset.filename === selectedSource.filename),
    ) || datasets[0];
  const feedback = data?.feedback ?? [];
  const sourceFeedback = feedback.filter((item) => feedbackBelongsToSource(item, selectedSource));
  const suggestedFeedback = data?.suggestedFeedback;
  const sourceSuggestedFeedback = suggestedFeedbackBelongsToSource(suggestedFeedback, selectedSource)
    ? suggestedFeedback
    : null;
  const hasProfile = Boolean(data?.found && datasets.length > 0);
  const hasPendingClarification = Boolean(data?.pendingClarification);
  const hasCompletedAnalysis = (data?.recentAnalysisStates ?? []).some(isDashboardReadyState);
  const canCreateDashboard = hasProfile && !hasPendingClarification && hasCompletedAnalysis;
  const dashboardReadinessMessage = hasPendingClarification
    ? localize('com_analitrics_dashboard_waiting_clarification')
    : !hasCompletedAnalysis
      ? localize('com_analitrics_dashboard_requires_analysis')
      : '';
  const metricCandidates = selectedDataset?.metricCandidates ?? [];
  const segmentCandidates = selectedDataset?.segmentCandidates ?? [];
  const dateCandidates = selectedDataset?.dateCandidates ?? [];
  const executiveKpis = buildExecutiveKpis(selectedDataset, localize);
  const executiveSummary = buildExecutiveSummary(selectedDataset, sourceFeedback, localize);
  const latestConcepts = latestFeedbackForSteps(sourceFeedback, [1])?.content || '';
  const latestDefinitions = latestFeedbackForSteps(sourceFeedback, [2, 4, 6])?.content || '';
  const linkedDashboard = useMemo(
    () =>
      (dashboardsQuery.data?.dashboards ?? []).find(
        (dashboard) => dashboard.conversationId === conversationId,
      ),
    [conversationId, dashboardsQuery.data?.dashboards],
  );
  const [createdDashboardId, setCreatedDashboardId] = useState('');
  useEffect(() => {
    setCreatedDashboardId('');
  }, [conversationId]);
  const effectiveDashboardId = linkedDashboard?.dashboardId || createdDashboardId;

  const handleCreateDashboard = () => {
    if (!conversationId || createDashboard.isLoading) {
      return;
    }
    createDashboard.mutate(
      { conversationId },
      {
        onSuccess: (payload) => {
          const dashboardId = payload.dashboard?.dashboardId;
          if (dashboardId) {
            setCreatedDashboardId(dashboardId);
            dashboardsQuery.refetch();
          }
        },
      },
    );
  };

  if (!hasConversation) {
    return null;
  }

  return (
    <aside className="flex h-full min-h-0 flex-col bg-surface-primary text-text-primary">
      <div className="flex items-start justify-between gap-3 border-b border-border-light px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold">
            {activeView === 'general'
              ? localize('com_analitrics_context_general')
              : localize('com_analitrics_context_catalog')}
          </h2>
          <p className="mt-0.5 text-xs text-text-secondary">
            {isFetching
              ? localize('com_analitrics_context_updating')
              : data?.updatedAt
                ? localize('com_analitrics_context_updated')
                : localize('com_analitrics_context_no_reading')}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {onCollapsePanel && (
            <TooltipAnchor
              side="left"
              description={localize('com_analitrics_close_side_panel')}
              render={
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  className="h-9 w-9 rounded-lg"
                  aria-label={localize('com_analitrics_close_side_panel')}
                  aria-expanded={true}
                  onClick={onCollapsePanel}
                >
                  <Sidebar aria-hidden="true" className="h-5 w-5 text-text-primary" />
                </Button>
              }
            />
          )}
          <TooltipAnchor
            side="left"
            description={localize('com_analitrics_context_refresh')}
            render={
              <Button
                type="button"
                size="icon"
                variant="ghost"
                className="h-9 w-9 rounded-lg"
                onClick={() => refetch()}
                aria-label={localize('com_analitrics_context_refresh')}
              >
                <RefreshCw className={cn('size-4', isFetching && 'animate-spin')} aria-hidden="true" />
              </Button>
            }
          />
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3">
        <ViewSwitch activeView={activeView} onChange={setActiveView} localize={localize} />

        {error != null && (
          <div className="flex gap-2 rounded-lg border border-status-error-border bg-surface-secondary p-3 text-sm text-text-primary">
            <AlertCircle className="mt-0.5 size-4 shrink-0 text-status-error" aria-hidden="true" />
            <span>{localize('com_analitrics_context_load_error')}</span>
          </div>
        )}

        {!hasConversation && (
          <div className="rounded-lg border border-border-light bg-surface-secondary p-3 text-sm text-text-secondary">
            {localize('com_analitrics_context_waiting')}
          </div>
        )}

        {hasConversation && !hasProfile && error == null && (
          <div className="rounded-lg border border-border-light bg-surface-secondary p-3 text-sm text-text-secondary">
            {localize('com_analitrics_context_no_active_reading')}
          </div>
        )}

        {activeView === 'general' ? (
          <>
            <ExecutiveFileSelector
              sources={feedbackSources}
              selectedFileId={effectiveSelectedFileId}
              onChange={setSelectedFileId}
              localize={localize}
            />

            <InsightSection icon={FileSpreadsheet} title={localize('com_analitrics_executive_reading')}>
              <p className="text-xs leading-relaxed">{executiveSummary}</p>
            </InsightSection>

            <button
              type="button"
              className={cn(
                'inline-flex w-full items-center justify-center gap-2 rounded-lg px-3 py-2.5 text-sm font-semibold shadow-sm transition-colors disabled:cursor-not-allowed disabled:opacity-50',
                effectiveDashboardId
                  ? 'border border-border-medium bg-surface-secondary text-text-primary hover:bg-surface-hover'
                  : 'border border-transparent bg-text-primary text-surface-primary hover:bg-text-primary/90',
              )}
              disabled={!effectiveDashboardId && (!canCreateDashboard || createDashboard.isLoading)}
              onClick={() => {
                if (effectiveDashboardId) {
                  navigate(`/dashboards/${effectiveDashboardId}`);
                  return;
                }
                handleCreateDashboard();
              }}
            >
              <LayoutDashboard className="size-4" aria-hidden="true" />
              {createDashboard.isLoading
                ? localize('com_analitrics_creating_dashboard')
                : effectiveDashboardId
                  ? localize('com_analitrics_open_dashboard')
                  : localize('com_analitrics_create_dashboard')}
            </button>
            {!effectiveDashboardId && dashboardReadinessMessage && (
              <p className="text-xs leading-relaxed text-text-secondary">{dashboardReadinessMessage}</p>
            )}
            {effectiveDashboardId && (
              <div className="rounded-lg border border-border-light bg-surface-secondary p-3 text-xs text-text-secondary">
                <div className="flex items-center gap-2 text-text-primary">
                  <CheckCircle2 className="size-4 text-green-500" aria-hidden="true" />
                  <span className="font-medium">{localize('com_analitrics_dashboard_created')}</span>
                </div>
                <p className="mt-1">{localize('com_analitrics_dashboard_created_detail')}</p>
              </div>
            )}
            {createDashboard.isError && (
              <p className="text-xs text-status-error">
                {localize('com_analitrics_dashboard_create_error')}
              </p>
            )}

            <div className="grid grid-cols-2 gap-2">
              {executiveKpis.map((kpi) => (
                <KpiCard key={kpi.key} kpi={kpi} localize={localize} />
              ))}
            </div>

            <InsightSection icon={Sigma} title={localize('com_analitrics_suggested_metrics')}>
              <ChipList
                items={metricCandidates}
                empty={localize('com_analitrics_no_suggested_metrics')}
              />
            </InsightSection>

            <InsightSection icon={Tags} title={localize('com_analitrics_analysis_dimensions')}>
              <ChipList items={segmentCandidates} empty={localize('com_analitrics_no_analysis_dimensions')} />
            </InsightSection>

            <InsightSection icon={CalendarDays} title={localize('com_analitrics_temporal_reading')}>
              <ChipList items={dateCandidates} empty={localize('com_analitrics_no_temporal_fields')} />
            </InsightSection>

            {data?.cacheHits != null && data.cacheHits > 0 && (
              <div className="rounded-lg border border-border-light bg-surface-secondary p-3 text-xs text-text-secondary">
                {localize('com_analitrics_cache_reused', { count: formatNumber(data.cacheHits) })}
              </div>
            )}
          </>
        ) : (
          <>
            <SourceSelector
              sources={feedbackSources}
              selectedFileId={effectiveSelectedFileId}
              onChange={setSelectedFileId}
              localize={localize}
            />

            {sourceSuggestedFeedback?.content && (
              <InsightSection icon={AlertCircle} title={localize('com_analitrics_suggested_correction')}>
                <div className="space-y-3">
                  <p className="text-xs leading-relaxed text-text-secondary">
                    {localize('com_analitrics_suggested_correction_detail')}
                  </p>
                  <p className="rounded-lg border border-border-light bg-surface-primary-alt p-3 text-xs text-text-primary">
                    {sourceSuggestedFeedback.content}
                  </p>
                  <button
                    type="button"
                    className="inline-flex items-center gap-1.5 rounded-lg border border-border-light px-2.5 py-1.5 text-xs font-medium text-text-primary transition-colors hover:bg-surface-hover"
                    onClick={() => setActiveFeedbackStep(Number(sourceSuggestedFeedback.step || 5))}
                  >
                    <PencilLine className="size-3.5" aria-hidden="true" />
                    {localize('com_analitrics_review_and_save')}
                  </button>
                </div>
              </InsightSection>
            )}

            <InsightSection icon={PencilLine} title={localize('com_analitrics_enriched_catalog')}>
              <div className="space-y-3">
                <div>
                  <p className="text-xs font-medium text-text-primary">{localize('com_analitrics_business_concepts')}</p>
                  <p className="mt-1 line-clamp-3 text-xs">
                    {compactText(latestConcepts, localize('com_analitrics_no_definition'))}
                  </p>
                </div>
                <div>
                  <p className="text-xs font-medium text-text-primary">
                    {localize('com_analitrics_active_definitions_rules')}
                  </p>
                  <p className="mt-1 line-clamp-3 text-xs">
                    {compactText(latestDefinitions, localize('com_analitrics_no_definition'))}
                  </p>
                </div>
                <div className="flex items-center gap-2 text-xs">
                  <CheckCircle2
                    className={cn(
                      'size-4',
                      sourceFeedback.length > 0 ? 'text-green-500' : 'text-text-tertiary',
                    )}
                    aria-hidden="true"
                  />
                  <span>
                    {localize('com_analitrics_saved_contributions_for_file', {
                      count: formatNumber(sourceFeedback.length),
                    })}
                  </span>
                </div>
              </div>
            </InsightSection>

            <InsightSection icon={FileSpreadsheet} title={localize('com_analitrics_edit_catalog')}>
              <p className="mb-3 text-xs">
                {localize('com_analitrics_edit_catalog_order')}
              </p>
              <div className="space-y-3">
                {feedbackSteps.map((step) => (
                  <CatalogFeedbackCard
                    key={step.step}
                    step={step}
                    conversationId={conversationId}
                    saved={sourceFeedback.filter((item) => item.step === step.step)}
                    disabled={!hasConversation || !selectedSource}
                    source={selectedSource}
                    expanded={activeFeedbackStep === step.step}
                    onToggle={() => setActiveFeedbackStep((current) => (current === step.step ? 0 : step.step))}
                    suggestedContent={
                      sourceSuggestedFeedback?.step === step.step ? sourceSuggestedFeedback.content : undefined
                    }
                    localize={localize}
                  />
                ))}
              </div>
            </InsightSection>
          </>
        )}
      </div>
    </aside>
  );
}
