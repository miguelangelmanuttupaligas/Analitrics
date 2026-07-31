import { config } from '../config.js';

type ChatMessage = {
  role: 'system' | 'user';
  content: string;
};

function cleanJsonBlock(value: string): string {
  const trimmed = value.trim();
  if (!trimmed.startsWith('```')) {
    return trimmed;
  }
  return trimmed.replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '').trim();
}

async function callOpenAI(messages: ChatMessage[], asJson: boolean): Promise<string> {
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
  };
  const content = data.choices?.[0]?.message?.content?.trim();
  if (!content) {
    throw new Error('Worker LLM devolvió una respuesta vacía.');
  }
  return content;
}

export async function callJsonWorker<T>(
  systemPrompt: string,
  userPrompt: string,
  parse: (value: unknown) => T,
): Promise<T> {
  const raw = await callOpenAI(
    [
      { role: 'system', content: systemPrompt },
      { role: 'user', content: userPrompt },
    ],
    true,
  );
  const parsed = JSON.parse(cleanJsonBlock(raw)) as unknown;
  return parse(parsed);
}

export async function callTextWorker(systemPrompt: string, userPrompt: string): Promise<string> {
  return callOpenAI(
    [
      { role: 'system', content: systemPrompt },
      { role: 'user', content: userPrompt },
    ],
    false,
  );
}
