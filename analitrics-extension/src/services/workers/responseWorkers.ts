import type {
  AnalyticsExecution,
  AnalyticsIntent,
  AnalyticsPlan,
  AnalyticsValidation,
  CleanedQuestion,
  ContextSnapshot,
} from '../../types.js';
import { callJsonWorker, callTextWorker } from '../llm.js';
import { composePrompt, loadPrompt } from '../prompts.js';
import { compactJson, parseValidation } from '../workerSupport.js';

export async function runValidationWorker(params: {
  question: string;
  cleanedQuestion: CleanedQuestion;
  snapshot: ContextSnapshot;
  intent: AnalyticsIntent;
  plan: AnalyticsPlan;
  execution: AnalyticsExecution;
  draftedAnswer: string;
}): Promise<AnalyticsValidation> {
  const { question, cleanedQuestion, snapshot, intent, plan, execution, draftedAnswer } = params;
  return callJsonWorker({
    workerName: 'validation_worker',
    systemPrompt: composePrompt(
      loadPrompt('shared', 'analitrics_core.md'),
      loadPrompt('shared', 'json_contract.md'),
      loadPrompt('graph', 'validation.md'),
    ),
    userPrompt: [
      `Pregunta:\n${question}`,
      `Pregunta limpia:\n${compactJson(cleanedQuestion)}`,
      `Contexto:\n${compactJson(snapshot)}`,
      `Intención:\n${compactJson(intent)}`,
      `Plan:\n${compactJson(plan)}`,
      `Ejecución:\n${compactJson(execution)}`,
      `Borrador de respuesta:\n${draftedAnswer}`,
    ].join('\n\n'),
    parse: (value) => parseValidation(value),
  });
}

export async function runValidationReconciliationWorker(params: {
  question: string;
  cleanedQuestion: CleanedQuestion;
  snapshot: ContextSnapshot;
  intent: AnalyticsIntent;
  plan: AnalyticsPlan;
  execution: AnalyticsExecution;
  validation: AnalyticsValidation;
  draftedAnswer: string;
}): Promise<AnalyticsValidation> {
  const { question, cleanedQuestion, snapshot, intent, plan, execution, validation, draftedAnswer } = params;
  return callJsonWorker({
    workerName: 'validation_reconciliation_worker',
    systemPrompt: composePrompt(
      loadPrompt('shared', 'analitrics_core.md'),
      loadPrompt('shared', 'json_contract.md'),
      loadPrompt('graph', 'validation_reconciliation.md'),
    ),
    userPrompt: [
      `Pregunta:\n${question}`,
      `Pregunta limpia:\n${compactJson(cleanedQuestion)}`,
      `Intención:\n${compactJson(intent)}`,
      `Contexto:\n${compactJson(snapshot)}`,
      `Plan:\n${compactJson(plan)}`,
      `Ejecución:\n${compactJson(execution)}`,
      `Borrador:\n${draftedAnswer}`,
      `Validación preliminar:\n${compactJson(validation)}`,
    ].join('\n\n'),
    parse: (value) => parseValidation(value),
  });
}

export async function runAnswerWorker(params: {
  question: string;
  cleanedQuestion: CleanedQuestion;
  snapshot: ContextSnapshot;
  intent: AnalyticsIntent;
  plan: AnalyticsPlan;
  execution: AnalyticsExecution;
  validationIssues?: string[];
}): Promise<string> {
  const { question, cleanedQuestion, snapshot, intent, plan, execution, validationIssues = [] } = params;
  return callTextWorker({
    workerName: 'answer_worker',
    systemPrompt: composePrompt(
      loadPrompt('shared', 'analitrics_core.md'),
      loadPrompt('shared', 'answer_style.md'),
      loadPrompt('graph', 'answer.md'),
      validationIssues.length
        ? `Corrige estos problemas detectados: ${validationIssues.join(' | ')}`
        : 'No hay problemas de validación previos.',
    ),
    userPrompt: [
      `Pregunta:\n${question}`,
      `Pregunta limpia:\n${compactJson(cleanedQuestion)}`,
      `Contexto:\n${compactJson(snapshot)}`,
      `Intención:\n${compactJson(intent)}`,
      `Plan:\n${compactJson(plan)}`,
      `Ejecución:\n${compactJson(execution)}`,
    ].join('\n\n'),
  });
}

export async function runResponseCleanupWorker(params: {
  originalQuestion: string;
  cleanedQuestion: CleanedQuestion;
  answerDraft: string;
  responseMode: AnalyticsPlan['responseMode'];
  hasVisualResource: boolean;
}): Promise<string> {
  const { originalQuestion, cleanedQuestion, answerDraft, responseMode, hasVisualResource } = params;
  return callTextWorker({
    workerName: 'response_cleanup_worker',
    systemPrompt: composePrompt(
      loadPrompt('shared', 'analitrics_core.md'),
      loadPrompt('shared', 'answer_style.md'),
      loadPrompt('graph', 'response_cleanup.md'),
    ),
    userPrompt: [
      `Pregunta original:\n${originalQuestion}`,
      `Pregunta limpia:\n${compactJson(cleanedQuestion)}`,
      `Modo de respuesta esperado: ${responseMode}`,
      `¿Habrá recurso visual inline?: ${hasVisualResource ? 'sí' : 'no'}`,
      `Borrador:\n${answerDraft}`,
    ].join('\n\n'),
  });
}

export async function runAnswerReconciliationWorker(params: {
  question: string;
  snapshot: ContextSnapshot;
  plan: AnalyticsPlan;
  execution: AnalyticsExecution;
  answerDraft: string;
}): Promise<string> {
  const { question, snapshot, plan, execution, answerDraft } = params;
  return callTextWorker({
    workerName: 'answer_reconciliation_worker',
    systemPrompt: composePrompt(
      loadPrompt('shared', 'analitrics_core.md'),
      loadPrompt('shared', 'answer_style.md'),
      loadPrompt('graph', 'answer_reconciliation.md'),
    ),
    userPrompt: [
      `Pregunta:\n${question}`,
      `Contexto:\n${compactJson(snapshot)}`,
      `Plan:\n${compactJson(plan)}`,
      `Ejecución:\n${compactJson(execution)}`,
      `Borrador actual:\n${answerDraft}`,
    ].join('\n\n'),
  });
}
