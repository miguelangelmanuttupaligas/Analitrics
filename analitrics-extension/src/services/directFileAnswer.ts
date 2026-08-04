import { z } from 'zod';
import { parse } from 'pgsql-ast-parser';
import type { ContextSnapshot } from '../types.js';
import { buildChartResource } from './charts.js';
import {
  applyContextSelection,
  buildContextSnapshot,
  buildSelectedAssetsDescription,
  type OrchestrationOptions,
  type RequestContext,
} from './contextSnapshot.js';
import { buildNodeTrace } from './graphObservability.js';
import { runSelectQuery } from './ingestion.js';
import { callJsonWorker, callTextWorker } from './llm.js';
import {
  finishAgentRun,
  recordNodeTrace,
  startAgentRun,
  withObservabilityContext,
} from './observability.js';
import { composePrompt, loadPrompt } from './prompts.js';
import { compactJson } from './workerSupport.js';
import { runContextSelectionWorker } from './workers/contextWorkers.js';

type ResourceContent = {
  type: 'resource';
  resource: {
    uri: string;
    mimeType: string;
    text: string;
    name: string;
  };
};

type DirectFilePlan = {
  responseMode: 'texto' | 'tabla' | 'grafico' | 'aclaracion';
  sql: string;
  title: string;
  chartType: 'barras' | 'lineas' | 'torta' | 'tabla' | 'ninguno';
  labelColumn: string;
  valueColumn: string;
  orientation: 'horizontal' | 'vertical' | 'ninguna';
  xField: string;
  yField: string;
  colorField: string;
  topN: number | null;
  clarificationQuestion: string;
  rationale: string;
};

export type DirectFileAnswer = {
  handled: boolean;
  observabilityRunId?: string;
  answer?: string;
  resourceContent?: ResourceContent;
  snapshot?: ContextSnapshot;
  plan?: DirectFilePlan;
  execution?: {
    sqlRowCount?: number;
    sqlRows?: Record<string, unknown>[];
    chartSummary?: string;
  };
  reason?: string;
};

const directPlanSchema = z.object({
  responseMode: z.enum(['texto', 'tabla', 'grafico', 'aclaracion']),
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
  rationale: z.string(),
});

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function normalizeSqlIdentifier(value: string): string {
  return value.replace(/^"|"$/g, '').toLowerCase();
}

function normalizeQualifiedName(value: string): string {
  return value
    .replace(/^"|"$/g, '')
    .split('.')
    .map((part) => normalizeSqlIdentifier(part))
    .join('.');
}

function getActiveTableNames(snapshot: ContextSnapshot): Set<string> {
  return new Set(
    snapshot.selectedAssets.flatMap((asset) =>
      asset.tables.flatMap((table) => [
        table.tableName.toLowerCase(),
        `analitrics_uploads.${table.tableName}`.toLowerCase(),
      ]),
    ),
  );
}

function qualifyKnownDirectTables(sql: string, snapshot: ContextSnapshot): string {
  let qualifiedSql = sql;
  for (const asset of snapshot.selectedAssets) {
    for (const table of asset.tables) {
      const tableName = table.tableName;
      const pattern = new RegExp(`\\b(from|join)\\s+(?!analitrics_uploads\\.)(?:"?${escapeRegExp(tableName)}"?)\\b`, 'gi');
      qualifiedSql = qualifiedSql.replace(pattern, (_match, keyword: string) => `${keyword} analitrics_uploads.${tableName}`);
    }
  }
  return qualifiedSql;
}

function collectCteAliases(ast: unknown): Set<string> {
  const aliases = new Set<string>();

  function visit(value: unknown): void {
    if (!value || typeof value !== 'object') {
      return;
    }
    if (Array.isArray(value)) {
      value.forEach(visit);
      return;
    }

    const record = value as Record<string, unknown>;
    if (record.type === 'with' && Array.isArray(record.bind)) {
      for (const binding of record.bind) {
        if (!binding || typeof binding !== 'object') {
          continue;
        }
        const alias = (binding as { alias?: { name?: unknown } }).alias?.name;
        if (typeof alias === 'string') {
          aliases.add(normalizeSqlIdentifier(alias));
        }
      }
    }

    Object.values(record).forEach(visit);
  }

  visit(ast);
  return aliases;
}

function collectTableReferences(ast: unknown): string[] {
  const references: string[] = [];

  function visit(value: unknown): void {
    if (!value || typeof value !== 'object') {
      return;
    }
    if (Array.isArray(value)) {
      value.forEach(visit);
      return;
    }

    const record = value as Record<string, unknown>;
    if (record.type === 'table' && record.name && typeof record.name === 'object') {
      const name = record.name as { schema?: unknown; name?: unknown };
      if (typeof name.name === 'string') {
        const table = normalizeSqlIdentifier(name.name);
        const schema = typeof name.schema === 'string' ? normalizeSqlIdentifier(name.schema) : '';
        references.push(schema ? `${schema}.${table}` : table);
      }
    }

    Object.values(record).forEach(visit);
  }

  visit(ast);
  return references;
}

function assertDirectSqlUsesOnlySnapshotTables(sql: string, snapshot: ContextSnapshot): void {
  const allowedTables = getActiveTableNames(snapshot);
  let statements: unknown[];
  try {
    statements = parse(sql);
  } catch (error) {
    throw new Error(
      `No se pudo parsear el SQL directo para validarlo: ${error instanceof Error ? error.message : String(error)}`,
    );
  }

  const cteAliases = collectCteAliases(statements);
  for (const alias of cteAliases) {
    allowedTables.add(alias);
  }

  const references = collectTableReferences(statements).map(normalizeQualifiedName);

  if (!references.length) {
    return;
  }

  const invalidReferences = references.filter((reference) => !allowedTables.has(reference));
  if (invalidReferences.length > 0) {
    throw new Error(
      `El SQL directo intentó usar tablas fuera del archivo activo: ${invalidReferences.join(', ')}.`,
    );
  }
}

function sanitizeDirectSql(sql: string, snapshot: ContextSnapshot): string {
  const qualifiedSql = qualifyKnownDirectTables(sql, snapshot);
  assertDirectSqlUsesOnlySnapshotTables(qualifiedSql, snapshot);
  return qualifiedSql;
}

async function tracedDirectValue<T>(
  node: string,
  fn: () => Promise<T>,
  summarize: (value: T) => Record<string, unknown>,
): Promise<T> {
  const startedAtMs = Date.now();
  try {
    const value = await fn();
    await recordNodeTrace(
      buildNodeTrace({
        node,
        startedAtMs,
        status: 'ok',
        result: summarize(value),
      }),
    );
    return value;
  } catch (error) {
    await recordNodeTrace(
      buildNodeTrace({
        node,
        startedAtMs,
        status: 'error',
        error,
      }),
    );
    throw error;
  }
}

function parseDirectPlan(value: unknown, question: string): DirectFilePlan {
  const candidate = (value ?? {}) as Record<string, unknown>;
  return directPlanSchema.parse({
    responseMode: ['texto', 'tabla', 'grafico', 'aclaracion'].includes(String(candidate.responseMode))
      ? candidate.responseMode
      : 'texto',
    sql: typeof candidate.sql === 'string' ? candidate.sql : '',
    title:
      typeof candidate.title === 'string' && candidate.title.trim()
        ? candidate.title.trim()
        : question.trim(),
    chartType: ['barras', 'lineas', 'torta', 'tabla', 'ninguno'].includes(String(candidate.chartType))
      ? candidate.chartType
      : 'ninguno',
    labelColumn: typeof candidate.labelColumn === 'string' ? candidate.labelColumn : '',
    valueColumn: typeof candidate.valueColumn === 'string' ? candidate.valueColumn : '',
    orientation: ['horizontal', 'vertical', 'ninguna'].includes(String(candidate.orientation))
      ? candidate.orientation
      : 'ninguna',
    xField: typeof candidate.xField === 'string' ? candidate.xField : '',
    yField: typeof candidate.yField === 'string' ? candidate.yField : '',
    colorField: typeof candidate.colorField === 'string' ? candidate.colorField : '',
    topN:
      typeof candidate.topN === 'number' && Number.isFinite(candidate.topN) && candidate.topN > 0
        ? Math.min(Math.max(Math.trunc(candidate.topN), 1), 50)
        : null,
    clarificationQuestion:
      typeof candidate.clarificationQuestion === 'string' ? candidate.clarificationQuestion : '',
    rationale: typeof candidate.rationale === 'string' ? candidate.rationale : '',
  });
}

async function buildDirectPlan(question: string, snapshot: ContextSnapshot): Promise<DirectFilePlan> {
  return callJsonWorker({
    workerName: 'direct_file_plan',
    systemPrompt: composePrompt(
      loadPrompt('shared', 'analitrics_core.md'),
      loadPrompt('shared', 'data_contract.md'),
      loadPrompt('shared', 'json_contract.md'),
      loadPrompt('direct_file', 'plan.md'),
    ),
    userPrompt: [
      `Pregunta:\n${question}`,
      `Contexto del archivo:\n${buildSelectedAssetsDescription(snapshot)}`,
    ].join('\n\n'),
    parse: (value) => parseDirectPlan(value, question),
  });
}

async function repairDirectPlan(params: {
  question: string;
  snapshot: ContextSnapshot;
  previousPlan: DirectFilePlan;
  error: unknown;
}): Promise<DirectFilePlan> {
  return callJsonWorker({
    workerName: 'direct_file_repair_plan',
    systemPrompt: composePrompt(
      loadPrompt('shared', 'analitrics_core.md'),
      loadPrompt('shared', 'data_contract.md'),
      loadPrompt('shared', 'json_contract.md'),
      loadPrompt('direct_file', 'repair_plan.md'),
    ),
    userPrompt: [
      `Pregunta:\n${params.question}`,
      `Contexto del archivo:\n${buildSelectedAssetsDescription(params.snapshot)}`,
      `Plan previo:\n${compactJson(params.previousPlan)}`,
      `Error SQL:\n${params.error instanceof Error ? params.error.message : String(params.error)}`,
    ].join('\n\n'),
    parse: (value) => parseDirectPlan(value, params.question),
  });
}

async function buildDirectAnswer(params: {
  question: string;
  snapshot: ContextSnapshot;
  plan: DirectFilePlan;
  sqlRows: Record<string, unknown>[];
  sqlRowCount?: number;
  chartSummary?: string;
  hasResource: boolean;
}): Promise<string> {
  const { question, snapshot, plan, sqlRows, sqlRowCount, chartSummary, hasResource } = params;
  return callTextWorker({
    workerName: 'direct_file_answer',
    systemPrompt: composePrompt(
      loadPrompt('shared', 'analitrics_core.md'),
      loadPrompt('shared', 'answer_style.md'),
      loadPrompt('direct_file', 'answer.md'),
      hasResource
        ? [
            'Si hay tabla o grafico inline, inicia la respuesta con el marcador \\ui{tabla} o \\ui{grafico} segun corresponda.',
            'El recurso inline ya renderiza las filas SQL devueltas: no las dupliques como tabla markdown ni como listado fila por fila.',
            'Despues del marcador, entrega solo una sintesis breve o insight ejecutivo basado en el recurso.',
          ].join('\n')
        : 'No incluyas marcadores \\ui{...} si no hay recurso inline.',
    ),
    userPrompt: [
      `Pregunta:\n${question}`,
      `Contexto del archivo:\n${buildSelectedAssetsDescription(snapshot)}`,
      `Plan directo:\n${compactJson(plan)}`,
      `Filas SQL devueltas (${sqlRowCount ?? sqlRows.length}):\n${compactJson(sqlRows)}`,
      `Resumen visual/tabular:\n${chartSummary ?? 'ninguno'}`,
    ].join('\n\n'),
  });
}

export async function answerWithDirectFileContext(
  baseContext: RequestContext,
  question: string,
  options: OrchestrationOptions = {},
): Promise<DirectFileAnswer> {
  const contextStartedAtMs = Date.now();
  let snapshot = await buildContextSnapshot(baseContext, options);
  if (!snapshot.selectedAssets.length) {
    return {
      handled: false,
      snapshot,
      reason: 'No hay archivo tabular activo para modo directo.',
    };
  }

  const runId = await startAgentRun({
    flowMode: 'direct_file',
    userId: baseContext.userId,
    conversationId: options.conversationId ?? baseContext.conversationId,
    question,
    metadata: {
      filename: options.filename,
      selectedAssets: snapshot.selectedAssets.map((asset) => asset.filename),
    },
  });

  return withObservabilityContext({ runId, flowMode: 'direct_file' }, async () => {
    await recordNodeTrace(
      buildNodeTrace({
        node: 'direct_context_node',
        startedAtMs: contextStartedAtMs,
        status: 'ok',
        result: {
          activeFile: snapshot.activeFile.filename ?? '',
          selectedAssets: snapshot.selectedAssets.length,
        },
      }),
    );

    try {
      if (snapshot.selectedAssets.length > 1) {
        const contextSelection = await tracedDirectValue(
          'direct_context_selection_node',
          () => runContextSelectionWorker(question, snapshot),
          (value) => ({
            selectedUploadIds: value.selectedUploadIds,
            rationale: value.rationale,
          }),
        );
        if (contextSelection.selectedUploadIds.length > 0) {
          snapshot = applyContextSelection(snapshot, contextSelection);
        }
      }

      let plan = await tracedDirectValue('direct_plan_node', () => buildDirectPlan(question, snapshot), (value) => ({
        plan: value,
      }));
      if ((plan as DirectFilePlan).responseMode === 'aclaracion') {
        const answer =
          plan.clarificationQuestion ||
          'Necesito una precisión adicional para responder con el archivo cargado.';
        await finishAgentRun({
          runId,
          status: 'ok',
          resultSummary: answer,
          metadata: { responseMode: plan.responseMode },
        });
        return {
          handled: true,
          observabilityRunId: runId,
          snapshot,
          plan,
          execution: {},
          answer,
        };
      }

      let sqlRows: Record<string, unknown>[] = [];
      let sqlRowCount: number | undefined;
      let chartSummary: string | undefined;
      let resourceContent: ResourceContent | undefined;

      const execution = await tracedDirectValue(
        'direct_execute_node',
        async () => {
          if (plan.sql.trim()) {
            let result: Awaited<ReturnType<typeof runSelectQuery>>;
            try {
              const safeSql = sanitizeDirectSql(plan.sql, snapshot);
              result = await runSelectQuery(safeSql);
            } catch (error) {
              plan = await tracedDirectValue(
                'direct_repair_plan_node',
                () => repairDirectPlan({ question, snapshot, previousPlan: plan, error }),
                (value) => ({ plan: value }),
              );
              if (plan.responseMode === 'aclaracion' || !plan.sql.trim()) {
                return { sqlRowCount, sqlRows, chartSummary };
              }
              const safeSql = sanitizeDirectSql(plan.sql, snapshot);
              result = await runSelectQuery(safeSql);
            }
            sqlRows = result.rows;
            sqlRowCount = result.rowCount;

            if (result.rows.length > 0 && (plan.responseMode === 'tabla' || plan.responseMode === 'grafico')) {
              const chart = await buildChartResource({
                title: plan.title || 'Resultado analítico',
                chartType:
                  plan.responseMode === 'tabla'
                    ? 'tabla'
                    : plan.chartType === 'ninguno'
                      ? 'barras'
                      : plan.chartType,
                rows: result.rows,
                labelColumn: plan.labelColumn || undefined,
                valueColumn: plan.valueColumn || undefined,
                overrides: {
                  orientation: plan.orientation === 'ninguna' ? undefined : plan.orientation,
                  xField: plan.xField || undefined,
                  yField: plan.yField || undefined,
                  colorField: plan.colorField || undefined,
                  topN: plan.topN ?? undefined,
                  sort: plan.responseMode === 'tabla' ? 'none' : 'descending',
                },
              });
              chartSummary = chart.summary;
              resourceContent = chart.resource;
            }
          }
          return { sqlRowCount, sqlRows, chartSummary };
        },
        (value) => ({
          sqlRowCount: value.sqlRowCount ?? 0,
          sqlRows: value.sqlRows.length,
          chartSummary: value.chartSummary ?? '',
        }),
      );

      if (plan.responseMode === 'aclaracion') {
        const answer =
          plan.clarificationQuestion ||
          'Necesito una precisión adicional para responder con el archivo cargado.';
        await finishAgentRun({
          runId,
          status: 'ok',
          resultSummary: answer,
          metadata: {
            responseMode: plan.responseMode,
            selectedAssets: snapshot.selectedAssets.map((asset) => asset.filename),
            sql: plan.sql,
            sqlRowCount: execution.sqlRowCount,
            hasResource: false,
          },
        });
        return {
          handled: true,
          observabilityRunId: runId,
          snapshot,
          plan,
          execution,
          answer,
        };
      }

      const answer = await tracedDirectValue(
        'direct_answer_node',
        () =>
          buildDirectAnswer({
            question,
            snapshot,
            plan,
            sqlRows,
            sqlRowCount,
            chartSummary,
            hasResource: resourceContent != null,
          }),
        (value) => ({ answer: value }),
      );

      await finishAgentRun({
        runId,
        status: 'ok',
        resultSummary: answer,
        metadata: {
          responseMode: plan.responseMode,
          selectedAssets: snapshot.selectedAssets.map((asset) => asset.filename),
          sql: plan.sql,
          sqlRowCount: execution.sqlRowCount,
          hasResource: resourceContent != null,
        },
      });

      return {
        handled: true,
        observabilityRunId: runId,
        answer,
        resourceContent,
        snapshot,
        plan,
        execution,
      };
    } catch (error) {
      await finishAgentRun({
        runId,
        status: 'error',
        error,
      });
      throw error;
    }
  });
}
