import type { GraphNodeTrace } from '../types.js';

function summarizeValue(value: unknown): string {
  if (value == null) {
    return 'sin cambios';
  }
  if (typeof value === 'string') {
    return value.length > 120 ? `${value.slice(0, 117)}...` : value;
  }
  if (Array.isArray(value)) {
    return `array(${value.length})`;
  }
  if (typeof value === 'object') {
    return `keys(${Object.keys(value as Record<string, unknown>).join(', ').slice(0, 140)})`;
  }
  return String(value);
}

export function buildNodeTrace(params: {
  node: string;
  startedAtMs: number;
  status: 'ok' | 'error';
  result?: Record<string, unknown>;
  error?: unknown;
}): GraphNodeTrace {
  const completedAtMs = Date.now();
  const startedAt = new Date(params.startedAtMs).toISOString();
  const completedAt = new Date(completedAtMs).toISOString();
  const elapsedMs = completedAtMs - params.startedAtMs;
  const summary =
    params.status === 'error'
      ? params.error instanceof Error
        ? params.error.message
        : String(params.error ?? 'error')
      : params.result
        ? Object.entries(params.result)
            .map(([key, value]) => `${key}=${summarizeValue(value)}`)
            .join('; ')
        : 'ok';

  return {
    node: params.node,
    startedAt,
    completedAt,
    elapsedMs,
    status: params.status,
    summary,
  };
}

export function logNodeTrace(trace: GraphNodeTrace): void {
  console.info(
    JSON.stringify({
      type: 'analitrics_graph_node',
      node: trace.node,
      startedAt: trace.startedAt,
      completedAt: trace.completedAt,
      elapsedMs: trace.elapsedMs,
      status: trace.status,
      summary: trace.summary,
    }),
  );
}
