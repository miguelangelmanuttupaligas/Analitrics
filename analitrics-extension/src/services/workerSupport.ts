import { z } from 'zod';
import type {
  AnalyticsIntent,
  AnalyticsPlan,
  AnalyticsSourceSelection,
  AnalyticsValidation,
  CleanedQuestion,
  ContextSnapshot,
} from '../types.js';

const intentSchema = z.object({
  intent: z.enum([
    'resumen',
    'hallazgos',
    'calidad',
    'conteo',
    'columnas',
    'tabla',
    'grafico',
    'comparacion',
    'pregunta_gerencial',
    'ambigua',
    'otro',
  ]),
  outputMode: z.enum(['texto', 'tabla', 'grafico', 'aclaracion']),
  dataScope: z.enum(['archivo', 'corporativo', 'combinado', 'indefinido']),
  needsActiveFile: z.boolean(),
  shouldAskClarifyingQuestion: z.boolean(),
  clarificationQuestion: z.string(),
  chartType: z.enum(['barras', 'lineas', 'torta', 'tabla', 'ninguno']),
  orientation: z.enum(['horizontal', 'vertical', 'ninguna']),
  confidence: z.number().min(0).max(1),
  rationale: z.string(),
});

const planSchema = z.object({
  objective: z.string(),
  responseMode: z.enum(['texto', 'tabla', 'grafico', 'aclaracion']),
  dataSource: z.enum(['archivo', 'corporativo', 'combinado', 'ninguno']),
  ensureImport: z.boolean(),
  useContextSummary: z.boolean(),
  sql: z.string(),
  title: z.string(),
  chartType: z.enum(['barras', 'lineas', 'torta', 'tabla', 'ninguno']),
  labelColumn: z.string(),
  valueColumn: z.string(),
  orientation: z.enum(['horizontal', 'vertical', 'ninguna']),
  xField: z.string(),
  yField: z.string(),
  colorField: z.string(),
  topN: z.number().int().positive().max(50).nullable(),
  clarificationQuestion: z.string(),
  successCriteria: z.array(z.string()),
  riskNotes: z.array(z.string()),
});

const validationSchema = z.object({
  approved: z.boolean(),
  issues: z.array(z.string()),
  suggestedFixes: z.array(z.string()),
  shouldEscalateToClarification: z.boolean(),
  clarificationQuestion: z.string(),
});

const cleanedQuestionSchema = z.object({
  cleanedQuestion: z.string(),
  userGoal: z.string(),
  requestedOutput: z.enum(['texto', 'tabla', 'grafico', 'aclaracion']),
  businessTone: z.enum(['ejecutivo', 'analitico', 'operativo', 'neutro']),
  mentionedEntities: z.array(z.string()),
  ambiguityNotes: z.array(z.string()),
});

const contextSelectionSchema = z.object({
  selectedUploadIds: z.array(z.string()),
  rationale: z.string(),
});

const sqlSafetySchema = z.object({
  approved: z.boolean(),
  sanitizedSql: z.string(),
  rationale: z.string(),
  shouldClarify: z.boolean(),
  clarificationQuestion: z.string(),
});

const sourceSelectionSchema = z.object({
  mode: z.enum(['archivo', 'corporativo', 'combinado', 'ninguno']),
  rationale: z.string(),
  needsClarification: z.boolean(),
  clarificationQuestion: z.string(),
});

function coerceEnum<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  return typeof value === 'string' && (allowed as readonly string[]).includes(value) ? (value as T) : fallback;
}

export function compactJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

export function buildWorkerContextBrief(snapshot: ContextSnapshot): string {
  const selectedAssets = snapshot.selectedAssets.map((asset, index) => ({
    rank: index + 1,
    uploadId: asset.uploadId,
    filename: asset.filename,
    summary: asset.summary,
    businessSummary: asset.businessSummary,
    matchedBy: asset.matchedBy,
    tables: asset.tables.map((table) => ({
      sheetName: table.sheetName,
      tableName: `analitrics_uploads.${table.tableName}`,
      rowCount: table.rowCount,
      columnCount: table.columnCount,
      columns: table.columns.map((column) => column.columnName),
    })),
  }));

  const availableAssets = snapshot.availableAssets.map((asset, index) => ({
    rank: index + 1,
    uploadId: asset.uploadId,
    filename: asset.filename,
    summary: asset.summary,
    businessSummary: asset.businessSummary,
    tableCount: asset.tableCount,
    totalRows: asset.totalRows,
    totalColumns: asset.totalColumns,
    recencyRank: asset.recencyRank,
  }));

  const recentAttachments = snapshot.recentAttachments.map((attachment) => ({
    fileId: attachment.fileId,
    filename: attachment.filename,
    imported: attachment.imported,
    mimeType: attachment.mimeType,
  }));

  return compactJson({
    userId: snapshot.userId,
    conversationId: snapshot.conversationId,
    filenameHint: snapshot.filenameHint,
    activeFile: snapshot.activeFile,
    selectedAssets,
    availableAssets,
    recentAttachments,
    corporateTables: snapshot.corporateTables.map((table) => `${table.schema}.${table.table}`).slice(0, 25),
  });
}

export function buildPlanningGuidance(
  snapshot: ContextSnapshot,
  intent: AnalyticsIntent,
  sourceSelection?: AnalyticsSourceSelection | null,
): string {
  const activeTables = snapshot.selectedAssets.flatMap((asset) =>
    asset.tables.map(
      (table) =>
        `analitrics_uploads.${table.tableName}(${table.columns.map((column) => column.columnName).join(', ')})`,
    ),
  );

  return [
    `Activo tabular seleccionado: ${snapshot.selectedAssets.length > 0 ? 'sí' : 'no'}`,
    `Cantidad de activos seleccionados: ${snapshot.selectedAssets.length}`,
    `Tablas activas visibles: ${activeTables.length > 0 ? activeTables.join(' | ') : 'ninguna'}`,
    `Tablas corporativas visibles: ${snapshot.corporateTables.length}`,
    `Modo inferido por intención: ${intent.outputMode}`,
    `Ámbito inferido por intención: ${intent.dataScope}`,
    `Modo de fuente seleccionado: ${sourceSelection?.mode ?? 'pendiente'}`,
  ].join('\n');
}

function normalizeRequestedOutput(value: unknown): CleanedQuestion['requestedOutput'] {
  return coerceEnum(value, ['texto', 'tabla', 'grafico', 'aclaracion'] as const, 'texto');
}

function normalizeBusinessTone(value: unknown): CleanedQuestion['businessTone'] {
  const normalized = String(value ?? '').trim().toLowerCase();
  if (['ejecutivo', 'executive'].includes(normalized)) {
    return 'ejecutivo';
  }
  if (['analitico', 'analítico', 'analytic', 'analytical'].includes(normalized)) {
    return 'analitico';
  }
  if (['operativo', 'operational'].includes(normalized)) {
    return 'operativo';
  }
  return 'neutro';
}

function normalizeIntentName(value: unknown): AnalyticsIntent['intent'] {
  return coerceEnum(
    value,
    [
      'resumen',
      'hallazgos',
      'calidad',
      'conteo',
      'columnas',
      'tabla',
      'grafico',
      'comparacion',
      'pregunta_gerencial',
      'ambigua',
      'otro',
    ] as const,
    'otro',
  );
}

function normalizeIntentOutputMode(value: unknown): AnalyticsIntent['outputMode'] {
  return coerceEnum(value, ['texto', 'tabla', 'grafico', 'aclaracion'] as const, 'texto');
}

function normalizeDataScope(value: unknown): AnalyticsIntent['dataScope'] {
  return coerceEnum(value, ['archivo', 'corporativo', 'combinado', 'indefinido'] as const, 'indefinido');
}

function normalizeChartType(value: unknown): AnalyticsIntent['chartType'] {
  return coerceEnum(value, ['barras', 'lineas', 'torta', 'tabla', 'ninguno'] as const, 'ninguno');
}

function normalizeOrientation(value: unknown): AnalyticsIntent['orientation'] {
  return coerceEnum(value, ['horizontal', 'vertical', 'ninguna'] as const, 'ninguna');
}

function normalizeResponseMode(value: unknown): AnalyticsPlan['responseMode'] {
  return coerceEnum(value, ['texto', 'tabla', 'grafico', 'aclaracion'] as const, 'texto');
}

function normalizePlanDataSource(value: unknown): AnalyticsPlan['dataSource'] {
  return coerceEnum(value, ['archivo', 'corporativo', 'combinado', 'ninguno'] as const, 'ninguno');
}

export function parseCleanedQuestion(value: unknown, originalQuestion: string): CleanedQuestion {
  const candidate = (value ?? {}) as Record<string, unknown>;
  return cleanedQuestionSchema.parse({
    cleanedQuestion:
      typeof candidate.cleanedQuestion === 'string' && candidate.cleanedQuestion.trim()
        ? candidate.cleanedQuestion.trim()
        : originalQuestion.trim(),
    userGoal:
      typeof candidate.userGoal === 'string' && candidate.userGoal.trim()
        ? candidate.userGoal.trim()
        : originalQuestion.trim(),
    requestedOutput: normalizeRequestedOutput(candidate.requestedOutput),
    businessTone: normalizeBusinessTone(candidate.businessTone),
    mentionedEntities: Array.isArray(candidate.mentionedEntities)
      ? candidate.mentionedEntities.map((item) => String(item))
      : [],
    ambiguityNotes: Array.isArray(candidate.ambiguityNotes)
      ? candidate.ambiguityNotes.map((item) => String(item))
      : [],
  });
}

export function parseIntent(value: unknown, originalQuestion: string): AnalyticsIntent {
  const candidate = (value ?? {}) as Record<string, unknown>;
  return intentSchema.parse({
    intent: normalizeIntentName(candidate.intent),
    outputMode: normalizeIntentOutputMode(candidate.outputMode),
    dataScope: normalizeDataScope(candidate.dataScope),
    needsActiveFile: typeof candidate.needsActiveFile === 'boolean' ? candidate.needsActiveFile : false,
    shouldAskClarifyingQuestion:
      typeof candidate.shouldAskClarifyingQuestion === 'boolean' ? candidate.shouldAskClarifyingQuestion : false,
    clarificationQuestion:
      typeof candidate.clarificationQuestion === 'string' ? candidate.clarificationQuestion : '',
    chartType: normalizeChartType(candidate.chartType),
    orientation: normalizeOrientation(candidate.orientation),
    confidence:
      typeof candidate.confidence === 'number' && Number.isFinite(candidate.confidence)
        ? Math.max(0, Math.min(1, candidate.confidence))
        : 0.7,
    rationale: typeof candidate.rationale === 'string' ? candidate.rationale : '',
  });
}

export function parsePlan(
  value: unknown,
  question: string,
  snapshot: ContextSnapshot,
  intent: AnalyticsIntent,
  sourceSelection?: AnalyticsSourceSelection | null,
): AnalyticsPlan {
  const candidate = (value ?? {}) as Record<string, unknown>;
  const responseMode = normalizeResponseMode(candidate.responseMode);
  const inferredDataSource =
    sourceSelection?.mode && sourceSelection.mode !== 'ninguno'
      ? sourceSelection.mode
      : hasAnySelectedAsset(snapshot) && snapshot.corporateTables.length > 0
        ? 'combinado'
        : hasAnySelectedAsset(snapshot)
          ? 'archivo'
          : snapshot.corporateTables.length > 0
            ? 'corporativo'
            : 'ninguno';
  return planSchema.parse({
    objective:
      typeof candidate.objective === 'string' && candidate.objective.trim()
        ? candidate.objective.trim()
        : question.trim(),
    responseMode,
    dataSource:
      normalizePlanDataSource(candidate.dataSource) === 'ninguno'
        ? inferredDataSource
        : normalizePlanDataSource(candidate.dataSource),
    ensureImport:
      typeof candidate.ensureImport === 'boolean'
        ? candidate.ensureImport
        : !hasAnySelectedAsset(snapshot) && snapshot.latestAttachment.available,
    useContextSummary:
      typeof candidate.useContextSummary === 'boolean'
        ? candidate.useContextSummary
        : responseMode === 'texto',
    sql: typeof candidate.sql === 'string' ? candidate.sql : '',
    title: typeof candidate.title === 'string' ? candidate.title : 'Resultado analítico',
    chartType: normalizeChartType(candidate.chartType),
    labelColumn: typeof candidate.labelColumn === 'string' ? candidate.labelColumn : '',
    valueColumn: typeof candidate.valueColumn === 'string' ? candidate.valueColumn : '',
    orientation: normalizeOrientation(candidate.orientation),
    xField: typeof candidate.xField === 'string' ? candidate.xField : '',
    yField: typeof candidate.yField === 'string' ? candidate.yField : '',
    colorField: typeof candidate.colorField === 'string' ? candidate.colorField : '',
    topN:
      typeof candidate.topN === 'number' && Number.isFinite(candidate.topN)
        ? candidate.topN
        : responseMode === 'tabla'
          ? 10
          : null,
    clarificationQuestion:
      typeof candidate.clarificationQuestion === 'string' ? candidate.clarificationQuestion : '',
    successCriteria: Array.isArray(candidate.successCriteria)
      ? candidate.successCriteria.map((item) => String(item))
      : [],
    riskNotes: Array.isArray(candidate.riskNotes)
      ? candidate.riskNotes.map((item) => String(item))
      : [],
  });
}

export function parseValidation(value: unknown): AnalyticsValidation {
  const candidate = (value ?? {}) as Record<string, unknown>;
  return validationSchema.parse({
    approved: typeof candidate.approved === 'boolean' ? candidate.approved : true,
    issues: Array.isArray(candidate.issues) ? candidate.issues.map((item) => String(item)) : [],
    suggestedFixes: Array.isArray(candidate.suggestedFixes)
      ? candidate.suggestedFixes.map((item) => String(item))
      : [],
    shouldEscalateToClarification:
      typeof candidate.shouldEscalateToClarification === 'boolean'
        ? candidate.shouldEscalateToClarification
        : false,
    clarificationQuestion:
      typeof candidate.clarificationQuestion === 'string' ? candidate.clarificationQuestion : '',
  });
}

export function parseContextSelection(
  value: unknown,
  maxAssets: number,
): { selectedUploadIds: string[]; rationale: string } {
  const candidate = contextSelectionSchema.parse(value ?? {});
  return {
    selectedUploadIds: candidate.selectedUploadIds.slice(0, maxAssets),
    rationale: candidate.rationale,
  };
}

export function parseSqlSafety(value: unknown): {
  approved: boolean;
  sanitizedSql: string;
  rationale: string;
  shouldClarify: boolean;
  clarificationQuestion: string;
} {
  const candidate = sqlSafetySchema.parse(value ?? {});
  return {
    approved: candidate.approved,
    sanitizedSql: candidate.sanitizedSql,
    rationale: candidate.rationale,
    shouldClarify: candidate.shouldClarify,
    clarificationQuestion: candidate.clarificationQuestion,
  };
}

export function parseSourceSelection(value: unknown): AnalyticsSourceSelection {
  return sourceSelectionSchema.parse(value ?? {});
}

function hasAnySelectedAsset(snapshot: ContextSnapshot): boolean {
  return snapshot.selectedAssets.length > 0;
}
