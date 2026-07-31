import { config } from '../config.js';
import { recordLlmCall } from './observability.js';

type ChatMessage = {
  role: 'system' | 'user';
  content: string;
};

type OpenAIUsage = {
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
};

type JsonWorkerArgs<T> = {
  workerName: string;
  systemPrompt: string;
  userPrompt: string;
  parse: (value: unknown) => T;
};

type TextWorkerArgs = {
  workerName: string;
  systemPrompt: string;
  userPrompt: string;
};

function cleanJsonBlock(value: string): string {
  const trimmed = value.trim();
  if (!trimmed.startsWith('```')) {
    return trimmed;
  }
  return trimmed.replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '').trim();
}

async function callOpenAI(
  messages: ChatMessage[],
  asJson: boolean,
): Promise<{ content: string; usage?: OpenAIUsage }> {
  if (!config.OPENAI_API_KEY) {
    throw new Error('OPENAI_API_KEY no está configurado para los workers de Analitrics.');
  }

  const response = await fetch('https://api.openai.com/v1/chat/completions', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${config.OPENAI_API_KEY}`,
    },
    body: JSON.stringify({
      model: config.WORKER_MODEL,
      temperature: 0.1,
      response_format: asJson ? { type: 'json_object' } : undefined,
      messages,
    }),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Worker LLM failed (${response.status}): ${errorText}`);
  }

  const data = (await response.json()) as {
    choices?: Array<{ message?: { content?: string } }>;
    usage?: OpenAIUsage;
  };
  const content = data.choices?.[0]?.message?.content?.trim();
  if (!content) {
    throw new Error('Worker LLM devolvió una respuesta vacía.');
  }
  return { content, usage: data.usage };
}

export async function callJsonWorker<T>(args: JsonWorkerArgs<T>): Promise<T>;
export async function callJsonWorker<T>(
  systemPrompt: string,
  userPrompt: string,
  parse: (value: unknown) => T,
): Promise<T>;
export async function callJsonWorker<T>(
  argsOrSystemPrompt: JsonWorkerArgs<T> | string,
  legacyUserPrompt?: string,
  legacyParse?: (value: unknown) => T,
): Promise<T> {
  const args =
    typeof argsOrSystemPrompt === 'string'
      ? {
          workerName: 'unknown_json_worker',
          systemPrompt: argsOrSystemPrompt,
          userPrompt: legacyUserPrompt ?? '',
          parse: legacyParse as (value: unknown) => T,
        }
      : argsOrSystemPrompt;
  const startedAtMs = Date.now();
  const inputChars = args.systemPrompt.length + args.userPrompt.length;
  let outputChars: number | undefined;
  let usage: OpenAIUsage | undefined;

  try {
    const response = await callOpenAI(
      [
        { role: 'system', content: args.systemPrompt },
        { role: 'user', content: args.userPrompt },
      ],
      true,
    );
    const raw = response.content;
    usage = response.usage;
    outputChars = raw.length;
    const parsed = JSON.parse(cleanJsonBlock(raw)) as unknown;
    const result = args.parse(parsed);
    await recordLlmCall({
      workerName: args.workerName,
      model: config.WORKER_MODEL,
      jsonMode: true,
      status: 'ok',
      elapsedMs: Date.now() - startedAtMs,
      promptTokens: usage?.prompt_tokens,
      completionTokens: usage?.completion_tokens,
      totalTokens: usage?.total_tokens,
      inputChars,
      outputChars,
      parseOk: true,
    });
    return result;
  } catch (error) {
    await recordLlmCall({
      workerName: args.workerName,
      model: config.WORKER_MODEL,
      jsonMode: true,
      status: 'error',
      elapsedMs: Date.now() - startedAtMs,
      promptTokens: usage?.prompt_tokens,
      completionTokens: usage?.completion_tokens,
      totalTokens: usage?.total_tokens,
      inputChars,
      outputChars,
      parseOk: false,
      parseError: error instanceof SyntaxError ? error.message : undefined,
      error: error instanceof Error ? error.message : String(error),
    });
    throw error;
  }
}

export async function callTextWorker(args: TextWorkerArgs): Promise<string>;
export async function callTextWorker(systemPrompt: string, userPrompt: string): Promise<string>;
export async function callTextWorker(
  argsOrSystemPrompt: TextWorkerArgs | string,
  legacyUserPrompt?: string,
): Promise<string> {
  const args =
    typeof argsOrSystemPrompt === 'string'
      ? {
          workerName: 'unknown_text_worker',
          systemPrompt: argsOrSystemPrompt,
          userPrompt: legacyUserPrompt ?? '',
        }
      : argsOrSystemPrompt;
  const startedAtMs = Date.now();
  const inputChars = args.systemPrompt.length + args.userPrompt.length;
  let usage: OpenAIUsage | undefined;

  try {
    const response = await callOpenAI(
      [
        { role: 'system', content: args.systemPrompt },
        { role: 'user', content: args.userPrompt },
      ],
      false,
    );
    usage = response.usage;
    await recordLlmCall({
      workerName: args.workerName,
      model: config.WORKER_MODEL,
      jsonMode: false,
      status: 'ok',
      elapsedMs: Date.now() - startedAtMs,
      promptTokens: usage?.prompt_tokens,
      completionTokens: usage?.completion_tokens,
      totalTokens: usage?.total_tokens,
      inputChars,
      outputChars: response.content.length,
    });
    return response.content;
  } catch (error) {
    await recordLlmCall({
      workerName: args.workerName,
      model: config.WORKER_MODEL,
      jsonMode: false,
      status: 'error',
      elapsedMs: Date.now() - startedAtMs,
      promptTokens: usage?.prompt_tokens,
      completionTokens: usage?.completion_tokens,
      totalTokens: usage?.total_tokens,
      inputChars,
      error: error instanceof Error ? error.message : String(error),
    });
    throw error;
  }
}
