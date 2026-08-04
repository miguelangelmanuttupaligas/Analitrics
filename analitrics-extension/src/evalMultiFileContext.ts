import fs from 'fs/promises';
import { closeConnections, initPostgres, pg } from './db.js';
import { answerWithDirectFileContext, type DirectFileAnswer } from './services/directFileAnswer.js';
import { importAttachmentIntoPostgres } from './services/ingestion.js';

type CheckResult = {
  name: string;
  ok: boolean;
  detail: string;
};

type MultiFileCase = {
  id: string;
  question: string;
  expectedSelectedAssets: string[];
  expectedExcludedAssets?: string[];
  filename?: string;
  expectsUnion: boolean;
  expectsSql: boolean;
  referenceSql?: string;
  compareColumns?: string[][];
  expectedTerms?: string[];
  isolatedOnly?: boolean;
  forbiddenSqlTerms?: string[];
};

type CaseResult = {
  id: string;
  ok: boolean;
  elapsedMs: number;
  selectedAssets: string[];
  sql: string;
  answerPreview: string;
  runId?: string;
  checks: CheckResult[];
};

const defaultUserId = '6a6cf19a9465f95900ab38cf';
const defaultConversationId = '0ae0856a-e61a-4db1-a9ad-7f919eabd7cf';
const isolatedConversationId = 'eval-multi-file-context';
const fileA = 'data_2024_2026.xlsx';
const fileB = 'ventas_2024_convertidas_a_2023.xlsx';
const extraFile = 'clientes_extra_contexto.csv';

const cases: MultiFileCase[] = [
  {
    id: 'combined_top_courses',
    question: 'Puedes unificar ambos archivos y responder el top de 5 cursos mas vendidos con monto total?',
    expectedSelectedAssets: [fileA, fileB],
    expectsUnion: true,
    expectsSql: true,
    compareColumns: [['producto', 'curso'], ['cantidad_ventas', 'ventas_totales', 'total_ventas'], ['monto_total']],
    referenceSql: `
      with ventas as (
        select producto, monto from analitrics_uploads.file_8a4239792082__hoja1
        union all
        select producto, monto from analitrics_uploads.file_4c8b2c5f5bd6__ventas_2023
      )
      select producto, count(*) as cantidad_ventas, sum(monto) as monto_total
      from ventas
      group by producto
      order by cantidad_ventas desc, monto_total desc
      limit 5
    `,
  },
  {
    id: 'single_file_a_top_courses',
    question: 'Solo para data_2024_2026.xlsx, dame el top 5 cursos más vendidos con monto total',
    filename: fileA,
    expectedSelectedAssets: [fileA],
    expectedExcludedAssets: [fileB],
    expectsUnion: false,
    expectsSql: true,
    compareColumns: [['producto', 'curso'], ['cantidad_ventas', 'ventas_totales', 'total_ventas'], ['monto_total']],
    referenceSql: `
      select producto, count(*) as cantidad_ventas, sum(monto) as monto_total
      from analitrics_uploads.file_8a4239792082__hoja1
      group by producto
      order by cantidad_ventas desc, monto_total desc
      limit 5
    `,
  },
  {
    id: 'single_file_b_top_courses',
    question: 'Ahora usa únicamente ventas_2024_convertidas_a_2023.xlsx y dame el top 5 cursos por cantidad con monto total',
    filename: fileB,
    expectedSelectedAssets: [fileB],
    expectedExcludedAssets: [fileA],
    expectsUnion: false,
    expectsSql: true,
    compareColumns: [['producto', 'curso'], ['cantidad_ventas', 'ventas_totales', 'total_ventas'], ['monto_total']],
    referenceSql: `
      select producto, count(*) as cantidad_ventas, sum(monto) as monto_total
      from analitrics_uploads.file_4c8b2c5f5bd6__ventas_2023
      group by producto
      order by cantidad_ventas desc, monto_total desc
      limit 5
    `,
  },
  {
    id: 'combined_after_single_focus',
    question: 'Vuelve a combinar ambos archivos y compara el top 5 de cursos vendidos con monto total',
    expectedSelectedAssets: [fileA, fileB],
    expectsUnion: true,
    expectsSql: true,
    compareColumns: [['producto', 'curso'], ['cantidad_ventas', 'ventas_totales', 'total_ventas'], ['monto_total']],
    referenceSql: `
      with ventas as (
        select producto, monto from analitrics_uploads.file_8a4239792082__hoja1
        union all
        select producto, monto from analitrics_uploads.file_4c8b2c5f5bd6__ventas_2023
      )
      select producto, count(*) as cantidad_ventas, sum(monto) as monto_total
      from ventas
      group by producto
      order by cantidad_ventas desc, monto_total desc
      limit 5
    `,
  },
  {
    id: 'single_file_a_row_count_after_combined',
    question: 'Para data_2024_2026.xlsx solamente, cuántos registros hay?',
    filename: fileA,
    expectedSelectedAssets: [fileA],
    expectedExcludedAssets: [fileB],
    expectsUnion: false,
    expectsSql: false,
    expectedTerms: ['10812'],
  },
  {
    id: 'single_file_b_row_count_after_file_a',
    question: 'Ahora para ventas_2024_convertidas_a_2023.xlsx solamente, cuántos registros hay?',
    filename: fileB,
    expectedSelectedAssets: [fileB],
    expectedExcludedAssets: [fileA],
    expectsUnion: false,
    expectsSql: true,
    compareColumns: [['total_registros', 'count']],
    referenceSql: `
      select count(*) as total_registros
      from analitrics_uploads.file_4c8b2c5f5bd6__ventas_2023
    `,
  },
  {
    id: 'column_list_file_a_only',
    question: 'Lista las variables de data_2024_2026.xlsx',
    filename: fileA,
    expectedSelectedAssets: [fileA],
    expectedExcludedAssets: [fileB],
    expectsUnion: false,
    expectsSql: false,
    expectedTerms: ['producto', 'monto', 'pais'],
  },
  {
    id: 'combined_country_amount',
    question: 'Con ambos archivos unidos, dame el monto total por país ordenado de mayor a menor',
    expectedSelectedAssets: [fileA, fileB],
    expectsUnion: true,
    expectsSql: true,
    compareColumns: [['pais'], ['monto_total']],
    referenceSql: `
      with ventas as (
        select pais, monto from analitrics_uploads.file_8a4239792082__hoja1
        union all
        select pais, monto from analitrics_uploads.file_4c8b2c5f5bd6__ventas_2023
      )
      select pais, sum(monto) as monto_total
      from ventas
      group by pais
      order by monto_total desc
    `,
  },
  {
    id: 'three_assets_named_two_file_union',
    question:
      'Une data_2024_2026.xlsx y ventas_2024_convertidas_a_2023.xlsx, ignora cualquier otro archivo, y dame el top 5 cursos más vendidos con monto total',
    expectedSelectedAssets: [fileA, fileB, extraFile],
    expectsUnion: true,
    expectsSql: true,
    isolatedOnly: true,
    forbiddenSqlTerms: ['clientes_extra_contexto', 'file_69a2f55b'],
    compareColumns: [['producto', 'curso'], ['cantidad_ventas', 'ventas_totales', 'total_ventas'], ['monto_total']],
    referenceSql: `
      with ventas as (
        select producto, monto from analitrics_uploads.file_8a4239792082__hoja1
        union all
        select producto, monto from analitrics_uploads.file_4c8b2c5f5bd6__ventas_2023
      )
      select producto, count(*) as cantidad_ventas, sum(monto) as monto_total
      from ventas
      group by producto
      order by cantidad_ventas desc, monto_total desc
      limit 5
    `,
  },
  {
    id: 'three_assets_extra_file_focus',
    question: 'Solo para clientes_extra_contexto.csv, lista las variables disponibles',
    filename: extraFile,
    expectedSelectedAssets: [extraFile],
    expectedExcludedAssets: [fileA, fileB],
    expectsUnion: false,
    expectsSql: false,
    isolatedOnly: true,
    expectedTerms: ['cliente_id', 'segmento', 'pais'],
  },
];

function normalize(value: unknown): string {
  if (value === null || value === undefined) {
    return '';
  }
  if (typeof value === 'number') {
    return String(Number(value.toFixed(4)));
  }
  return String(value)
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .replace(/,/g, '')
    .trim()
    .toLowerCase();
}

function preview(value: string | undefined, maxLength = 220): string {
  const compact = (value ?? '').replace(/\s+/g, ' ').trim();
  return compact.length > maxLength ? `${compact.slice(0, maxLength - 1)}…` : compact;
}

async function runReference(sql: string): Promise<Record<string, unknown>[]> {
  const result = await pg.query(sql);
  return result.rows;
}

async function getObservedRows(runId?: string): Promise<Record<string, unknown>[]> {
  if (!runId) {
    return [];
  }
  const result = await pg.query<{ metadata_json: Record<string, unknown> }>(
    `
      select metadata_json
      from analitrics_meta.agent_runs
      where run_id = $1
    `,
    [runId],
  );
  const sqlRows = result.rows[0]?.metadata_json?.sqlRows;
  return Array.isArray(sqlRows) ? (sqlRows as Record<string, unknown>[]) : [];
}

function pickValue(row: Record<string, unknown>, candidates: string[]): unknown {
  for (const candidate of candidates) {
    if (Object.prototype.hasOwnProperty.call(row, candidate)) {
      return row[candidate];
    }
  }
  return undefined;
}

function compareRows(
  observedRows: Record<string, unknown>[],
  referenceRows: Record<string, unknown>[],
  columns: string[][],
): CheckResult {
  const observed = observedRows.slice(0, referenceRows.length).map((row) =>
    columns.map((columnCandidates) => normalize(pickValue(row, columnCandidates))).join('|'),
  );
  const expected = referenceRows.map((row) =>
    columns.map((columnCandidates) => normalize(pickValue(row, columnCandidates))).join('|'),
  );
  const ok = observed.length === expected.length && expected.every((row, index) => row === observed[index]);
  return {
    name: 'referenceData',
    ok,
    detail: ok
      ? `${expected.length} filas coinciden con SQL de referencia`
      : `esperado=${JSON.stringify(expected.slice(0, 5))}; observado=${JSON.stringify(observed.slice(0, 5))}`,
  };
}

async function runCase(testCase: MultiFileCase, context: { userId: string; conversationId: string }): Promise<CaseResult> {
  const startedAtMs = Date.now();
  const result: DirectFileAnswer = await answerWithDirectFileContext(context, testCase.question, {
    conversationId: context.conversationId,
    filename: testCase.filename,
  });
  const selectedAssets = result.snapshot?.selectedAssets.map((asset) => asset.filename) ?? [];
  const sql = result.plan?.sql ?? '';
  const answer = result.answer ?? '';
  const checks: CheckResult[] = [
    {
      name: 'handled',
      ok: result.handled,
      detail: result.handled ? 'respondido por direct_file' : result.reason ?? 'no manejado',
    },
    {
      name: 'expectedSelectedAssets',
      ok: testCase.expectedSelectedAssets.every((asset) => selectedAssets.includes(asset)),
      detail: `selected=${selectedAssets.join(', ')}`,
    },
    {
      name: 'excludedAssets',
      ok: !(testCase.expectedExcludedAssets ?? []).some((asset) => selectedAssets.includes(asset)),
      detail: `excluded=${(testCase.expectedExcludedAssets ?? []).join(', ') || 'N/A'}`,
    },
    {
      name: 'sqlPresence',
      ok: testCase.expectsSql ? sql.trim().length > 0 : true,
      detail: testCase.expectsSql ? preview(sql, 160) : 'SQL no requerido',
    },
    {
      name: 'unionUsage',
      ok: testCase.expectsUnion ? /union\s+all/i.test(sql) : !/union\s+all/i.test(sql),
      detail: testCase.expectsUnion ? 'debe usar UNION ALL' : 'no debe usar UNION ALL',
    },
    {
      name: 'noUploadRequest',
      ok: !/(sube|carga|adjunta|proporciona).{0,80}archivo/i.test(answer),
      detail: preview(answer, 180),
    },
  ];

  if (testCase.forbiddenSqlTerms?.length) {
    const normalizedSql = normalize(sql);
    checks.push({
      name: 'forbiddenSqlTerms',
      ok: testCase.forbiddenSqlTerms.every((term) => !normalizedSql.includes(normalize(term))),
      detail: `forbidden=${testCase.forbiddenSqlTerms.join(', ')}`,
    });
  }

  if (testCase.expectedTerms?.length) {
    const normalizedAnswer = normalize(answer);
    checks.push({
      name: 'answerTerms',
      ok: testCase.expectedTerms.every((term) => normalizedAnswer.includes(normalize(term))),
      detail: `terms=${testCase.expectedTerms.join(', ')}`,
    });
  }

  if (testCase.referenceSql && testCase.compareColumns?.length) {
    const [referenceRows, observedRows] = await Promise.all([
      runReference(testCase.referenceSql),
      Promise.resolve(result.execution?.sqlRows ?? []),
    ]);
    checks.push(compareRows(observedRows, referenceRows, testCase.compareColumns));
  }

  return {
    id: testCase.id,
    ok: checks.every((check) => check.ok),
    elapsedMs: Date.now() - startedAtMs,
    selectedAssets,
    sql,
    answerPreview: preview(answer),
    runId: result.observabilityRunId,
    checks,
  };
}

async function createIsolatedContext(userId: string): Promise<string> {
  await pg.query(
    `
      delete from analitrics_meta.conversation_file_contexts
      where user_id = $1
        and conversation_id = $2
    `,
    [userId, isolatedConversationId],
  );

  await pg.query(
    `
      insert into analitrics_meta.conversation_file_contexts(
        user_id, conversation_id, upload_id, filename, mime_type, is_active
      )
      select user_id, $2, upload_id, filename, mime_type, true
      from analitrics_meta.uploaded_files
      where user_id = $1
        and filename = any($3::text[])
      on conflict (user_id, conversation_id, upload_id)
      do update set is_active = true, filename = excluded.filename, updated_at = now()
    `,
    [userId, isolatedConversationId, [fileA, fileB]],
  );

  const extraPath = '/tmp/analitrics-clientes-extra-contexto.csv';
  await fs.writeFile(
    extraPath,
    [
      'cliente_id,segmento,pais,score_riesgo',
      '1,Enterprise,Peru,0.12',
      '2,Pyme,Chile,0.42',
      '3,Enterprise,Colombia,0.22',
    ].join('\n'),
    'utf-8',
  );
  await importAttachmentIntoPostgres({
    userId,
    conversationId: isolatedConversationId,
    messageId: 'eval-extra-file-message',
    fileId: 'eval-extra-file-clientes',
    filename: extraFile,
    mimeType: 'text/csv',
    filepath: extraPath,
    absolutePath: extraPath,
    bytes: Buffer.byteLength(await fs.readFile(extraPath)),
  });

  return isolatedConversationId;
}

async function main(): Promise<void> {
  await initPostgres();
  const useIsolatedContext = process.env.EVAL_ISOLATED_CONTEXT === 'true';
  const userId = process.env.EVAL_USER_ID ?? defaultUserId;
  const context = {
    userId,
    conversationId: useIsolatedContext
      ? await createIsolatedContext(userId)
      : process.env.EVAL_CONVERSATION_ID ?? defaultConversationId,
  };
  const requestedCases = (process.env.EVAL_CASES ?? '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
  const selectedCases = requestedCases.length
    ? cases.filter((testCase) => requestedCases.includes(testCase.id))
    : cases.filter((testCase) => useIsolatedContext || !testCase.isolatedOnly);

  console.log(`Evaluando multiarchivo user=${context.userId}, conversation=${context.conversationId}`);
  const results: CaseResult[] = [];
  for (const testCase of selectedCases) {
    console.log(`\n${testCase.id}: ${testCase.question}`);
    const result = await runCase(testCase, context);
    results.push(result);
    console.log(result.ok ? 'OK' : 'FAIL', `${result.elapsedMs}ms`, `run=${result.runId ?? 'N/D'}`);
    console.log(`assets=${result.selectedAssets.join(', ')}`);
    console.log(`respuesta=${result.answerPreview}`);
    for (const check of result.checks) {
      console.log(`  ${check.ok ? 'OK' : 'FAIL'} ${check.name}: ${check.detail}`);
    }
  }

  const passed = results.filter((result) => result.ok).length;
  const failed = results.length - passed;
  console.log(`\nResultado multiarchivo: ${passed}/${results.length} correctas, ${failed} fallidas.`);
  console.table(
    results.map((result) => ({
      case: result.id,
      ok: result.ok,
      elapsedMs: result.elapsedMs,
      assets: result.selectedAssets.join(' + '),
      runId: result.runId ?? '',
    })),
  );

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
