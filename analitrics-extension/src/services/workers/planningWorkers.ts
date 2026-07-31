import type {
  AnalyticsExecution,
  AnalyticsIntent,
  AnalyticsPlan,
  AnalyticsSourceSelection,
  AnalyticsValidation,
  CleanedQuestion,
  ContextSnapshot,
} from '../../types.js';
import { callJsonWorker } from '../llm.js';
import { composePrompt, loadPrompt } from '../prompts.js';
import {
  buildPlanningGuidance,
  buildWorkerContextBrief,
  compactJson,
  parsePlan,
  parseSqlSafety,
} from '../workerSupport.js';

export async function runPlanningWorker(
  cleanedQuestion: CleanedQuestion,
  snapshot: ContextSnapshot,
  intent: AnalyticsIntent,
  sourceSelection: AnalyticsSourceSelection,
): Promise<AnalyticsPlan> {
  return callJsonWorker({
    workerName: 'planning_worker',
    systemPrompt: composePrompt(
      loadPrompt('shared', 'analitrics_core.md'),
      loadPrompt('shared', 'data_contract.md'),
      loadPrompt('shared', 'json_contract.md'),
      loadPrompt('graph', 'planning.md'),
    ),
    userPrompt: [
      `Pregunta limpia:\n${compactJson(cleanedQuestion)}`,
      `Intención:\n${compactJson(intent)}`,
      `Selección de fuente:\n${compactJson(sourceSelection)}`,
      `Guía operativa:\n${buildPlanningGuidance(snapshot, intent, sourceSelection)}`,
      `Contexto:\n${buildWorkerContextBrief(snapshot)}`,
    ].join('\n\n'),
    parse: (value) => parsePlan(value, cleanedQuestion.cleanedQuestion, snapshot, intent, sourceSelection),
  });
}

export async function runPlanReconciliationWorker(params: {
  cleanedQuestion: CleanedQuestion;
  snapshot: ContextSnapshot;
  intent: AnalyticsIntent;
  sourceSelection: AnalyticsSourceSelection;
  proposedPlan: AnalyticsPlan;
}): Promise<AnalyticsPlan> {
  const { cleanedQuestion, snapshot, intent, sourceSelection, proposedPlan } = params;
  return callJsonWorker({
    workerName: 'plan_reconciliation_worker',
    systemPrompt: composePrompt(
      loadPrompt('shared', 'analitrics_core.md'),
      loadPrompt('shared', 'data_contract.md'),
      loadPrompt('shared', 'json_contract.md'),
      loadPrompt('graph', 'plan_reconciliation.md'),
    ),
    userPrompt: [
      `Pregunta limpia:\n${compactJson(cleanedQuestion)}`,
      `Intención:\n${compactJson(intent)}`,
      `Selección de fuente:\n${compactJson(sourceSelection)}`,
      `Guía operativa:\n${buildPlanningGuidance(snapshot, intent, sourceSelection)}`,
      `Contexto:\n${buildWorkerContextBrief(snapshot)}`,
      `Plan propuesto:\n${compactJson(proposedPlan)}`,
    ].join('\n\n'),
    parse: (value) => parsePlan(value, cleanedQuestion.cleanedQuestion, snapshot, intent, sourceSelection),
  });
}

export async function runSqlSafetyWorker(params: {
  question: string;
  snapshot: ContextSnapshot;
  plan: AnalyticsPlan;
}): Promise<{
  approved: boolean;
  sanitizedSql: string;
  rationale: string;
  shouldClarify: boolean;
  clarificationQuestion: string;
}> {
  const { question, snapshot, plan } = params;
  if (!plan.sql.trim()) {
    return {
      approved: true,
      sanitizedSql: '',
      rationale: 'El plan no requiere SQL.',
      shouldClarify: false,
      clarificationQuestion: '',
    };
  }

  return callJsonWorker({
    workerName: 'sql_safety_worker',
    systemPrompt: composePrompt(
      loadPrompt('shared', 'analitrics_core.md'),
      loadPrompt('shared', 'json_contract.md'),
      loadPrompt('shared', 'sql_safety.md'),
      loadPrompt('graph', 'sql_safety.md'),
    ),
    userPrompt: [
      `Pregunta:\n${question}`,
      `Contexto:\n${buildWorkerContextBrief(snapshot)}`,
      `Plan:\n${compactJson(plan)}`,
    ].join('\n\n'),
    parse: (value) => parseSqlSafety(value),
  });
}

export async function runRepairPlanningWorker(params: {
  question: string;
  cleanedQuestion: CleanedQuestion;
  snapshot: ContextSnapshot;
  intent: AnalyticsIntent;
  sourceSelection: AnalyticsSourceSelection;
  previousPlan: AnalyticsPlan;
  execution: AnalyticsExecution;
  validation: AnalyticsValidation;
}): Promise<AnalyticsPlan> {
  const { question, cleanedQuestion, snapshot, intent, sourceSelection, previousPlan, execution, validation } = params;
  return callJsonWorker({
    workerName: 'repair_planning_worker',
    systemPrompt: composePrompt(
      loadPrompt('shared', 'analitrics_core.md'),
      loadPrompt('shared', 'data_contract.md'),
      loadPrompt('shared', 'json_contract.md'),
      loadPrompt('graph', 'repair_planning.md'),
    ),
    userPrompt: [
      `Pregunta:\n${question}`,
      `Pregunta limpia:\n${compactJson(cleanedQuestion)}`,
      `Contexto:\n${buildWorkerContextBrief(snapshot)}`,
      `Intención:\n${compactJson(intent)}`,
      `Selección de fuente:\n${compactJson(sourceSelection)}`,
      `Plan previo:\n${compactJson(previousPlan)}`,
      `Ejecución previa:\n${compactJson(execution)}`,
      `Problemas detectados:\n${compactJson(validation)}`,
    ].join('\n\n'),
    parse: (value) => parsePlan(value, cleanedQuestion.cleanedQuestion, snapshot, intent, sourceSelection),
  });
}
