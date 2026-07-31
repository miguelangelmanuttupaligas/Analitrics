import { closeConnections, initPostgres, pg } from './db.js';
import { answerWithDirectFileContext } from './services/directFileAnswer.js';
import { orchestrateAnalyticsRequest } from './services/orchestrator.js';

type EvalFlow = 'direct_file' | 'graph';

type EvalCase = {
  id: string;
  question: string;
  expectedModes: Array<'texto' | 'tabla' | 'grafico' | 'aclaracion'>;
  expectsSql: boolean;
  expectsResource: boolean;
  expectsFileContext: boolean;
};

type EvalResult = {
  caseId: string;
  flow: EvalFlow;
  ok: boolean;
  elapsedMs: number;
  checks: Record<string, boolean>;
  answerPreview: string;
  sql?: string;
  runId?: string;
  error?: string;
};

const evalCases: EvalCase[] = [
  {
    id: 'file_summary',
    question: 'Resume qué contiene este archivo y cuál parece ser su propósito de negocio',
    expectedModes: ['texto'],
    expectsSql: false,
    expectsResource: false,
    expectsFileContext: true,
  },
  {
    id: 'top_country_courses',
    question: 'Dime el top 5 de países que venden más cursos',
    expectedModes: ['tabla'],
    expectsSql: true,
    expectsResource: true,
    expectsFileContext: true,
  },
  {
    id: 'amount_by_country',
    question: 'Dame el monto total por país y ordénalo de mayor a menor',
    expectedModes: ['tabla'],
    expectsSql: true,
    expectsResource: true,
    expectsFileContext: true,
  },
  {
    id: 'top_products_chart',
    question: 'Grafica los 10 cursos con mayor monto',
    expectedModes: ['grafico'],
    expectsSql: true,
    expectsResource: true,
    expectsFileContext: true,
  },
  {
    id: 'country_quality',
    question: '¿Qué inconsistencias ves en la columna país?',
    expectedModes: ['texto', 'tabla'],
    expectsSql: true,
    expectsResource: false,
    expectsFileContext: true,
  },
  {
    id: 'executive_findings',
    question: 'Dame 5 hallazgos ejecutivos del archivo',
    expectedModes: ['texto', 'tabla'],
    expectsSql: false,
    expectsResource: false,
    expectsFileContext: true,
  },
  {
    id: 'corporate_enrichment',
    question: '¿Qué datos corporativos serían más útiles para enriquecer este análisis?',
    expectedModes: ['texto'],
    expectsSql: false,
    expectsResource: false,
    expectsFileContext: true,
  },
];

function parseFlows(): EvalFlow[] {
  const requested = (process.env.EVAL_FLOW ?? 'direct_file').trim().toLowerCase();
  if (requested === 'both') {
    return ['direct_file', 'graph'];
  }
  if (requested === 'graph') {
    return ['graph'];
  }
  return ['direct_file'];
}

function selectEvalCases(): EvalCase[] {
  const requested = process.env.EVAL_CASES;
  if (!requested?.trim()) {
    return evalCases;
  }
  const selectedIds = new Set(
    requested
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean),
  );
  return evalCases.filter((testCase) => selectedIds.has(testCase.id));
}

function preview(value: string, maxLength = 220): string {
  const compact = value.replace(/\s+/g, ' ').trim();
  return compact.length > maxLength ? `${compact.slice(0, maxLength - 1)}…` : compact;
}

function asksForReload(answer: string): boolean {
  return /(carg(a|ue|ues|ar)|proporcion(a|e|es|ar)).{0,40}archivo/i.test(answer);
}

async function resolveEvalContext(): Promise<{ userId: string; conversationId: string; filename?: string }> {
  const userId = process.env.EVAL_USER_ID;
  const conversationId = process.env.EVAL_CONVERSATION_ID;
  if (userId && conversationId) {
    return {
      userId,
      conversationId,
      filename: process.env.EVAL_FILENAME,
    };
  }

  const latest = await pg.query<{
    user_id: string;
    conversation_id: string;
    filename: string | null;
  }>(
    `
      select user_id, conversation_id, filename
      from analitrics_meta.conversation_file_contexts
      where is_active = true
      order by updated_at desc, created_at desc
      limit 1
    `,
  );

  const row = latest.rows[0];
  if (!row) {
    throw new Error(
      'No hay contexto de archivo activo. Carga un Excel/CSV o define EVAL_USER_ID y EVAL_CONVERSATION_ID.',
    );
  }

  return {
    userId: row.user_id,
    conversationId: row.conversation_id,
    filename: row.filename ?? undefined,
  };
}

async function runCase(flow: EvalFlow, testCase: EvalCase, context: { userId: string; conversationId: string; filename?: string }): Promise<EvalResult> {
  const startedAtMs = Date.now();
  try {
    if (flow === 'direct_file') {
      const result = await answerWithDirectFileContext(
        { userId: context.userId, conversationId: context.conversationId },
        testCase.question,
        { conversationId: context.conversationId, filename: context.filename },
      );
      const answer = result.answer ?? '';
      const checks = {
        handled: result.handled,
        mode: result.plan ? testCase.expectedModes.includes(result.plan.responseMode) : false,
        sql: testCase.expectsSql ? Boolean(result.plan?.sql.trim()) : true,
        resource: testCase.expectsResource ? result.resourceContent != null : true,
        fileContext: testCase.expectsFileContext ? Boolean(result.snapshot?.activeFile.available) : true,
        noReloadRequest: !asksForReload(answer),
        spanishAnswer: /[áéíóúñ]|\b(el|la|los|las|archivo|datos|ventas|país)\b/i.test(answer),
      };

      return {
        caseId: testCase.id,
        flow,
        ok: Object.values(checks).every(Boolean),
        elapsedMs: Date.now() - startedAtMs,
        checks,
        answerPreview: preview(answer),
        sql: result.plan?.sql,
        runId: result.observabilityRunId,
      };
    }

    const result = await orchestrateAnalyticsRequest(
      { userId: context.userId, conversationId: context.conversationId },
      testCase.question,
      { conversationId: context.conversationId, filename: context.filename },
    );
    const checks = {
      mode: testCase.expectedModes.includes(result.plan.responseMode),
      sql: testCase.expectsSql ? Boolean(result.plan.sql.trim()) : true,
      resource: testCase.expectsResource ? result.resourceContent != null : true,
      fileContext: testCase.expectsFileContext ? result.context.activeFile.available : true,
      noReloadRequest: !asksForReload(result.answer),
      spanishAnswer: /[áéíóúñ]|\b(el|la|los|las|archivo|datos|ventas|país)\b/i.test(result.answer),
      validation: result.validation.approved || result.validation.shouldEscalateToClarification,
    };

    return {
      caseId: testCase.id,
      flow,
      ok: Object.values(checks).every(Boolean),
      elapsedMs: Date.now() - startedAtMs,
      checks,
      answerPreview: preview(result.answer),
      sql: result.plan.sql,
      runId: result.execution.observabilityRunId,
    };
  } catch (error) {
    return {
      caseId: testCase.id,
      flow,
      ok: false,
      elapsedMs: Date.now() - startedAtMs,
      checks: { error: false },
      answerPreview: '',
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

async function summarizeRecentRuns(): Promise<void> {
  const summary = await pg.query<{
    flow_mode: string;
    runs: string;
    avg_elapsed_ms: string | null;
    failed_runs: string;
  }>(
    `
      select
        flow_mode,
        count(*)::text as runs,
        round(avg(elapsed_ms))::text as avg_elapsed_ms,
        count(*) filter (where status <> 'ok')::text as failed_runs
      from analitrics_meta.agent_runs
      where started_at > now() - interval '30 minutes'
      group by flow_mode
      order by flow_mode
    `,
  );

  const workers = await pg.query<{
    worker_name: string;
    calls: string;
    avg_elapsed_ms: string | null;
    errors: string;
    avg_total_tokens: string | null;
  }>(
    `
      select
        worker_name,
        count(*)::text as calls,
        round(avg(elapsed_ms))::text as avg_elapsed_ms,
        count(*) filter (where status <> 'ok')::text as errors,
        round(avg(total_tokens))::text as avg_total_tokens
      from analitrics_meta.agent_llm_calls
      where created_at > now() - interval '30 minutes'
      group by worker_name
      order by errors desc, avg(elapsed_ms) desc nulls last
      limit 12
    `,
  );

  console.log('\nResumen de runs recientes');
  console.table(summary.rows);
  console.log('\nWorkers LLM recientes');
  console.table(workers.rows);
}

async function main(): Promise<void> {
  await initPostgres();
  const context = await resolveEvalContext();
  const flows = parseFlows();
  const selectedCases = selectEvalCases();
  if (!selectedCases.length) {
    throw new Error('EVAL_CASES no coincide con ningún caso disponible.');
  }

  console.log(
    `Evaluando Sprint 1 con user=${context.userId}, conversation=${context.conversationId}, filename=${context.filename ?? 'auto'}, flow=${flows.join('+')}`,
  );

  const results: EvalResult[] = [];
  for (const flow of flows) {
    for (const testCase of selectedCases) {
      console.log(`\n[${flow}] ${testCase.id}: ${testCase.question}`);
      const result = await runCase(flow, testCase, context);
      results.push(result);
      console.log(result.ok ? 'OK' : 'FAIL', `${result.elapsedMs}ms`, result.answerPreview || result.error);
      if (!result.ok) {
        console.log(JSON.stringify({ checks: result.checks, sql: result.sql, error: result.error }, null, 2));
      }
    }
  }

  const passed = results.filter((result) => result.ok).length;
  const failed = results.length - passed;
  console.log(`\nResultado Sprint 1: ${passed}/${results.length} correctas, ${failed} fallidas.`);
  console.table(
    results.map((result) => ({
      case: result.caseId,
      flow: result.flow,
      ok: result.ok,
      elapsedMs: result.elapsedMs,
      runId: result.runId ?? '',
    })),
  );
  await summarizeRecentRuns();

  if (failed > 0) {
    process.exitCode = 1;
  }
}

main()
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  })
  .finally(async () => {
    await closeConnections();
  });
