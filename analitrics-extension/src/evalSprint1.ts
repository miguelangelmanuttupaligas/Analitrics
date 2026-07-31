import { closeConnections, initPostgres, pg } from './db.js';
import { answerWithDirectFileContext } from './services/directFileAnswer.js';
import { orchestrateAnalyticsRequest } from './services/orchestrator.js';
import { randomUUID } from 'node:crypto';

type EvalFlow = 'direct_file' | 'graph';

type EvalCase = {
  id: string;
  question: string;
  expectedModes: Array<'texto' | 'tabla' | 'grafico' | 'aclaracion'>;
  expectsSql: boolean;
  expectsResource: boolean;
  expectsFileContext: boolean;
  expectedMetric?: string;
  expectedDimension?: string;
  mustUseColumns?: string[];
  expectedAnswerTerms?: string[];
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
  estimatedCostUsd?: number;
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
    expectedAnswerTerms: ['registros', 'columnas', 'producto'],
  },
  {
    id: 'top_country_courses',
    question: 'Dime el top 5 de países que venden más cursos',
    expectedModes: ['tabla'],
    expectsSql: true,
    expectsResource: true,
    expectsFileContext: true,
    expectedMetric: 'monto',
    expectedDimension: 'pais',
    mustUseColumns: ['pais', 'monto'],
    expectedAnswerTerms: ['Perú'],
  },
  {
    id: 'amount_by_country',
    question: 'Dame el monto total por país y ordénalo de mayor a menor',
    expectedModes: ['tabla'],
    expectsSql: true,
    expectsResource: true,
    expectsFileContext: true,
    expectedMetric: 'monto',
    expectedDimension: 'pais',
    mustUseColumns: ['pais', 'monto'],
    expectedAnswerTerms: ['Perú'],
  },
  {
    id: 'top_products_chart',
    question: 'Grafica los 10 cursos con mayor monto',
    expectedModes: ['grafico'],
    expectsSql: true,
    expectsResource: true,
    expectsFileContext: true,
    expectedMetric: 'monto',
    expectedDimension: 'producto',
    mustUseColumns: ['producto', 'monto'],
  },
  {
    id: 'country_quality',
    question: '¿Qué inconsistencias ves en la columna país?',
    expectedModes: ['texto', 'tabla'],
    expectsSql: true,
    expectsResource: false,
    expectsFileContext: true,
    expectedDimension: 'pais',
    mustUseColumns: ['pais'],
    expectedAnswerTerms: ['país'],
  },
  {
    id: 'executive_findings',
    question: 'Dame 5 hallazgos ejecutivos del archivo',
    expectedModes: ['texto', 'tabla'],
    expectsSql: false,
    expectsResource: false,
    expectsFileContext: true,
    expectedAnswerTerms: ['hallazgo'],
  },
  {
    id: 'corporate_enrichment',
    question: '¿Qué datos corporativos serían más útiles para enriquecer este análisis?',
    expectedModes: ['texto'],
    expectsSql: false,
    expectsResource: false,
    expectsFileContext: true,
    expectedAnswerTerms: ['corporativo'],
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

function includesAllTerms(value: string | undefined, terms: string[] = []): boolean {
  const normalized = (value ?? '')
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .toLowerCase();
  return terms.every((term) =>
    normalized.includes(
      term
        .normalize('NFD')
        .replace(/\p{Diacritic}/gu, '')
        .toLowerCase(),
    ),
  );
}

async function getRunCost(runId: string | undefined): Promise<number | undefined> {
  if (!runId) {
    return undefined;
  }
  const result = await pg.query<{ estimated_cost_usd: string | null }>(
    `
      select estimated_cost_usd
      from analitrics_meta.agent_runs
      where run_id = $1
    `,
    [runId],
  );
  const raw = result.rows[0]?.estimated_cost_usd;
  return raw == null ? undefined : Number(raw);
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
        expectedMetric: testCase.expectedMetric
          ? includesAllTerms([result.plan?.sql, result.plan?.rationale, answer].filter(Boolean).join('\n'), [
              testCase.expectedMetric,
            ])
          : true,
        expectedDimension: testCase.expectedDimension
          ? includesAllTerms([result.plan?.sql, result.plan?.rationale, answer].filter(Boolean).join('\n'), [
              testCase.expectedDimension,
            ])
          : true,
        mustUseColumns: testCase.mustUseColumns?.length
          ? includesAllTerms(result.plan?.sql, testCase.mustUseColumns)
          : true,
        answerTerms: testCase.expectedAnswerTerms?.length
          ? includesAllTerms(answer, testCase.expectedAnswerTerms)
          : true,
      };
      const estimatedCostUsd = await getRunCost(result.observabilityRunId);

      return {
        caseId: testCase.id,
        flow,
        ok: Object.values(checks).every(Boolean),
        elapsedMs: Date.now() - startedAtMs,
        checks,
        answerPreview: preview(answer),
        sql: result.plan?.sql,
        runId: result.observabilityRunId,
        estimatedCostUsd,
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
      expectedMetric: testCase.expectedMetric
        ? includesAllTerms([result.plan.sql, result.plan.objective, result.answer].join('\n'), [
            testCase.expectedMetric,
          ])
        : true,
      expectedDimension: testCase.expectedDimension
        ? includesAllTerms([result.plan.sql, result.plan.objective, result.answer].join('\n'), [
            testCase.expectedDimension,
          ])
        : true,
      mustUseColumns: testCase.mustUseColumns?.length
        ? includesAllTerms(result.plan.sql, testCase.mustUseColumns)
        : true,
      answerTerms: testCase.expectedAnswerTerms?.length
        ? includesAllTerms(result.answer, testCase.expectedAnswerTerms)
        : true,
    };
    const estimatedCostUsd = await getRunCost(result.execution.observabilityRunId);

    return {
      caseId: testCase.id,
      flow,
      ok: Object.values(checks).every(Boolean),
      elapsedMs: Date.now() - startedAtMs,
      checks,
      answerPreview: preview(result.answer),
      sql: result.plan.sql,
      runId: result.execution.observabilityRunId,
      estimatedCostUsd,
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

async function startEvalRun(params: {
  suiteName: string;
  context: { userId: string; conversationId: string; filename?: string };
  flows: EvalFlow[];
}): Promise<string> {
  const evalRunId = randomUUID();
  await pg.query(
    `
      insert into analitrics_meta.eval_runs(
        eval_run_id, suite_name, user_id, conversation_id, filename, flows
      )
      values ($1, $2, $3, $4, $5, $6)
    `,
    [
      evalRunId,
      params.suiteName,
      params.context.userId,
      params.context.conversationId,
      params.context.filename ?? null,
      params.flows,
    ],
  );
  return evalRunId;
}

async function recordEvalCaseResult(
  evalRunId: string,
  testCase: EvalCase,
  result: EvalResult,
): Promise<void> {
  await pg.query(
    `
      insert into analitrics_meta.eval_case_results(
        eval_run_id, case_id, flow_mode, agent_run_id, status, elapsed_ms,
        expected_json, checks_json, answer_preview, sql, error, estimated_cost_usd
      )
      values ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, $9, $10, $11, $12)
    `,
    [
      evalRunId,
      result.caseId,
      result.flow,
      result.runId ?? null,
      result.ok ? 'ok' : 'failed',
      result.elapsedMs,
      JSON.stringify({
        expectedModes: testCase.expectedModes,
        expectsSql: testCase.expectsSql,
        expectsResource: testCase.expectsResource,
        expectsFileContext: testCase.expectsFileContext,
        expectedMetric: testCase.expectedMetric,
        expectedDimension: testCase.expectedDimension,
        mustUseColumns: testCase.mustUseColumns,
        expectedAnswerTerms: testCase.expectedAnswerTerms,
      }),
      JSON.stringify(result.checks),
      result.answerPreview,
      result.sql ?? null,
      result.error ?? null,
      result.estimatedCostUsd ?? null,
    ],
  );
}

async function finishEvalRun(evalRunId: string, results: EvalResult[]): Promise<void> {
  const passed = results.filter((result) => result.ok).length;
  const failed = results.length - passed;
  const totalCost = results.reduce((sum, result) => sum + (result.estimatedCostUsd ?? 0), 0);
  await pg.query(
    `
      update analitrics_meta.eval_runs
      set
        status = $2,
        completed_at = now(),
        elapsed_ms = greatest(0, floor(extract(epoch from (now() - started_at)) * 1000)::int),
        passed_count = $3,
        failed_count = $4,
        total_count = $5,
        estimated_cost_usd = $6
      where eval_run_id = $1
    `,
    [evalRunId, failed > 0 ? 'failed' : 'ok', passed, failed, results.length, totalCost],
  );
}

async function summarizeRecentRuns(): Promise<void> {
  const summary = await pg.query<{
    flow_mode: string;
    runs: string;
    avg_elapsed_ms: string | null;
    failed_runs: string;
    estimated_cost_usd: string | null;
  }>(
    `
      select
        flow_mode,
        count(*)::text as runs,
        round(avg(elapsed_ms))::text as avg_elapsed_ms,
        count(*) filter (where status <> 'ok')::text as failed_runs,
        round(sum(estimated_cost_usd), 8)::text as estimated_cost_usd
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
    estimated_cost_usd: string | null;
  }>(
    `
      select
        worker_name,
        count(*)::text as calls,
        round(avg(elapsed_ms))::text as avg_elapsed_ms,
        count(*) filter (where status <> 'ok')::text as errors,
        round(avg(total_tokens))::text as avg_total_tokens,
        round(sum(total_cost_usd), 8)::text as estimated_cost_usd
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
    `Evaluando Sprint 2 con user=${context.userId}, conversation=${context.conversationId}, filename=${context.filename ?? 'auto'}, flow=${flows.join('+')}`,
  );

  const evalRunId = await startEvalRun({
    suiteName: 'sprint2_comparison',
    context,
    flows,
  });
  const results: EvalResult[] = [];
  for (const flow of flows) {
    for (const testCase of selectedCases) {
      console.log(`\n[${flow}] ${testCase.id}: ${testCase.question}`);
      const result = await runCase(flow, testCase, context);
      results.push(result);
      await recordEvalCaseResult(evalRunId, testCase, result);
      const cost = result.estimatedCostUsd == null ? 'costo=N/D' : `costo=$${result.estimatedCostUsd.toFixed(6)}`;
      console.log(result.ok ? 'OK' : 'FAIL', `${result.elapsedMs}ms`, cost, result.answerPreview || result.error);
      if (!result.ok) {
        console.log(JSON.stringify({ checks: result.checks, sql: result.sql, error: result.error }, null, 2));
      }
    }
  }

  const passed = results.filter((result) => result.ok).length;
  const failed = results.length - passed;
  await finishEvalRun(evalRunId, results);
  console.log(`\nResultado Sprint 2: ${passed}/${results.length} correctas, ${failed} fallidas.`);
  console.table(
    results.map((result) => ({
      case: result.caseId,
      flow: result.flow,
      ok: result.ok,
      elapsedMs: result.elapsedMs,
      costUsd: result.estimatedCostUsd == null ? '' : result.estimatedCostUsd.toFixed(6),
      runId: result.runId ?? '',
    })),
  );
  console.log('\nComparativo por flujo');
  console.table(
    Object.entries(
      results.reduce<Record<string, { ok: number; total: number; elapsedMs: number; cost: number }>>(
        (acc, result) => {
          const current = acc[result.flow] ?? { ok: 0, total: 0, elapsedMs: 0, cost: 0 };
          current.ok += result.ok ? 1 : 0;
          current.total += 1;
          current.elapsedMs += result.elapsedMs;
          current.cost += result.estimatedCostUsd ?? 0;
          acc[result.flow] = current;
          return acc;
        },
        {},
      ),
    ).map(([flow, stats]) => ({
      flow,
      score: `${stats.ok}/${stats.total}`,
      avgElapsedMs: Math.round(stats.elapsedMs / stats.total),
      estimatedCostUsd: stats.cost.toFixed(6),
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
