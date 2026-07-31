import type { AnalyticsSourceSelection, CleanedQuestion, ContextSnapshot } from '../../types.js';
import { callJsonWorker } from '../llm.js';
import { buildWorkerContextBrief, compactJson, parseContextSelection, parseSourceSelection } from '../workerSupport.js';

export async function runContextSelectionWorker(
  question: string,
  snapshot: ContextSnapshot,
): Promise<{ selectedUploadIds: string[]; rationale: string }> {
  return callJsonWorker({
    workerName: 'context_selection_worker',
    systemPrompt: [
      'Eres el worker de selección de contexto de Analitrics.',
      'No respondas la pregunta del usuario.',
      'Debes elegir qué activos tabulares disponibles conviene mantener activos para esta consulta.',
      'Puedes seleccionar uno o varios uploadIds.',
      'Prioriza activos que coincidan con la pregunta, el nombre del archivo, sus resúmenes, sus columnas y sus tablas.',
      'Si la pregunta claramente trata del archivo ya activo, conserva ese activo salvo evidencia fuerte en contra.',
      'Si la pregunta no menciona archivo específico pero hay un único activo claramente relevante, selecciónalo.',
      'Si la pregunta es puramente corporativa y no necesita archivo, puedes devolver selectedUploadIds vacío.',
      'Si la pregunta parece requerir varios archivos, puedes seleccionar varios.',
      'Si no hay evidencia suficiente para distinguir, prioriza los más recientes.',
      'No selecciones varios archivos por defecto si uno solo cubre la consulta.',
      'No inventes uploadIds.',
      'Devuelve solo JSON con selectedUploadIds y rationale.',
    ].join('\n'),
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
    systemPrompt: [
      'Eres el worker de selección de fuente de Analitrics.',
      'No respondas la pregunta del usuario.',
      'Debes elegir exactamente uno de estos modos de trabajo:',
      '- archivo: responder solo con archivos/tablas cargadas',
      '- corporativo: responder solo con datos corporativos PostgreSQL',
      '- combinado: unir ambos contextos de forma defendible',
      '- ninguno: no existe base suficiente para responder',
      'Elige combinado solo si la pregunta realmente requiere ambos mundos o si existe una relación analítica razonable entre ellos.',
      'Si el usuario pregunta por el archivo cargado, prioriza archivo.',
      'Si el usuario pregunta por disponibilidad o inventario de datos corporativos, prioriza corporativo.',
      'Si falta una relación clara para combinar, puedes devolver needsClarification=true.',
      'No inventes joins ni correspondencias inexistentes entre archivo y corporativo.',
      'Devuelve solo JSON con mode, rationale, needsClarification y clarificationQuestion.',
    ].join('\n'),
    userPrompt: [
      `Pregunta limpia:\n${compactJson(cleanedQuestion)}`,
      `Contexto resumido:\n${buildWorkerContextBrief(snapshot)}`,
    ].join('\n\n'),
    parse: (value) => parseSourceSelection(value),
  });
}
