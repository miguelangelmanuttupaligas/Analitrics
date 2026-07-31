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
  return callJsonWorker(
    [
      'Eres el worker de planificación de Analitrics.',
      'Construye un plan ejecutable para responder la pregunta usando solo la evidencia disponible.',
      'Usa exactamente estos enums:',
      '- responseMode: texto | tabla | grafico | aclaracion',
      '- dataSource: archivo | corporativo | combinado | ninguno',
      '- chartType: barras | lineas | torta | tabla | ninguno',
      '- orientation: horizontal | vertical | ninguna',
      'Las únicas estrategias válidas de fuente son: solo archivo, solo dato corporativo, o combinado.',
      'Respeta el modo seleccionado por sourceSelection salvo que necesites escalar a aclaración.',
      'Si no existe suficiente contexto, devuelve responseMode=aclaracion.',
      'Si la pregunta requiere archivo y hay adjuntos recientes pero no activos seleccionados, usa ensureImport=true.',
      'Si el usuario pide tabla, usa responseMode=tabla y chartType=tabla.',
      'Si el usuario pide grafico, usa responseMode=grafico y define chartType adecuado.',
      'Si la pregunta limpia o ambiguityNotes muestran que falta el criterio de priorización, prefiere aclaración útil antes que asumir una métrica específica.',
      'No conviertas "más relevantes", "algo importante", "vista ejecutiva" o lenguaje similar en "mayor monto", "más ventas" u otra métrica salvo que el usuario lo haya pedido de forma explícita.',
      'Para preguntas descriptivas sobre el archivo, prefiere useContextSummary=true y evita SQL innecesario.',
      'Para preguntas combinadas archivo + corporativo, usa dataSource=combinado solo si puedes explicar o ejecutar una relación defendible entre ambos contextos; si no, aclara.',
      'Para preguntas corporativas de inventario o disponibilidad, evita SQL si el snapshot ya expone tablas corporativas suficientes.',
      'Si generas gráfico, elige dimensiones que existan de forma explícita y una orientación coherente con la cardinalidad estimada.',
      'Si generas SQL, usa solo tablas y columnas explícitas del contexto disponible.',
      'Puedes elegir entre varios activos tabulares seleccionados; si la pregunta mezcla varios archivos, decide si conviene combinarlos o pedir precisión mínima.',
      'No inventes tablas como ventas ni dimensiones inexistentes.',
      'Si no hay tablas corporativas disponibles, no finjas comparación corporativa.',
      'Devuelve solo JSON.',
    ].join('\n'),
    [
      `Pregunta limpia:\n${compactJson(cleanedQuestion)}`,
      `Intención:\n${compactJson(intent)}`,
      `Selección de fuente:\n${compactJson(sourceSelection)}`,
      `Guía operativa:\n${buildPlanningGuidance(snapshot, intent, sourceSelection)}`,
      `Contexto:\n${buildWorkerContextBrief(snapshot)}`,
    ].join('\n\n'),
    (value) => parsePlan(value, cleanedQuestion.cleanedQuestion, snapshot, intent, sourceSelection),
  );
}

export async function runPlanReconciliationWorker(params: {
  cleanedQuestion: CleanedQuestion;
  snapshot: ContextSnapshot;
  intent: AnalyticsIntent;
  sourceSelection: AnalyticsSourceSelection;
  proposedPlan: AnalyticsPlan;
}): Promise<AnalyticsPlan> {
  const { cleanedQuestion, snapshot, intent, sourceSelection, proposedPlan } = params;
  return callJsonWorker(
    [
      'Eres el worker de reconciliación de plan de Analitrics.',
      'Tu trabajo es revisar un plan propuesto y devolver un plan final más coherente con el contexto disponible.',
      'No respondas la pregunta del usuario.',
      'Mantén exactamente los enums de contrato:',
      '- responseMode: texto | tabla | grafico | aclaracion',
      '- dataSource: archivo | corporativo | combinado | ninguno',
      '- chartType: barras | lineas | torta | tabla | ninguno',
      '- orientation: horizontal | vertical | ninguna',
      'No inventes tablas, columnas ni joins.',
      'Reduce sobreinterpretaciones del planner.',
      'Si el plan convirtió una petición abierta o ambigua en una métrica específica no pedida por el usuario, corrígelo.',
      'Si ambiguityNotes indica que falta un criterio de priorización, no dejes pasar SQL que imponga un criterio arbitrario.',
      'Si existe un activo tabular seleccionado, evita pedir un archivo que ya está disponible.',
      'Si el plan pide tabla o gráfico, asegúrate de que tenga SQL ejecutable o cambia a aclaración justificada.',
      'Si el plan depende de archivo y hay adjunto reciente no importado, puedes usar ensureImport=true.',
      'Si el plan marcó dataSource=combinado pero no existe una relación defendible entre archivo y corporativo, cambia a aclaración o a una respuesta descriptiva más honesta.',
      'Respeta la selección explícita de fuente: archivo, corporativo o combinado.',
      'Si el contexto real no permite contestar, devuelve responseMode=aclaracion con una pregunta concreta.',
      'Devuelve solo JSON con el plan final.',
    ].join('\n'),
    [
      `Pregunta limpia:\n${compactJson(cleanedQuestion)}`,
      `Intención:\n${compactJson(intent)}`,
      `Selección de fuente:\n${compactJson(sourceSelection)}`,
      `Guía operativa:\n${buildPlanningGuidance(snapshot, intent, sourceSelection)}`,
      `Contexto:\n${buildWorkerContextBrief(snapshot)}`,
      `Plan propuesto:\n${compactJson(proposedPlan)}`,
    ].join('\n\n'),
    (value) => parsePlan(value, cleanedQuestion.cleanedQuestion, snapshot, intent, sourceSelection),
  );
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

  return callJsonWorker(
    [
      'Eres el worker de seguridad SQL de Analitrics.',
      'No respondas la pregunta del usuario.',
      'Tu trabajo es revisar el SQL propuesto para asegurar que sea de solo lectura y coherente con el contexto.',
      'Solo se permiten consultas SELECT o WITH de lectura.',
      'No permitas INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, CREATE, GRANT, REVOKE, COMMENT ni COPY.',
      'No inventes tablas ni columnas fuera del contexto disponible.',
      'Si el SQL es reparable, devuelve sanitizedSql corregido.',
      'Si no es seguro o no puede repararse con el contexto, marca shouldClarify=true y formula una aclaración concreta.',
      'Devuelve solo JSON con approved, sanitizedSql, rationale, shouldClarify, clarificationQuestion.',
    ].join('\n'),
    [
      `Pregunta:\n${question}`,
      `Contexto:\n${buildWorkerContextBrief(snapshot)}`,
      `Plan:\n${compactJson(plan)}`,
    ].join('\n\n'),
    (value) => parseSqlSafety(value),
  );
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
  return callJsonWorker(
    [
      'Eres el worker de reparación de plan de Analitrics.',
      'Debes corregir un plan previo que produjo problemas detectados por validación.',
      'Mantén exactamente los enums de contrato:',
      '- responseMode: texto | tabla | grafico | aclaracion',
      '- dataSource: archivo | corporativo | combinado | ninguno',
      '- chartType: barras | lineas | torta | tabla | ninguno',
      '- orientation: horizontal | vertical | ninguna',
      'Corrige especialmente pérdida de contexto, inventos de columnas o tablas, selección errónea de modo de salida y mala elección entre archivo/corporativo/combinado.',
      'Si la reparación no es posible con la evidencia disponible, devuelve responseMode=aclaracion.',
      'No inventes datos.',
      'Devuelve solo JSON.',
    ].join('\n'),
    [
      `Pregunta:\n${question}`,
      `Pregunta limpia:\n${compactJson(cleanedQuestion)}`,
      `Contexto:\n${buildWorkerContextBrief(snapshot)}`,
      `Intención:\n${compactJson(intent)}`,
      `Selección de fuente:\n${compactJson(sourceSelection)}`,
      `Plan previo:\n${compactJson(previousPlan)}`,
      `Ejecución previa:\n${compactJson(execution)}`,
      `Problemas detectados:\n${compactJson(validation)}`,
    ].join('\n\n'),
    (value) => parsePlan(value, cleanedQuestion.cleanedQuestion, snapshot, intent, sourceSelection),
  );
}
