import fs from 'node:fs';
import path from 'node:path';

const cache = new Map<string, string>();

export function loadPrompt(...parts: string[]): string {
  const promptPath = path.join(process.cwd(), 'prompts', ...parts);
  const cached = cache.get(promptPath);
  if (cached != null) {
    return cached;
  }

  const value = fs.readFileSync(promptPath, 'utf8').trim();
  cache.set(promptPath, value);
  return value;
}

export function composePrompt(...prompts: string[]): string {
  return prompts.map((prompt) => prompt.trim()).filter(Boolean).join('\n\n');
}
