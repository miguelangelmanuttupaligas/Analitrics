import type { AnalyticsIntent, CleanedQuestion, ContextSnapshot } from '../../types.js';
import { callJsonWorker } from '../llm.js';
import { composePrompt, loadPrompt } from '../prompts.js';
import { buildWorkerContextBrief, parseCleanedQuestion, parseIntent } from '../workerSupport.js';

export async function runIntentWorker(question: string, snapshot: ContextSnapshot): Promise<AnalyticsIntent> {
  return callJsonWorker({
    workerName: 'intent_worker',
    systemPrompt: composePrompt(
      loadPrompt('shared', 'analitrics_core.md'),
      loadPrompt('shared', 'json_contract.md'),
      loadPrompt('graph', 'intent.md'),
    ),
    userPrompt: `Pregunta del usuario:\n${question}\n\nContexto disponible:\n${buildWorkerContextBrief(snapshot)}`,
    parse: (value) => parseIntent(value, question),
  });
}

export async function runQuestionCleanupWorker(
  question: string,
  snapshot: ContextSnapshot,
): Promise<CleanedQuestion> {
  return callJsonWorker({
    workerName: 'question_cleanup_worker',
    systemPrompt: composePrompt(
      loadPrompt('shared', 'analitrics_core.md'),
      loadPrompt('shared', 'json_contract.md'),
      loadPrompt('graph', 'question_cleanup.md'),
    ),
    userPrompt: `Pregunta original:\n${question}\n\nContexto disponible:\n${buildWorkerContextBrief(snapshot)}`,
    parse: (value) => parseCleanedQuestion(value, question),
  });
}
