import type {
  AnalyticsExecution,
  AnalyticsIntent,
  AnalyticsPlan,
  AnalyticsValidation,
  CleanedQuestion,
  ContextSnapshot,
} from '../../types.js';
import { callJsonWorker, callTextWorker } from '../llm.js';
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
    systemPrompt: [
      'Eres el worker de validación de Analitrics.',
      'Evalúa si la respuesta borrador cumple la intención y si se apoya en la evidencia ejecutada.',
      'Marca como no aprobado si:',
      '- la respuesta pierde el contexto del archivo pese a existir,',
      '- se genera gráfico cuando el usuario pidió tabla,',
      '- se promete una tabla o gráfico pero no hay ejecución SQL ni recurso visual/tabular asociado,',
      '- se inventan dimensiones, tablas o conclusiones no sustentadas,',
      '- se afirma comparación corporativa cuando no hay tablas corporativas disponibles.',
      '- el plan introdujo un criterio de priorización, agregación o filtro que no aparece en la pregunta limpia y además ambiguityNotes sugiere que faltaba ese criterio.',
      'Devuelve solo JSON.',
    ].join('\n'),
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
    systemPrompt: [
      'Eres el worker de reconciliación de validación de Analitrics.',
      'Recibes una validación preliminar y debes ajustarla para que sea coherente con el contexto real.',
      'No inventes problemas inexistentes.',
      'Si existe un activo tabular ya disponible, no escales a una aclaración por falta de archivo.',
      'Si la validación detecta pérdida de contexto, puedes desaprobar y sugerir reparación del plan o de la respuesta.',
      'Si la pregunta limpia conserva ambigüedad explícita y el plan impuso un criterio no pedido, mantén la desaprobación.',
      'Devuelve solo JSON.',
    ].join('\n'),
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
    systemPrompt: [
      'Eres el worker de redacción de Analitrics.',
      'Redacta una respuesta final en español, directa y ejecutiva.',
      'Usa solo la evidencia entregada.',
      'No menciones workers, planificación, MCP ni detalles internos.',
      'Si habrá un recurso visual o tabular inline, termina la parte introductoria dejando espacio para que el asistente principal inserte el marcador UI provisto por la herramienta.',
      'Si faltó contexto, formula una aclaración corta y útil.',
      validationIssues.length
        ? `Corrige estos problemas detectados: ${validationIssues.join(' | ')}`
        : 'No hay problemas de validación previos.',
    ].join('\n'),
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
    systemPrompt: [
      'Eres el worker de limpieza de respuesta de Analitrics.',
      'Tu trabajo es mejorar claridad y tono sin cambiar el fondo.',
      'Reglas:',
      '- conserva el idioma español;',
      '- elimina relleno, disculpas innecesarias y repeticiones;',
      '- mantén un tono ejecutivo y claro;',
      '- no menciones herramientas internas;',
      '- si habrá recurso visual o tabla inline, deja intacto cualquier marcador \\ui{...};',
      '- si la respuesta es una aclaración, que sea corta y específica.',
    ].join('\n'),
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
    systemPrompt: [
      'Eres el worker de reconciliación de respuesta de Analitrics.',
      'Tu trabajo es corregir el borrador final si contradice el contexto real disponible.',
      'No inventes datos nuevos.',
      'Si ya existe un archivo activo en contexto, no pidas al usuario volver a cargarlo.',
      'Si hay evidencia suficiente, transforma aclaraciones innecesarias en una respuesta útil y breve.',
      'Si no hay evidencia suficiente, conserva o mejora la aclaración.',
      'Mantén el español y no menciones herramientas internas.',
    ].join('\n'),
    userPrompt: [
      `Pregunta:\n${question}`,
      `Contexto:\n${compactJson(snapshot)}`,
      `Plan:\n${compactJson(plan)}`,
      `Ejecución:\n${compactJson(execution)}`,
      `Borrador actual:\n${answerDraft}`,
    ].join('\n\n'),
  });
}
