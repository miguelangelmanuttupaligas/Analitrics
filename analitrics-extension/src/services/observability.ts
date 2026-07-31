import { AsyncLocalStorage } from 'node:async_hooks';
import { randomUUID } from 'node:crypto';
import { pg } from '../db.js';
import type { GraphNodeTrace } from '../types.js';

export type FlowMode = 'direct_file' | 'graph' | 'eval';

type ObservabilityContext = {
  runId: string;
  flowMode: FlowMode;
};

type LlmCallRecord = {
  workerName: string;
  model: string;
  jsonMode: boolean;
  status: 'ok' | 'error';
  elapsedMs: number;
  promptTokens?: number;
  completionTokens?: number;
  totalTokens?: number;
  inputChars: number;
  outputChars?: number;
  parseOk?: boolean;
  parseError?: string;
  error?: string;
};

const storage = new AsyncLocalStorage<ObservabilityContext>();

function truncate(value: string | undefined, maxLength = 1600): string | undefined {
  if (!value) {
    return value;
  }
  return value.length > maxLength ? `${value.slice(0, maxLength - 1)}…` : value;
}

async function safeQuery(sql: string, values: unknown[]): Promise<void> {
  try {
    await pg.query(sql, values);
  } catch (error) {
    console.warn(
      JSON.stringify({
        type: 'analitrics_observability_error',
        error: error instanceof Error ? error.message : String(error),
      }),
    );
  }
}

export function getObservabilityContext(): ObservabilityContext | undefined {
  return storage.getStore();
}

export async function withObservabilityContext<T>(
  context: ObservabilityContext,
  fn: () => Promise<T>,
): Promise<T> {
  return storage.run(context, fn);
}

export async function startAgentRun(params: {
  flowMode: FlowMode;
  userId: string;
  conversationId?: string;
  question: string;
  metadata?: Record<string, unknown>;
}): Promise<string> {
  const runId = randomUUID();
  await safeQuery(
    `
      insert into analitrics_meta.agent_runs(
        run_id, flow_mode, user_id, conversation_id, question, metadata_json
      )
      values ($1, $2, $3, $4, $5, $6::jsonb)
    `,
    [
      runId,
      params.flowMode,
      params.userId,
      params.conversationId ?? null,
      params.question,
      JSON.stringify(params.metadata ?? {}),
    ],
  );
  return runId;
}

export async function finishAgentRun(params: {
  runId: string;
  status: 'ok' | 'error' | 'skipped';
  resultSummary?: string;
  error?: unknown;
  metadata?: Record<string, unknown>;
}): Promise<void> {
  await safeQuery(
    `
      update analitrics_meta.agent_runs
      set
        status = $2,
        completed_at = now(),
        elapsed_ms = greatest(0, floor(extract(epoch from (now() - started_at)) * 1000)::int),
        result_summary = $3,
        error = $4,
        metadata_json = metadata_json || $5::jsonb
      where run_id = $1
    `,
    [
      params.runId,
      params.status,
      truncate(params.resultSummary),
      truncate(params.error instanceof Error ? params.error.message : String(params.error ?? '')),
      JSON.stringify(params.metadata ?? {}),
    ],
  );
}

export async function recordNodeTrace(
  trace: GraphNodeTrace,
  metadata: Record<string, unknown> = {},
): Promise<void> {
  const context = getObservabilityContext();
  if (!context) {
    return;
  }
  await safeQuery(
    `
      insert into analitrics_meta.agent_node_traces(
        run_id, node_name, status, started_at, completed_at, elapsed_ms, summary, error, metadata_json
      )
      values ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
    `,
    [
      context.runId,
      trace.node,
      trace.status,
      trace.startedAt,
      trace.completedAt,
      trace.elapsedMs,
      truncate(trace.summary),
      trace.status === 'error' ? truncate(trace.summary) : null,
      JSON.stringify(metadata),
    ],
  );
}

export async function recordLlmCall(record: LlmCallRecord): Promise<void> {
  const context = getObservabilityContext();
  await safeQuery(
    `
      insert into analitrics_meta.agent_llm_calls(
        run_id, flow_mode, worker_name, model, json_mode, status, elapsed_ms,
        prompt_tokens, completion_tokens, total_tokens, input_chars, output_chars,
        parse_ok, parse_error, error
      )
      values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
    `,
    [
      context?.runId ?? null,
      context?.flowMode ?? null,
      record.workerName,
      record.model,
      record.jsonMode,
      record.status,
      record.elapsedMs,
      record.promptTokens ?? null,
      record.completionTokens ?? null,
      record.totalTokens ?? null,
      record.inputChars,
      record.outputChars ?? null,
      record.parseOk ?? null,
      truncate(record.parseError),
      truncate(record.error),
    ],
  );
}
