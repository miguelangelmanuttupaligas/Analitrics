import { z } from 'zod';
import type { ContextSnapshot } from '../types.js';
import { buildChartResource } from './charts.js';
import {
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
import { compactJson } from './workerSupport.js';

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
      typeof candidate.topN === 'number' && Number.isFinite(candidate.topN)
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
    systemPrompt: [
      'Eres Analitrics en modo directo de archivo.',
      'Tu trabajo es decidir cómo responder una pregunta sobre un Excel/CSV ya importado a PostgreSQL.',
      'No respondas al usuario todavía: devuelve solo un plan JSON.',
      'Si la pregunta requiere cálculo, ranking, filtro, agregación, tabla o gráfico, genera SQL PostgreSQL SELECT usando solo las tablas y columnas explícitas del contexto.',
      'Usa nombres de tabla completamente calificados como analitrics_uploads.nombre_tabla.',
      'Si la pregunta es descriptiva y basta con metadata/resumen del archivo, deja sql vacío y usa responseMode=texto.',
      'Si el usuario pide gráfico, usa responseMode=grafico.',
      'Si el usuario pide tabla o ranking, usa responseMode=tabla.',
      'Si falta información indispensable, usa responseMode=aclaracion con una pregunta corta.',
      'No inventes tablas, columnas ni datos.',
      'Devuelve JSON con responseMode, sql, title, chartType, labelColumn, valueColumn, orientation, xField, yField, colorField, topN, clarificationQuestion y rationale.',
    ].join('\n'),
    userPrompt: [
      `Pregunta:\n${question}`,
      `Contexto del archivo:\n${buildSelectedAssetsDescription(snapshot)}`,
    ].join('\n\n'),
    parse: (value) => parseDirectPlan(value, question),
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
    systemPrompt: [
      'Eres Analitrics, un asistente de analítica de negocio.',
      'Responde en español con tono claro y ejecutivo.',
      'Usa solo el contexto del archivo y los resultados SQL entregados.',
      'No menciones MCP, workers, SQL interno ni detalles de implementación.',
      hasResource
        ? 'Si hay tabla o gráfico inline, inicia la respuesta con el marcador \\ui{tabla} o \\ui{grafico} según corresponda.'
        : 'No incluyas marcadores \\ui{...} si no hay recurso inline.',
      'Si el resultado contiene valores nulos o marcadores como \\N, explícalos como datos sin informar cuando sea relevante.',
    ].join('\n'),
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
  const snapshot = await buildContextSnapshot(baseContext, options);
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
      const plan = await tracedDirectValue('direct_plan_node', () => buildDirectPlan(question, snapshot), (value) => ({
        plan: value,
      }));
      if (plan.responseMode === 'aclaracion') {
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
            const result = await runSelectQuery(plan.sql);
            sqlRows = result.rows;
            sqlRowCount = result.rowCount;

            if (plan.responseMode === 'tabla' || plan.responseMode === 'grafico') {
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
