import { useEffect, useState, type ReactNode } from 'react';
import {
  AlertCircle,
  CalendarDays,
  CheckCircle2,
  FileSpreadsheet,
  PencilLine,
  RefreshCw,
  Sigma,
  Tags,
  X,
  type LucideIcon,
} from 'lucide-react';
import { Constants } from 'librechat-data-provider';
import type {
  AnalitricsColumn,
  AnalitricsFeedback,
  AnalitricsFile,
  AnalitricsProfile,
  AnalitricsTable,
} from '~/hooks';
import { useAnalitricsContext, useSaveAnalitricsCatalogFeedback } from '~/hooks';
import { cn } from '~/utils';

type AnalitricsContextPanelProps = {
  conversationId?: string | null;
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
  label: string;
  prompt: string;
  placeholder: string;
};

type PanelView = 'general' | 'catalog';

const feedbackSteps: CatalogFeedbackStep[] = [
  {
    step: 1,
    label: 'Nombrar conceptos',
    prompt: 'Define cómo se llaman estos conceptos en tu negocio.',
    placeholder: 'Ejemplo: producto significa curso vendido; monto significa ingreso cobrado.',
  },
  {
    step: 2,
    label: 'Confirmar indicadores',
    prompt: 'Indica qué métricas deben guiar el análisis.',
    placeholder: 'Ejemplo: ingresos, ticket promedio, ventas pagadas, cantidad de alumnos.',
  },
  {
    step: 3,
    label: 'Confirmar dimensiones',
    prompt: 'Aclara los cortes gerenciales que usas para comparar.',
    placeholder: 'Ejemplo: curso, canal, mes, país, asesor comercial, categoría.',
  },
  {
    step: 4,
    label: 'Agregar reglas de negocio',
    prompt: 'Describe filtros, exclusiones o fórmulas importantes.',
    placeholder: 'Ejemplo: excluir registros de prueba; usar fecha de pago; ingreso neto descuenta becas.',
  },
  {
    step: 5,
    label: 'Corregir interpretaciones',
    prompt: 'Corrige cualquier lectura incorrecta del agente.',
    placeholder: 'Ejemplo: precio no es ingreso; estado matriculado no significa pago confirmado.',
  },
  {
    step: 6,
    label: 'Aprobar definiciones',
    prompt: 'Marca qué definiciones ya pueden tratarse como confiables.',
    placeholder: 'Ejemplo: ingreso total = suma de pagos confirmados; curso es la dimensión principal.',
  },
];

const numberFormat = new Intl.NumberFormat('es-PE');

const formatNumber = (value?: number | null) =>
  numberFormat.format(Number.isFinite(value ?? NaN) ? Number(value) : 0);

const businessSourceName = (index: number) => `Ámbito analítico ${index + 1}`;

const fileDisplayName = (file: AnalitricsFile, index: number) =>
  file.filename || file.storageKey?.split('/').at(-1) || `Archivo ${index + 1}`;

const fileId = (file: AnalitricsFile, index: number) =>
  file.file_id || file.storageKey || file.filename || `file-${index}`;

const buildFeedbackSources = (files: AnalitricsFile[]): FeedbackSource[] =>
  files.map((file, index) => {
    const filename = fileDisplayName(file, index);
    return {
      fileId: fileId(file, index),
      filename,
      label: files.length === 1 ? filename : `${index + 1}. ${filename}`,
    };
  });

const normalizeColumn = (column: AnalitricsColumn): NormalizedColumn => {
  if (typeof column === 'string') {
    return { name: column, type: '' };
  }
  return {
    name: column?.name || 'Campo',
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

const compactText = (value: string, fallback = 'Sin definición guardada') =>
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
    return 'Pendiente';
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

const buildExecutiveKpis = (dataset: DatasetInsight | undefined): ExecutiveKpi[] => {
  const columns = dataset?.columns ?? [];
  const metricColumn = preferredMetricColumn(columns);
  const dimensionColumn = preferredDimensionColumn(columns);
  const dateCount = columns.filter((column) => isDateType(column.type)).length;

  return [
    {
      key: 'rows',
      label: 'Registros',
      value: formatNumber(dataset?.rowCount ?? 0),
      detail: 'Filas activas del archivo seleccionado.',
      confidence: dataset?.rowCount ? 'known' : 'pending',
    },
    {
      key: 'columns',
      label: 'Variables',
      value: formatNumber(dataset?.columnCount ?? 0),
      detail: 'Campos disponibles para análisis.',
      confidence: dataset?.columnCount ? 'known' : 'pending',
    },
    {
      key: 'main_metric',
      label: metricColumn?.sum != null ? `Total ${metricColumn.name}` : metricColumn?.name || 'Indicador principal',
      value: formatMetricValue(metricColumn?.sum ?? metricColumn?.average),
      detail:
        metricColumn?.sum != null
          ? `Suma detectada en ${metricColumn.name}`
          : metricColumn?.average != null
            ? `Promedio detectado en ${metricColumn.name}`
            : 'Confirma el indicador principal.',
      confidence: metricColumn?.sum != null || metricColumn?.average != null ? 'estimated' : 'pending',
    },
    {
      key: 'main_dimension',
      label: dimensionColumn?.name || 'Dimensión principal',
      value: dimensionColumn?.distinctCount != null ? formatNumber(dimensionColumn.distinctCount) : 'Pendiente',
      detail:
        dimensionColumn?.distinctCount != null
          ? `Valores únicos detectados en ${dimensionColumn.name}`
          : dateCount > 0
            ? `${dateCount} campo(s) temporal(es) detectados.`
            : 'Confirma el corte gerencial principal.',
      confidence: dimensionColumn?.distinctCount != null ? 'estimated' : 'pending',
    },
  ];
};

const buildExecutiveSummary = (dataset: DatasetInsight | undefined, feedback: AnalitricsFeedback[]) => {
  if (!dataset) {
    return 'Selecciona un archivo procesado para ver su lectura ejecutiva.';
  }
  const metric = preferredMetricColumn(dataset.columns);
  const dimension = preferredDimensionColumn(dataset.columns);
  const userDefinition = latestFeedbackForSteps(feedback, [1, 2, 3, 4, 6])?.content;
  const parts = [
    `${dataset.filename || dataset.name} contiene ${formatNumber(dataset.rowCount)} registros y ${formatNumber(dataset.columnCount)} variables.`,
    dataset.metricCandidates.length > 0
      ? `Se detectan indicadores como ${dataset.metricCandidates.slice(0, 3).join(', ')}.`
      : 'Aún falta confirmar los indicadores de negocio.',
    dimension ? `El corte gerencial más evidente es ${dimension.name}.` : undefined,
    metric ? `El indicador numérico más útil para iniciar es ${metric.name}.` : undefined,
    userDefinition ? `Definición aportada: ${userDefinition}` : undefined,
  ].filter(Boolean);

  return parts.slice(0, 4).join(' ');
};

const buildDatasetInsights = (
  tables: AnalitricsTable[],
  profiles: AnalitricsProfile[],
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
    const columns = group.flatMap((profile) => profile.columns ?? []).map(normalizeColumn);
    const numericColumns = columns.filter((column) => isNumericType(column.type));
    const explicitMetricCandidates = columns
      .filter((column) => isLikelyKpi(column.name, column.type))
      .map((column) => column.name);

    return {
      fileId: key,
      name: businessSourceName(index),
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

function KpiCard({ kpi }: { kpi: ExecutiveKpi }) {
  const statusLabel =
    kpi.confidence === 'known' ? 'Validado' : kpi.confidence === 'estimated' ? 'Estimado' : 'Pendiente';

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

function FeedbackHistory({ items }: { items: AnalitricsFeedback[] }) {
  if (items.length === 0) {
    return <p className="text-xs text-text-secondary">Sin aportes guardados todavía.</p>;
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
}: {
  sources: FeedbackSource[];
  selectedFileId: string;
  onChange: (fileId: string) => void;
}) {
  if (sources.length === 0) {
    return (
      <div className="rounded-lg border border-border-light bg-surface-secondary p-3 text-xs text-text-secondary">
        Adjunta y procesa un archivo para enriquecer su catálogo.
      </div>
    );
  }

  const selected = sources.find((source) => source.fileId === selectedFileId);

  return (
    <div className="rounded-lg border border-border-light bg-surface-secondary p-3">
      <label className="text-xs font-medium text-text-primary" htmlFor="analitrics-feedback-source">
        Archivo a enriquecer
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
        Los aportes se guardarán solo para {selected?.filename || 'el archivo seleccionado'}.
      </p>
    </div>
  );
}

function ExecutiveFileSelector({
  sources,
  selectedFileId,
  onChange,
}: {
  sources: FeedbackSource[];
  selectedFileId: string;
  onChange: (fileId: string) => void;
}) {
  if (sources.length === 0) {
    return null;
  }

  return (
    <div className="rounded-lg border border-border-light bg-surface-secondary p-3">
      <label className="text-xs font-medium text-text-primary" htmlFor="analitrics-executive-source">
        Archivo analizado
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
}: {
  activeView: PanelView;
  onChange: (view: PanelView) => void;
}) {
  const items: Array<{
    id: PanelView;
    title: string;
    icon: LucideIcon;
  }> = [
    {
      id: 'general',
      title: 'General',
      icon: FileSpreadsheet,
    },
    {
      id: 'catalog',
      title: 'Catálogo',
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
              <span className="text-sm font-semibold">{item.title}</span>
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

function CatalogFeedbackCard({
  step,
  conversationId,
  saved,
  disabled,
  source,
  expanded,
  onToggle,
  suggestedContent,
}: {
  step: CatalogFeedbackStep;
  conversationId?: string | null;
  saved: AnalitricsFeedback[];
  disabled: boolean;
  source?: FeedbackSource;
  expanded: boolean;
  onToggle: () => void;
  suggestedContent?: string;
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
        label: step.label,
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
          <h4 className="text-sm font-medium text-text-primary">{step.label}</h4>
          <p className="mt-1 text-xs text-text-secondary">{step.prompt}</p>
          {!expanded && (
            <div className="mt-2">
              <FeedbackHistory items={saved} />
            </div>
          )}
        </div>
        {saved.length > 0 && (
          <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-green-500" aria-label="Con aportes guardados" />
        )}
        <button
          type="button"
          className="rounded-md p-1.5 text-text-secondary transition-colors hover:bg-surface-hover hover:text-text-primary focus:outline-none focus:ring-2 focus:ring-border-heavy"
          onClick={onToggle}
          aria-label={expanded ? `Cerrar edición de ${step.label}` : `Editar ${step.label}`}
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
            placeholder={step.placeholder}
            disabled={disabled || saveFeedback.isLoading}
            onChange={(event) => setContent(event.target.value)}
          />
          <div className="mt-2 flex items-center justify-between gap-2">
            <span className="text-xs text-text-secondary">
              {saveFeedback.isError ? 'No se pudo guardar.' : saved.length > 0 ? `${saved.length} aporte(s)` : 'Opcional'}
            </span>
            <button
              type="button"
              className="inline-flex items-center gap-1.5 rounded-lg border border-border-light px-2.5 py-1.5 text-xs font-medium text-text-primary transition-colors hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-50"
              disabled={!canSave}
              onClick={handleSave}
            >
              <PencilLine className="size-3.5" aria-hidden="true" />
              Guardar
            </button>
          </div>
          {saved.length > 0 && (
            <div className="mt-3">
              <FeedbackHistory items={saved} />
            </div>
          )}
        </div>
      )}
    </article>
  );
}

export default function AnalitricsContextPanel({ conversationId }: AnalitricsContextPanelProps) {
  const hasConversation = Boolean(conversationId && conversationId !== Constants.NEW_CONVO);
  const { data, error, isFetching, refetch } = useAnalitricsContext(conversationId);
  const files = data?.files ?? [];
  const tables = (data?.tables ?? []).filter((table) => !table.systemTable);
  const profiles = (data?.profiles ?? []).filter((profile) => !profile.system_table);
  const datasets = buildDatasetInsights(tables, profiles);
  const feedbackSources = buildFeedbackSources(files);
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
  const metricCandidates = selectedDataset?.metricCandidates ?? [];
  const segmentCandidates = selectedDataset?.segmentCandidates ?? [];
  const dateCandidates = selectedDataset?.dateCandidates ?? [];
  const executiveKpis = buildExecutiveKpis(selectedDataset);
  const executiveSummary = buildExecutiveSummary(selectedDataset, sourceFeedback);
  const latestConcepts = latestFeedbackForSteps(sourceFeedback, [1])?.content || '';
  const latestDefinitions = latestFeedbackForSteps(sourceFeedback, [2, 4, 6])?.content || '';

  if (!hasConversation) {
    return null;
  }

  return (
    <aside className="flex h-full min-h-0 flex-col bg-surface-primary text-text-primary">
      <div className="flex items-start justify-between gap-3 border-b border-border-light px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold">
            {activeView === 'general' ? 'Resumen ejecutivo' : 'Catálogo'}
          </h2>
          <p className="mt-0.5 text-xs text-text-secondary">
            {isFetching ? 'Actualizando...' : data?.updatedAt ? 'Lectura actualizada' : 'Sin lectura'}
          </p>
        </div>
        <button
          type="button"
          className="rounded-lg p-2 text-text-secondary transition-colors hover:bg-surface-hover hover:text-text-primary focus:outline-none focus:ring-2 focus:ring-border-heavy"
          onClick={() => refetch()}
          aria-label="Actualizar resumen ejecutivo"
        >
          <RefreshCw className={cn('size-4', isFetching && 'animate-spin')} aria-hidden="true" />
        </button>
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3">
        <ViewSwitch activeView={activeView} onChange={setActiveView} />

        {error != null && (
          <div className="flex gap-2 rounded-lg border border-status-error-border bg-surface-secondary p-3 text-sm text-text-primary">
            <AlertCircle className="mt-0.5 size-4 shrink-0 text-status-error" aria-hidden="true" />
            <span>No se pudo cargar el resumen.</span>
          </div>
        )}

        {!hasConversation && (
          <div className="rounded-lg border border-border-light bg-surface-secondary p-3 text-sm text-text-secondary">
            El resumen aparecerá cuando exista una conversación con datos analíticos.
          </div>
        )}

        {hasConversation && !hasProfile && error == null && (
          <div className="rounded-lg border border-border-light bg-surface-secondary p-3 text-sm text-text-secondary">
            Aún no hay lectura gerencial activa.
          </div>
        )}

        {activeView === 'general' ? (
          <>
            <ExecutiveFileSelector
              sources={feedbackSources}
              selectedFileId={effectiveSelectedFileId}
              onChange={setSelectedFileId}
            />

            <InsightSection icon={FileSpreadsheet} title="Lectura ejecutiva">
              <p className="text-xs leading-relaxed">{executiveSummary}</p>
            </InsightSection>

            <div className="grid grid-cols-2 gap-2">
              {executiveKpis.map((kpi) => (
                <KpiCard key={kpi.key} kpi={kpi} />
              ))}
            </div>

            <InsightSection icon={Sigma} title="Indicadores sugeridos">
              <ChipList
                items={metricCandidates}
                empty="Aún no se detectaron indicadores numéricos relevantes."
              />
            </InsightSection>

            <InsightSection icon={Tags} title="Dimensiones de análisis">
              <ChipList items={segmentCandidates} empty="Aún no se detectaron cortes de negocio." />
            </InsightSection>

            <InsightSection icon={CalendarDays} title="Lectura temporal">
              <ChipList items={dateCandidates} empty="No se detectaron campos de fecha." />
            </InsightSection>

            {data?.cacheHits != null && data.cacheHits > 0 && (
              <div className="rounded-lg border border-border-light bg-surface-secondary p-3 text-xs text-text-secondary">
                Lectura reutilizada {formatNumber(data.cacheHits)} veces en este chat.
              </div>
            )}
          </>
        ) : (
          <>
            <SourceSelector
              sources={feedbackSources}
              selectedFileId={effectiveSelectedFileId}
              onChange={setSelectedFileId}
            />

            {sourceSuggestedFeedback?.content && (
              <InsightSection icon={AlertCircle} title="Corrección sugerida">
                <div className="space-y-3">
                  <p className="text-xs leading-relaxed text-text-secondary">
                    El agente detectó una corrección que puede mejorar futuras consultas.
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
                    Revisar y guardar
                  </button>
                </div>
              </InsightSection>
            )}

            <InsightSection icon={PencilLine} title="Catálogo enriquecido">
              <div className="space-y-3">
                <div>
                  <p className="text-xs font-medium text-text-primary">Conceptos de negocio</p>
                  <p className="mt-1 line-clamp-3 text-xs">{compactText(latestConcepts)}</p>
                </div>
                <div>
                  <p className="text-xs font-medium text-text-primary">Definiciones y reglas activas</p>
                  <p className="mt-1 line-clamp-3 text-xs">{compactText(latestDefinitions)}</p>
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
                    {formatNumber(sourceFeedback.length)} aporte(s) guardado(s) para este archivo.
                  </span>
                </div>
              </div>
            </InsightSection>

            <InsightSection icon={FileSpreadsheet} title="Editar catálogo">
              <p className="mb-3 text-xs">
                Orden sugerido: completa de arriba hacia abajo cuando tengas claridad. No es obligatorio
                llenar todo para continuar el análisis.
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
