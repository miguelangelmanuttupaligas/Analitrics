import type { AnalyticsSourceSelection, CleanedQuestion, ContextSnapshot } from '../../types.js';
import { callJsonWorker } from '../llm.js';
import { composePrompt, loadPrompt } from '../prompts.js';
import { buildWorkerContextBrief, compactJson, parseContextSelection, parseSourceSelection } from '../workerSupport.js';

export async function runContextSelectionWorker(
  question: string,
  snapshot: ContextSnapshot,
): Promise<{ selectedUploadIds: string[]; rationale: string }> {
  return callJsonWorker({
    workerName: 'context_selection_worker',
    systemPrompt: composePrompt(
      loadPrompt('shared', 'analitrics_core.md'),
      loadPrompt('shared', 'json_contract.md'),
      loadPrompt('graph', 'context_selection.md'),
    ),
    userPrompt: [
      `Pregunta:\n${question}`,
      `Contexto resumido:\n${buildWorkerContextBrief(snapshot)}`,
    ].join('\n\n'),
    parse: (value) => parseContextSelection(value, snapshot.budget.maxAssets),
  });
}

export async function runSourceSelectionWorker(params: {
  cleanedQuestion: CleanedQuestion;
  snapshot: ContextSnapshot;
}): Promise<AnalyticsSourceSelection> {
  const { cleanedQuestion, snapshot } = params;
  return callJsonWorker({
    workerName: 'source_selection_worker',
    systemPrompt: composePrompt(
      loadPrompt('shared', 'analitrics_core.md'),
      loadPrompt('shared', 'json_contract.md'),
      loadPrompt('graph', 'source_selection.md'),
    ),
    userPrompt: [
      `Pregunta limpia:\n${compactJson(cleanedQuestion)}`,
      `Contexto resumido:\n${buildWorkerContextBrief(snapshot)}`,
    ].join('\n\n'),
    parse: (value) => parseSourceSelection(value),
  });
}
