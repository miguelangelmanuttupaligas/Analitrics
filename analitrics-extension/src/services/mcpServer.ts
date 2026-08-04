import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';
import { buildChartResource } from './charts.js';
import {
  describeCurrentContext,
  findImportedContextsMentionedInQuestion,
  getCurrentContext,
  listActiveContexts,
  runSelectQuery,
} from './ingestion.js';
import { findLatestTabularAttachment, findRecentUserMessageForQuestion } from './librechatFiles.js';
import { importAttachmentIntoPostgres } from './ingestion.js';
import { answerWithDirectFileContext } from './directFileAnswer.js';

type RequestContext = {
  userId: string;
  conversationId?: string;
};

function formatRows(rows: Record<string, unknown>[]): string {
  return JSON.stringify(rows, null, 2);
}

type ResolvedAnalyticContext =
  | {
      ok: true;
      conversationId?: string;
      filename?: string;
      reason: string;
    }
  | {
      ok: false;
      message: string;
    };

async function resolveAnalyticContext(params: {
  baseContext: RequestContext;
  pregunta: string;
  filename?: string;
  conversationId?: string;
}): Promise<ResolvedAnalyticContext> {
  const explicitConversationId = params.conversationId ?? params.baseContext.conversationId;
  if (explicitConversationId) {
    return {
      ok: true,
      conversationId: explicitConversationId,
      filename: params.filename,
      reason: 'conversation_id_explicito',
    };
  }

  const recentMessage = await findRecentUserMessageForQuestion({
    userId: params.baseContext.userId,
    question: params.pregunta,
    filename: params.filename,
  });

  if (recentMessage?.attachments.length === 1) {
    const attachment = recentMessage.attachments[0];
    await importAttachmentIntoPostgres(attachment);
    return {
      ok: true,
      conversationId: recentMessage.conversationId,
      filename: attachment.filename,
      reason: 'mensaje_reciente_con_un_adjunto',
    };
  }

  if (recentMessage && recentMessage.attachments.length === 0) {
    const contexts = await listActiveContexts(params.baseContext.userId, recentMessage.conversationId);
    if (contexts.length === 1) {
      return {
        ok: true,
        conversationId: recentMessage.conversationId,
        filename: contexts[0].filename,
        reason: 'mensaje_reciente_sin_adjunto_con_contexto_activo',
      };
    }
  }

  if (recentMessage && recentMessage.attachments.length > 1 && !params.filename) {
    return {
      ok: false,
      message: `Encontré varios archivos adjuntos en el mensaje (${recentMessage.attachments
        .map((attachment) => attachment.filename)
        .join(', ')}). Indica cuál debo usar.`,
    };
  }

  if (params.filename) {
    const attachment = await findLatestTabularAttachment({
      userId: params.baseContext.userId,
      filename: params.filename,
    });
    if (attachment) {
      await importAttachmentIntoPostgres(attachment);
      return {
        ok: true,
        conversationId: attachment.conversationId,
        filename: attachment.filename,
        reason: 'filename_explicito_en_adjunto',
      };
    }

    const context = await getCurrentContext({
      userId: params.baseContext.userId,
      filename: params.filename,
    });
    if (context) {
      return {
        ok: true,
        conversationId: context.conversationId,
        filename: context.filename,
        reason: 'filename_explicito_importado',
      };
    }
  }

  const mentionedContexts = await findImportedContextsMentionedInQuestion({
    userId: params.baseContext.userId,
    question: params.pregunta,
  });

  if (mentionedContexts.length === 1) {
    return {
      ok: true,
      conversationId: mentionedContexts[0].conversationId,
      filename: mentionedContexts[0].filename,
      reason: 'filename_mencionado_en_pregunta',
    };
  }

  if (mentionedContexts.length > 1) {
    return {
      ok: false,
      message: `Encontré más de un archivo que coincide con tu pregunta (${mentionedContexts
        .map((context) => context.filename)
        .join(', ')}). Indica el nombre exacto del archivo.`,
    };
  }

  return {
    ok: false,
    message:
      'No puedo determinar qué archivo de este chat debo usar. Adjunta un CSV/XLSX en el mensaje o indica el nombre exacto del archivo.',
  };
}

async function ensureImportedContext(baseContext: RequestContext, filename?: string, conversationId?: string) {
  const current = await getCurrentContext({
    userId: baseContext.userId,
    conversationId,
    filename,
  });

  if (current) {
    return current;
  }

  const attachment = await findLatestTabularAttachment({
    userId: baseContext.userId,
    conversationId,
    filename,
  });

  if (!attachment) {
    return null;
  }

  return importAttachmentIntoPostgres(attachment);
}

export function createMcpServer(baseContext: RequestContext): McpServer {
  const server = new McpServer({
    name: 'analitrics-extension',
    version: '0.1.0',
  });

  server.registerTool(
    'orquestar_consulta_analitica',
    {
      title: 'Orquestar consulta analítica',
      description:
        'Tool principal de Analitrics para solicitudes de usuario sobre archivos CSV/XLSX cargados. Usa el flujo directo productivo: contexto de archivo, SQL en PostgreSQL, respuesta ejecutiva y recurso visual/tabular cuando corresponde.',
      inputSchema: {
        pregunta: z.string().min(1).describe('Pregunta original del usuario.'),
        filename: z.string().optional().describe('Nombre exacto del archivo si se desea sesgar el contexto.'),
        conversationId: z.string().optional().describe('ConversationId si se desea fijar el contexto.'),
      },
    },
    async ({ pregunta, filename, conversationId }) => {
      const resolvedContext = await resolveAnalyticContext({
        baseContext,
        pregunta,
        filename,
        conversationId,
      });

      if (!resolvedContext.ok) {
        return {
          content: [
            {
              type: 'text',
              text: resolvedContext.message,
            },
          ],
        };
      }

      const directAnswer = await answerWithDirectFileContext(baseContext, pregunta, {
        filename: resolvedContext.filename,
        conversationId: resolvedContext.conversationId,
      });

      if (directAnswer.handled) {
        const content: Array<
          | { type: 'text'; text: string }
          | { type: 'resource'; resource: { uri: string; mimeType: string; text: string; name: string } }
        > = [
          {
            type: 'text',
            text: directAnswer.answer ?? '',
          },
        ];

        if (directAnswer.resourceContent) {
          content.push(directAnswer.resourceContent);
        }

        return { content };
      }

      return {
        content: [
          {
            type: 'text',
            text:
              directAnswer.reason ??
              'No encontré un archivo CSV/XLSX activo para responder esta pregunta. Carga un archivo tabular y vuelve a intentarlo.',
          },
        ],
      };
    },
  );

  server.registerTool(
    'importar_archivo_actual',
    {
      title: 'Importar archivo actual',
      description:
        'Tool técnico de bajo nivel. Descubre el archivo tabular CSV/XLSX más reciente cargado por el usuario en LibreChat y lo persiste en PostgreSQL para memoria y consulta. Para solicitudes normales del usuario, prefiere orquestar_consulta_analitica.',
      inputSchema: {
        filename: z.string().optional().describe('Nombre exacto del archivo si desea forzarlo.'),
        conversationId: z.string().optional().describe('ConversationId de LibreChat si desea fijarlo.'),
      },
    },
    async ({ filename, conversationId }) => {
      const attachment = await findLatestTabularAttachment({
        userId: baseContext.userId,
        conversationId: conversationId ?? baseContext.conversationId,
        filename,
      });

      if (!attachment) {
        return {
          content: [
            {
              type: 'text',
              text: 'No encontré un archivo CSV/XLSX reciente para importar en este contexto.',
            },
          ],
        };
      }

      const imported = await importAttachmentIntoPostgres(attachment);
      return {
        content: [
          {
            type: 'text',
            text: [
              `Archivo importado: ${imported.filename}`,
              `Resumen técnico: ${imported.summary}`,
              `Resumen de negocio: ${imported.businessSummary}`,
              'Tablas creadas:',
              ...imported.tables.map(
                (table) =>
                  `- analitrics_uploads.${table.tableName} (${table.rowCount} filas, ${table.columnCount} columnas)`,
              ),
            ].join('\n'),
          },
        ],
      };
    },
  );

  server.registerTool(
    'describir_contexto_actual',
    {
      title: 'Describir contexto actual',
      description:
        'Tool técnico de bajo nivel. Describe el archivo tabular activo, su resumen semántico y las tablas PostgreSQL creadas para esta conversación. Para solicitudes normales del usuario, prefiere orquestar_consulta_analitica.',
      inputSchema: {
        filename: z.string().optional(),
        conversationId: z.string().optional(),
      },
    },
    async ({ filename, conversationId }) => {
      const context = await ensureImportedContext(
        baseContext,
        filename,
        conversationId ?? baseContext.conversationId,
      );

      if (!context) {
        return {
          content: [
            {
              type: 'text',
              text: 'No hay contexto tabular importado todavía para este usuario o conversación.',
            },
          ],
        };
      }

      const text = await describeCurrentContext({
        userId: baseContext.userId,
        conversationId: conversationId ?? baseContext.conversationId,
        filename,
      });
      return { content: [{ type: 'text', text }] };
    },
  );

  server.registerTool(
    'listar_contextos_tabulares',
    {
      title: 'Listar contextos tabulares',
      description:
        'Tool técnico de bajo nivel. Lista los archivos tabulares ya importados y disponibles para el usuario. Para solicitudes normales del usuario, prefiere orquestar_consulta_analitica.',
      inputSchema: {
        conversationId: z.string().optional(),
      },
    },
    async ({ conversationId }) => {
      let contexts = await listActiveContexts(
        baseContext.userId,
        conversationId ?? baseContext.conversationId,
      );
      if (!contexts.length) {
        const imported = await ensureImportedContext(
          baseContext,
          undefined,
          conversationId ?? baseContext.conversationId,
        );
        contexts = imported ? [imported] : [];
      }
      if (!contexts.length) {
        return {
          content: [{ type: 'text', text: 'No hay contextos tabulares importados todavía.' }],
        };
      }
      return {
        content: [
          {
            type: 'text',
            text: contexts
              .map(
                (context) =>
                  `${context.filename} -> ${context.tables
                    .map((table) => `analitrics_uploads.${table.tableName}`)
                    .join(', ')}`,
              )
              .join('\n'),
          },
        ],
      };
    },
  );

  server.registerTool(
    'consultar_sql_contexto',
    {
      title: 'Consultar SQL contexto',
      description:
        'Tool técnico de ejecución. Ejecuta una consulta SQL de solo lectura sobre PostgreSQL. Úsalo cuando ya exista un plan claro. Para solicitudes normales del usuario, prefiere orquestar_consulta_analitica.',
      inputSchema: {
        sql: z.string().min(1).describe('Consulta SQL de solo lectura.'),
      },
    },
    async ({ sql }) => {
      const result = await runSelectQuery(sql);
      return {
        content: [
          {
            type: 'text',
            text: `Filas devueltas: ${result.rowCount}\n${formatRows(result.rows)}`,
          },
        ],
      };
    },
  );

  server.registerTool(
    'generar_grafico_contexto',
    {
      title: 'Generar gráfico del contexto',
      description:
        'Tool técnico de ejecución. Genera un gráfico visual inline a partir de una consulta SQL de solo lectura sobre PostgreSQL. Para solicitudes normales del usuario, prefiere orquestar_consulta_analitica, que ya planifica cuándo usar este tool.',
      inputSchema: {
        sql: z.string().min(1).describe('Consulta SQL de solo lectura.'),
        tipo: z
          .enum(['barras', 'lineas', 'torta', 'tabla'])
          .describe('Tipo de visualización a generar.'),
        labelColumn: z
          .string()
          .optional()
          .describe('Nombre de la columna a usar como etiqueta o eje X. Si es posible, indícalo explícitamente.'),
        valueColumn: z
          .string()
          .optional()
          .describe('Nombre de la columna numérica a usar como métrica o eje Y. Si es posible, indícalo explícitamente.'),
        orientation: z
          .enum(['horizontal', 'vertical'])
          .optional()
          .describe('Orientación preferida para barras u otros gráficos que la soporten.'),
        xField: z
          .string()
          .optional()
          .describe('Campo a usar explícitamente en el eje X cuando quieras controlar el gráfico sin depender de inferencia.'),
        yField: z
          .string()
          .optional()
          .describe('Campo a usar explícitamente en el eje Y cuando quieras controlar el gráfico sin depender de inferencia.'),
        colorField: z
          .string()
          .optional()
          .describe('Campo categórico opcional para colorear series o categorías.'),
        topN: z
          .number()
          .int()
          .positive()
          .max(50)
          .optional()
          .describe('Número máximo de filas visibles en el gráfico.'),
        sort: z
          .enum(['ascending', 'descending', 'none'])
          .optional()
          .describe('Orden preferido para la dimensión principal.'),
        spec: z
          .any()
          .optional()
          .describe('Spec declarativo opcional estilo Vega-Lite parcial. No incluyas data; el servidor la inyecta.'),
        titulo: z
          .string()
          .optional()
          .describe('Título visible del gráfico o tabla.'),
      },
    },
    async ({ sql, tipo, titulo, labelColumn, valueColumn, orientation, xField, yField, colorField, topN, sort, spec }) => {
      const result = await runSelectQuery(sql);
      const resolvedTitle = titulo?.trim() || `Visual analítica (${tipo})`;
      const chart = await buildChartResource({
        title: resolvedTitle,
        chartType: tipo,
        rows: result.rows,
        labelColumn,
        valueColumn,
        overrides: {
          orientation,
          xField,
          yField,
          colorField,
          topN,
          sort,
          spec,
        },
      });

      return {
        content: [
          {
            type: 'text',
            text: `${chart.summary}\nFilas evaluadas: ${result.rowCount}.`,
          },
          chart.resource,
        ],
      };
    },
  );

  server.registerTool(
    'resumir_archivo_actual',
    {
      title: 'Resumir archivo actual',
      description:
        'Tool técnico de bajo nivel. Devuelve el resumen técnico y gerencial del archivo tabular activo ya importado. Para solicitudes normales del usuario, prefiere orquestar_consulta_analitica.',
      inputSchema: {
        filename: z.string().optional(),
        conversationId: z.string().optional(),
      },
    },
    async ({ filename, conversationId }) => {
      const context = await ensureImportedContext(
        baseContext,
        filename,
        conversationId ?? baseContext.conversationId,
      );
      if (!context) {
        return {
          content: [{ type: 'text', text: 'No hay un archivo tabular importado activo.' }],
        };
      }
      return {
        content: [
          {
            type: 'text',
            text: `Resumen técnico: ${context.summary}\nResumen gerencial: ${context.businessSummary}`,
          },
        ],
      };
    },
  );

  return server;
}
