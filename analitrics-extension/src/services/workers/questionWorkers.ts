import type { AnalyticsIntent, CleanedQuestion, ContextSnapshot } from '../../types.js';
import { callJsonWorker } from '../llm.js';
import { buildWorkerContextBrief, parseCleanedQuestion, parseIntent } from '../workerSupport.js';

export async function runIntentWorker(question: string, snapshot: ContextSnapshot): Promise<AnalyticsIntent> {
  return callJsonWorker(
    [
      'Eres el worker de intención de Analitrics.',
      'Clasifica la intención del usuario sin responder la pregunta.',
      'Debes decidir formato de salida, necesidad de aclaración y fuente de datos más natural.',
      'Usa exactamente estos enums:',
      '- intent: resumen | hallazgos | calidad | conteo | columnas | tabla | grafico | comparacion | pregunta_gerencial | ambigua | otro',
      '- outputMode: texto | tabla | grafico | aclaracion',
      '- dataScope: archivo | corporativo | combinado | indefinido',
      '- chartType: barras | lineas | torta | tabla | ninguno',
      '- orientation: horizontal | vertical | ninguna',
      'Las únicas estrategias válidas de fuente son: solo archivo, solo dato corporativo, o combinado.',
      'Si el usuario pide tabla, la salida debe ser tabla.',
      'Si el usuario pide gráfico o visual, la salida debe ser grafico.',
      'Si el usuario pregunta sobre un archivo, y hay activos tabulares seleccionados o adjuntos recientes, prioriza archivo.',
      'Si el usuario alude a varios archivos o comparación entre cargas, considera dataScope=combinado o archivo según la evidencia visible.',
      'No inventes dimensiones ni tablas.',
      'Devuelve solo JSON.',
    ].join('\n'),
    `Pregunta del usuario:\n${question}\n\nContexto disponible:\n${buildWorkerContextBrief(snapshot)}`,
    (value) => parseIntent(value, question),
  );
}

export async function runQuestionCleanupWorker(
  question: string,
  snapshot: ContextSnapshot,
): Promise<CleanedQuestion> {
  return callJsonWorker(
    [
      'Eres el worker de limpieza de intención de Analitrics.',
      'No respondas la pregunta.',
      'Reescribe la petición en una forma limpia, directa y útil para análisis, preservando exactamente la intención del usuario.',
      'Usa exactamente estos enums para requestedOutput: texto | tabla | grafico | aclaracion.',
      'Usa exactamente estos enums para businessTone: ejecutivo | analitico | operativo | neutro.',
      'No cambies el criterio de negocio del usuario.',
      'No sustituyas términos vagos por métricas concretas salvo que el usuario ya las haya pedido.',
      'Ejemplo: "registros más relevantes" no significa automáticamente "mayor monto".',
      'Si la petición implica ranking, prioridad o selección pero no define el criterio, debes registrarlo en ambiguityNotes.',
      'Ejemplos de ambigüedad que deben quedar explícitos en ambiguityNotes: "más relevantes", "más importantes", "top", "mejores", "hazme un análisis", "vista ejecutiva", "muéstrame algo importante".',
      'Cuando exista esa ambigüedad, conserva la intención del usuario sin resolverla por tu cuenta.',
      'Si la pregunta es corta o ambigua, mantenla fiel y señala la ambigüedad en ambiguityNotes en vez de sobreespecificarla.',
      'Preserva la intención del usuario, pero elimina ambigüedad innecesaria, muletillas y ruido.',
      'No inventes columnas, tablas ni dimensiones.',
      'Si el usuario pidió tabla o gráfico, consérvalo en requestedOutput.',
      'Devuelve solo JSON.',
    ].join('\n'),
    `Pregunta original:\n${question}\n\nContexto disponible:\n${buildWorkerContextBrief(snapshot)}`,
    (value) => parseCleanedQuestion(value, question),
  );
}
