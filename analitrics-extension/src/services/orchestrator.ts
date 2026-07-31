import { Annotation, END, START, StateGraph } from '@langchain/langgraph';
import type {
  AnalyticsExecution,
  AnalyticsIntent,
  AnalyticsPlan,
  AnalyticsSourceSelection,
  AnalyticsValidation,
  CleanedQuestion,
  ContextAssetSummary,
  ContextSnapshot,
  ContextTableProfile,
  GraphNodeTrace,
} from '../types.js';
import { buildChartResource } from './charts.js';
import {
  applyContextSelection,
  buildContextSnapshot,
  buildSelectedAssetsDescription,
  type OrchestrationOptions,
  type RequestContext,
} from './contextSnapshot.js';
import { buildNodeTrace, logNodeTrace } from './graphObservability.js';
import { importAttachmentIntoPostgres, runSelectQuery } from './ingestion.js';
import { findLatestTabularAttachment } from './librechatFiles.js';
import {
  finishAgentRun,
  recordNodeTrace,
  startAgentRun,
  withObservabilityContext,
} from './observability.js';
import { runContextSelectionWorker, runSourceSelectionWorker } from './workers/contextWorkers.js';
import { runPlanningWorker, runPlanReconciliationWorker, runRepairPlanningWorker, runSqlSafetyWorker } from './workers/planningWorkers.js';
import { runIntentWorker, runQuestionCleanupWorker } from './workers/questionWorkers.js';
import {
  runAnswerReconciliationWorker,
  runAnswerWorker,
  runResponseCleanupWorker,
  runValidationReconciliationWorker,
  runValidationWorker,
} from './workers/responseWorkers.js';

type ResourceContent = {
  type: 'resource';
  resource: {
    uri: string;
    mimeType: string;
    text: string;
    name: string;
  };
};

const OrchestrationState = Annotation.Root({
  question: Annotation<string>,
  baseContext: Annotation<RequestContext>,
  options: Annotation<OrchestrationOptions>,
  context: Annotation<ContextSnapshot | null>,
  cleanedQuestion: Annotation<CleanedQuestion | null>,
  intent: Annotation<AnalyticsIntent | null>,
  sourceSelection: Annotation<AnalyticsSourceSelection | null>,
  plan: Annotation<AnalyticsPlan | null>,
  execution: Annotation<AnalyticsExecution | null>,
  validation: Annotation<AnalyticsValidation | null>,
  answerDraft: Annotation<string>,
  answer: Annotation<string>,
  resourceContent: Annotation<ResourceContent | null>,
  repairAttempt: Annotation<number>,
  nodeTraces: Annotation<GraphNodeTrace[]>,
});

type OrchestrationGraphState = typeof OrchestrationState.State;

function buildClarificationValidation(question: string): AnalyticsValidation {
  return {
    approved: true,
    issues: [],
    suggestedFixes: [],
    shouldEscalateToClarification: true,
    clarificationQuestion: question,
  };
}

function getPrimarySelectedAsset(snapshot: ContextSnapshot): ContextAssetSummary | null {
  return snapshot.selectedAssets[0] ?? null;
}

function getPrimaryActiveTable(snapshot: ContextSnapshot): ContextTableProfile | null {
  return getPrimarySelectedAsset(snapshot)?.tables[0] ?? null;
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function qualifyKnownUploadTables(sql: string, snapshot?: ContextSnapshot | null): string {
  if (!snapshot?.selectedAssets.length || !sql.trim()) {
    return sql;
  }

  let normalizedSql = sql;
  const tableNames = Array.from(
    new Set(snapshot.selectedAssets.flatMap((asset) => asset.tables.map((table) => table.tableName))),
  );

  for (const tableName of tableNames) {
    const pattern = new RegExp(`(?<!\\.)\\b${escapeRegExp(tableName)}\\b`, 'g');
    normalizedSql = normalizedSql.replace(pattern, `analitrics_uploads.${tableName}`);
  }

  return normalizedSql;
}

async function executePlan(
  baseContext: RequestContext,
  plan: AnalyticsPlan,
  options: OrchestrationOptions,
  snapshot?: ContextSnapshot | null,
): Promise<{
  execution: AnalyticsExecution;
  resourceContent?: ResourceContent;
}> {
  const conversationId = options.conversationId ?? baseContext.conversationId;
  const execution: AnalyticsExecution = {};

  if (plan.ensureImport) {
    const attachment = await findLatestTabularAttachment({
      userId: baseContext.userId,
      conversationId,
      filename: options.filename,
    });
    if (!attachment) {
      throw new Error('El plan pidió importar un archivo, pero no se encontró un CSV/XLSX reciente.');
    }
    const imported = await importAttachmentIntoPostgres(attachment);
    execution.importedFile = imported.filename;
  }

  if (plan.useContextSummary) {
    execution.contextDescription = snapshot ? buildSelectedAssetsDescription(snapshot) : '';
  }

  if (!plan.sql.trim()) {
    return { execution };
  }

  const resolvedSql = qualifyKnownUploadTables(plan.sql, snapshot);
  const result = await runSelectQuery(resolvedSql);
  execution.sqlRowCount = result.rowCount;
  execution.sqlRows = result.rows;

  if (plan.responseMode !== 'tabla' && plan.responseMode !== 'grafico') {
    return { execution };
  }

  const chart = await buildChartResource({
    title: plan.title || 'Resultado analítico',
    chartType: plan.responseMode === 'tabla' ? 'tabla' : plan.chartType === 'ninguno' ? 'barras' : plan.chartType,
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

  execution.chartSummary = chart.summary;
  return {
    execution,
    resourceContent: chart.resource,
  };
}

async function tracedNode(
  state: OrchestrationGraphState,
  node: string,
  fn: () => Promise<Record<string, unknown>>,
): Promise<Record<string, unknown>> {
  const startedAtMs = Date.now();
  try {
    const result = await fn();
    const trace = buildNodeTrace({ node, startedAtMs, status: 'ok', result });
    logNodeTrace(trace);
    await recordNodeTrace(trace);
    return {
      ...result,
      nodeTraces: [...(state.nodeTraces ?? []), trace],
    };
  } catch (error) {
    const trace = buildNodeTrace({ node, startedAtMs, status: 'error', error });
    logNodeTrace(trace);
    await recordNodeTrace(trace);
    throw error;
  }
}

export async function orchestrateAnalyticsRequest(
  baseContext: RequestContext,
  question: string,
  options: OrchestrationOptions = {},
): Promise<{
  answer: string;
  cleanedQuestion: CleanedQuestion;
  context: ContextSnapshot;
  intent: AnalyticsIntent;
  sourceSelection: AnalyticsSourceSelection;
  plan: AnalyticsPlan;
  execution: AnalyticsExecution;
  validation: AnalyticsValidation;
  resourceContent?: ResourceContent;
}> {
  const graph = new StateGraph(OrchestrationState)
    .addNode('resolve_context_node', async (state: OrchestrationGraphState) =>
      tracedNode(state, 'resolve_context_node', async () => ({
        context: await buildContextSnapshot(state.baseContext, state.options),
      })),
    )
    .addNode('select_context_node', async (state: OrchestrationGraphState) =>
      tracedNode(state, 'select_context_node', async () => ({
        context: applyContextSelection(
          state.context!,
          await runContextSelectionWorker(state.question, state.context!),
        ),
      })),
    )
    .addNode('clean_intent_node', async (state: OrchestrationGraphState) =>
      tracedNode(state, 'clean_intent_node', async () => ({
        cleanedQuestion: await runQuestionCleanupWorker(state.question, state.context!),
      })),
    )
    .addNode('classify_intent_node', async (state: OrchestrationGraphState) =>
      tracedNode(state, 'classify_intent_node', async () => ({
        intent: await runIntentWorker(state.cleanedQuestion!.cleanedQuestion, state.context!),
      })),
    )
    .addNode('source_selection_node', async (state: OrchestrationGraphState) =>
      tracedNode(state, 'source_selection_node', async () => ({
        sourceSelection: await runSourceSelectionWorker({
          cleanedQuestion: state.cleanedQuestion!,
          snapshot: state.context!,
        }),
      })),
    )
    .addNode('plan_node', async (state: OrchestrationGraphState) =>
      tracedNode(state, 'plan_node', async () => ({
        plan: await runPlanningWorker(
          state.cleanedQuestion!,
          state.context!,
          state.intent!,
          state.sourceSelection!,
        ),
      })),
    )
    .addNode('reconcile_plan_node', async (state: OrchestrationGraphState) =>
      tracedNode(state, 'reconcile_plan_node', async () => ({
        plan: await runPlanReconciliationWorker({
          cleanedQuestion: state.cleanedQuestion!,
          snapshot: state.context!,
          intent: state.intent!,
          sourceSelection: state.sourceSelection!,
          proposedPlan: state.plan!,
        }),
      })),
    )
    .addNode('sql_safety_node', async (state: OrchestrationGraphState) =>
      tracedNode(state, 'sql_safety_node', async () => {
        const sqlSafety = await runSqlSafetyWorker({
          question: state.cleanedQuestion!.cleanedQuestion,
          snapshot: state.context!,
          plan: state.plan!,
        });

        if (sqlSafety.shouldClarify) {
          return {
            plan: {
              ...state.plan!,
              responseMode: 'aclaracion' as const,
              clarificationQuestion: sqlSafety.clarificationQuestion,
              sql: '',
            },
          };
        }

        if (!state.plan!.sql.trim()) {
          return { plan: state.plan! };
        }

        return {
          plan: {
            ...state.plan!,
            sql: sqlSafety.sanitizedSql || state.plan!.sql,
          },
        };
      }),
    )
    .addNode('clarify_node', async (state: OrchestrationGraphState) =>
      tracedNode(state, 'clarify_node', async () => {
        const clarificationQuestion =
          state.plan?.clarificationQuestion ||
          state.sourceSelection?.clarificationQuestion ||
          state.intent?.clarificationQuestion ||
          '¿Podrías precisar un poco más lo que quieres analizar?';
        return {
          answerDraft: clarificationQuestion,
          answer: clarificationQuestion,
          execution: state.execution ?? {},
          validation: buildClarificationValidation(clarificationQuestion),
        };
      }),
    )
    .addNode('execute_node', async (state: OrchestrationGraphState) =>
      tracedNode(state, 'execute_node', async () => {
        const executed = await executePlan(state.baseContext, state.plan!, state.options, state.context);
        return {
          execution: executed.execution,
          resourceContent: executed.resourceContent ?? null,
        };
      }),
    )
    .addNode('refresh_context_node', async (state: OrchestrationGraphState) =>
      tracedNode(state, 'refresh_context_node', async () => ({
        context: await buildContextSnapshot(state.baseContext, state.options),
      })),
    )
    .addNode('draft_answer_node', async (state: OrchestrationGraphState) =>
      tracedNode(state, 'draft_answer_node', async () => ({
        answerDraft: await runAnswerWorker({
          question: state.question,
          cleanedQuestion: state.cleanedQuestion!,
          snapshot: state.context!,
          intent: state.intent!,
          plan: state.plan!,
          execution: state.execution ?? {},
          validationIssues:
            state.validation && !state.validation.approved
              ? [...state.validation.issues, ...state.validation.suggestedFixes]
              : [],
        }),
      })),
    )
    .addNode('validate_node', async (state: OrchestrationGraphState) =>
      tracedNode(state, 'validate_node', async () => ({
        validation: await runValidationWorker({
          question: state.question,
          cleanedQuestion: state.cleanedQuestion!,
          snapshot: state.context!,
          intent: state.intent!,
          plan: state.plan!,
          execution: state.execution ?? {},
          draftedAnswer: state.answerDraft,
        }),
      })),
    )
    .addNode('reconcile_validation_node', async (state: OrchestrationGraphState) =>
      tracedNode(state, 'reconcile_validation_node', async () => ({
        validation: await runValidationReconciliationWorker({
          question: state.question,
          cleanedQuestion: state.cleanedQuestion!,
          snapshot: state.context!,
          intent: state.intent!,
          plan: state.plan!,
          execution: state.execution ?? {},
          validation: state.validation!,
          draftedAnswer: state.answerDraft,
        }),
      })),
    )
    .addNode('repair_plan_node', async (state: OrchestrationGraphState) =>
      tracedNode(state, 'repair_plan_node', async () => ({
        repairAttempt: state.repairAttempt + 1,
        plan: await runRepairPlanningWorker({
          question: state.cleanedQuestion!.cleanedQuestion,
          cleanedQuestion: state.cleanedQuestion!,
          snapshot: state.context!,
          intent: state.intent!,
          sourceSelection: state.sourceSelection!,
          previousPlan: state.plan!,
          execution: state.execution ?? {},
          validation: state.validation!,
        }),
        execution: {},
        resourceContent: null,
      })),
    )
    .addNode('cleanup_response_node', async (state: OrchestrationGraphState) =>
      tracedNode(state, 'cleanup_response_node', async () => {
        const finalDraft =
          state.validation?.shouldEscalateToClarification && state.validation.clarificationQuestion.trim()
            ? state.validation.clarificationQuestion.trim()
            : state.answerDraft;
        const reconciledDraft = await runAnswerReconciliationWorker({
          question: state.question,
          snapshot: state.context!,
          plan: state.plan!,
          execution: state.execution ?? {},
          answerDraft: finalDraft,
        });
        return {
          answer: await runResponseCleanupWorker({
            originalQuestion: state.question,
            cleanedQuestion: state.cleanedQuestion!,
            answerDraft: reconciledDraft,
            responseMode: state.plan!.responseMode,
            hasVisualResource: state.resourceContent != null,
          }),
        };
      }),
    )
    .addEdge(START, 'resolve_context_node')
    .addEdge('resolve_context_node', 'select_context_node')
    .addEdge('select_context_node', 'clean_intent_node')
    .addEdge('clean_intent_node', 'classify_intent_node')
    .addEdge('classify_intent_node', 'source_selection_node')
    .addEdge('source_selection_node', 'plan_node')
    .addEdge('plan_node', 'reconcile_plan_node')
    .addEdge('reconcile_plan_node', 'sql_safety_node')
    .addConditionalEdges('sql_safety_node', (state: OrchestrationGraphState) => {
      if (
        state.plan?.responseMode === 'aclaracion' ||
        state.sourceSelection?.needsClarification ||
        state.intent?.shouldAskClarifyingQuestion
      ) {
        return 'clarify_node';
      }
      return 'execute_node';
    })
    .addEdge('clarify_node', 'cleanup_response_node')
    .addEdge('execute_node', 'refresh_context_node')
    .addEdge('refresh_context_node', 'draft_answer_node')
    .addEdge('draft_answer_node', 'validate_node')
    .addEdge('validate_node', 'reconcile_validation_node')
    .addConditionalEdges('reconcile_validation_node', (state: OrchestrationGraphState) => {
      if (state.validation?.shouldEscalateToClarification) {
        return 'clarify_node';
      }
      if (!state.validation?.approved && state.repairAttempt < 1) {
        return 'repair_plan_node';
      }
      return 'cleanup_response_node';
    })
    .addEdge('repair_plan_node', 'execute_node')
    .addEdge('cleanup_response_node', END)
    .compile();

  const runId = await startAgentRun({
    flowMode: 'graph',
    userId: baseContext.userId,
    conversationId: options.conversationId ?? baseContext.conversationId,
    question,
    metadata: {
      filename: options.filename,
    },
  });

  try {
    const result = await withObservabilityContext({ runId, flowMode: 'graph' }, () =>
      graph.invoke({
        question,
        baseContext,
        options,
        context: null,
        cleanedQuestion: null,
        intent: null,
        sourceSelection: null,
        plan: null,
        execution: null,
        validation: null,
        answerDraft: '',
        answer: '',
        resourceContent: null,
        repairAttempt: 0,
        nodeTraces: [],
      }),
    );

    if (!result.context || !result.cleanedQuestion || !result.intent || !result.sourceSelection || !result.plan || !result.validation) {
      throw new Error('El grafo de Analitrics terminó sin producir un estado válido completo.');
    }

    const execution = {
      ...(result.execution ?? {}),
      observabilityRunId: runId,
      graphTrace: result.nodeTraces ?? [],
    };

    await finishAgentRun({
      runId,
      status: 'ok',
      resultSummary: result.answer,
      metadata: {
        responseMode: result.plan.responseMode,
        dataSource: result.plan.dataSource,
        sqlRowCount: result.execution?.sqlRowCount ?? null,
        hasResource: result.resourceContent != null,
      },
    });

    return {
      answer: result.answer,
      cleanedQuestion: result.cleanedQuestion,
      context: result.context,
      intent: result.intent,
      sourceSelection: result.sourceSelection,
      plan: result.plan,
      execution,
      validation: result.validation,
      resourceContent: result.resourceContent ?? undefined,
    };
  } catch (error) {
    await finishAgentRun({
      runId,
      status: 'error',
      error,
    });
    throw error;
  }
}
