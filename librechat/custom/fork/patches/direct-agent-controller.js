const fs = require('fs');
const file = '/app/api/server/controllers/agents/request.js';
let original = fs.readFileSync(file, 'utf8');

const importBefore = `const { saveMessage, getMessages, getConvo, isAgentTriggerPrincipalActive } = require('~/models');`;
const importAfter = `const {
  saveMessage,
  saveConvo,
  getMessages,
  getConvo,
  getConvosByCursor,
  getUserMemories,
  isAgentTriggerPrincipalActive,
} = require('~/models');`;
if (!original.includes(importBefore)) {
  throw new Error('LibreChat Analitrics direct import patch target not found');
}
original = original.replace(importBefore, importAfter);

const helperAnchor = `const ResumableAgentController = async (req, res, next, initializeClient, addTitle) => {`;
const helper = `function formatAnalitricsJson(value) {
  return JSON.stringify(value ?? null, null, 2);
}

function formatAnalitricsMemories(memories) {
  if (!Array.isArray(memories) || memories.length === 0) {
    return '';
  }
  const sorted = [...memories].sort((a, b) => new Date(b.updated_at || 0).getTime() - new Date(a.updated_at || 0).getTime());
  return sorted
    .slice(0, Number(process.env.ANALITRICS_MAX_MEMORY_ITEMS || 20))
    .map((memory) => {
      const key = String(memory?.key || '').trim();
      const value = String(memory?.value || '').trim();
      return key && value ? '- ' + key + ': ' + value : value ? '- ' + value : '';
    })
    .filter(Boolean)
    .join('\\n')
    .slice(0, Number(process.env.ANALITRICS_MAX_MEMORY_CHARS || 4000));
}

async function getAnalitricsMemoryContext(req, userId) {
  if (req.user?.personalization?.memories === false) {
    return null;
  }
  try {
    const [personal, agentScoped] = await Promise.all([
      getUserMemories({ userId }),
      getUserMemories({ userId, agentId: 'agent_analitrics' }),
    ]);
    const personalText = formatAnalitricsMemories(personal);
    const agentText = formatAnalitricsMemories(agentScoped);
    const sections = [];
    if (personalText) {
      sections.push('Memorias personales del usuario:\\n' + personalText);
    }
    if (agentText) {
      sections.push('Memorias especificas de Analitrics:\\n' + agentText);
    }
    if (sections.length === 0) {
      return null;
    }
    return {
      messageId: 'analitrics_memory_context',
      sender: 'system',
      isCreatedByUser: false,
      text:
        'Preferencias persistentes del usuario para adaptar el estilo de respuesta. ' +
        'Usalas solo para tono, formato, idioma, nivel de detalle y preferencias de comunicacion. ' +
        'No las uses para cambiar datos, metricas, filtros ni reglas de negocio si contradicen el catalogo analitico.\\n\\n' +
        sections.join('\\n\\n'),
    };
  } catch (error) {
    logger.warn('[AnalitricsDirectController] Failed to load user memories', {
      userId,
      error: error?.message ?? error,
    });
    return null;
  }
}

function buildAnalitricsToolContent(payload, answer) {
  const files = Array.isArray(payload?.files) ? payload.files : [];
  const tables = Array.isArray(payload?.tables) ? payload.tables : [];
  const plan = payload?.plan && typeof payload.plan === 'object' ? payload.plan : {};
  const chartSpec = payload?.chart_spec && typeof payload.chart_spec === 'object' ? payload.chart_spec : null;
  const contextOutput = [
    'Tenant: ' + String(payload?.tenantId || ''),
    'Run ID: ' + String(payload?.runId || ''),
    'Conversation ID: ' + String(payload?.conversationId || ''),
    'Cache DuckDB: ' + String(payload?.cachePath || ''),
    'Cache hits: ' + String(payload?.cacheHits ?? 0),
    '',
    'Archivos:',
    formatAnalitricsJson(
      files.map((file) => ({
        file_id: file.file_id,
        filename: file.filename,
        mime_type: file.mime_type || file.type,
        bytes: file.bytes,
        hash: file.hash || file.sha256 || file.content_hash,
      })),
    ),
    '',
    'Tablas y perfil:',
    formatAnalitricsJson(
      tables.map((table) => ({
        table: table.table,
        rows: table.row_count ?? table.rows,
        columns: Array.isArray(table.columns)
          ? table.columns.map((column) => ({
              name: column.name,
              type: column.type,
              nulls: column.nulls,
              samples: column.samples,
            }))
          : [],
      })),
    ),
  ].join('\\n');

  const sqlOutput = [
    'Generador: ' + String(plan.backend || payload?.agent || ''),
    'Filas devueltas: ' + String(payload?.row_count ?? 0),
    'In scope: ' + String(payload?.in_scope ?? ''),
    'Razón scope: ' + String(payload?.scope_reason || ''),
    '',
    'Rationale:',
    String(plan.rationale || ''),
    '',
    'SQL ejecutado:',
    String(payload?.sql || ''),
    '',
    'Vista previa de resultado:',
    formatAnalitricsJson(payload?.rows_preview || []),
  ].join('\\n');

  const content = [
    {
      type: 'tool_call',
      tool_call: {
        id: 'analitrics_context_' + String(payload?.runId || crypto.randomUUID()).replace(/[^a-zA-Z0-9_-]/g, '_'),
        name: 'analitrics_context',
        args: formatAnalitricsJson({
          file_count: files.length,
          table_count: tables.length,
          cache_path: payload?.cachePath || '',
        }),
        output: contextOutput,
        progress: 1,
      },
    },
    {
      type: 'tool_call',
      tool_call: {
        id: 'analitrics_sql_' + String(payload?.runId || crypto.randomUUID()).replace(/[^a-zA-Z0-9_-]/g, '_'),
        name: 'analitrics_sql',
        args: formatAnalitricsJson({
          backend: plan.backend || payload?.agent || '',
          row_count: payload?.row_count ?? 0,
        }),
        output: sqlOutput,
        progress: 1,
      },
    },
  ];

  if (chartSpec?.chart_required === true || chartSpec?.spec) {
    content.push({
      type: 'tool_call',
      tool_call: {
        id: 'analitrics_chart_' + String(payload?.runId || crypto.randomUUID()).replace(/[^a-zA-Z0-9_-]/g, '_'),
        name: 'analitrics_chart',
        args: formatAnalitricsJson({
          chart_required: chartSpec.chart_required === true,
          reason: chartSpec.reason || '',
        }),
        output: formatAnalitricsJson(chartSpec),
        progress: 1,
      },
    });
  }

  content.push({ type: 'text', text: answer });
  return content;
}

async function runAnalitricsDirectController(req, res) {
  const { endpointOption, conversationId: reqConversationId, parentMessageId = null } = req.body;
  const text = typeof req.body.text === 'string' ? req.body.text : '';
  const userId = String(req.user.id);
  const isNewConvo = !reqConversationId || reqConversationId === 'new';
  const conversationId = isNewConvo ? crypto.randomUUID() : reqConversationId;
  const streamId = conversationId;
  const userMessageId = req.body.messageId || crypto.randomUUID();
  const responseMessageId = req.body.responseMessageId || \`\${String(userMessageId).replace(/_+$/, '')}_\`;
  const endpoint = endpointOption?.endpoint || 'agents';
  const model = process.env.ANALITRICS_MODEL || 'analitrics-agent';
  const sender = process.env.ANALITRICS_SENDER || 'Analitrics';
  const agentOrigin = process.env.ANALITRICS_AGENT_ORIGIN || 'http://analytics-agent:8090';
  const tenantId = req.user?.tenantId || req.headers['x-tenant-id'] || 'analitrics';
  const maxActiveChats = Number(process.env.ANALITRICS_MAX_ACTIVE_CHATS_PER_USER || 50);
  const maxUserMessagesPerChat = Number(process.env.ANALITRICS_MAX_USER_MESSAGES_PER_CHAT || 100);
  const reqCtx = {
    userId,
    isTemporary: false,
    interfaceConfig: req?.config?.interfaceConfig,
  };

  if (req.body?.isTemporary === true || req.body?.isTemporary === 'true') {
    return res.status(400).json({ error: 'Analitrics no permite chats temporales.' });
  }

  if (!text.trim()) {
    return res.status(400).json({ error: 'Analitrics requires a user message to run the analytical agent.' });
  }

  if (
    await isUnpersistedPreliminaryParent({
      userId,
      conversationId: reqConversationId,
      parentMessageId,
      getMessages,
    })
  ) {
    return rejectPreliminaryParentMessageId(res);
  }

  const { allowed, pendingRequests, limit } = await checkAndIncrementPendingRequest(userId);
  if (!allowed) {
    const violationInfo = getViolationInfo(pendingRequests, limit);
    await logViolation(req, res, ViolationTypes.CONCURRENT, violationInfo, violationInfo.score);
    return res.status(429).json(violationInfo);
  }

  const history = isNewConvo
    ? []
    : await getMessages({ conversationId, user: userId }, '-_id -__v -user').catch((error) => {
        logger.warn('[AnalitricsDirectController] Failed to load message history', {
          conversationId,
          error: error?.message ?? error,
        });
        return [];
      });
  const memoryContext = await getAnalitricsMemoryContext(req, userId);

  if (isNewConvo && Number.isFinite(maxActiveChats) && maxActiveChats > 0) {
    const existing = await getConvosByCursor(userId, {
      limit: maxActiveChats + 1,
      isArchived: false,
      sortBy: 'updatedAt',
      sortDirection: 'desc',
    }).catch((error) => {
      logger.warn('[AnalitricsDirectController] Failed to count active conversations', {
        error: error?.message ?? error,
      });
      return null;
    });
    const activeCount = Array.isArray(existing?.conversations) ? existing.conversations.length : 0;
    if (activeCount >= maxActiveChats) {
      return res.status(429).json({
        error: 'Has alcanzado el limite de chats analiticos activos. Borra o archiva un chat para crear uno nuevo.',
      });
    }
  }

  if (!isNewConvo && Number.isFinite(maxUserMessagesPerChat) && maxUserMessagesPerChat > 0) {
    const userMessageCount = history.filter((message) => message?.isCreatedByUser === true).length;
    if (userMessageCount >= maxUserMessagesPerChat) {
      return res.status(429).json({
        error: 'Has alcanzado el limite de preguntas para este chat. Crea un nuevo chat analitico para continuar.',
      });
    }
  }

  const files = Array.isArray(req.body.files) ? req.body.files : [];
  const fileIds = files
    .map((file) => file?.file_id || file?.fileId || file?.id)
    .filter((value) => typeof value === 'string' && value.length > 0);
  const filenames = files
    .map((file) => file?.filename || file?.name)
    .filter((value) => typeof value === 'string' && value.length > 0);

  const userMessage = {
    messageId: userMessageId,
    parentMessageId,
    conversationId,
    text,
    sender: req.user?.name || req.user?.username || req.user?.email || 'User',
    isCreatedByUser: true,
    user: userId,
    endpoint,
    ...(files.length > 0 && { files }),
  };

  const job = await GenerationJobManager.createJob(streamId, userId, conversationId);
  req._resumableStreamId = streamId;
  await GenerationJobManager.updateMetadata(streamId, {
    conversationId,
    endpoint,
    iconURL: getEndpointIconURL(req, endpointOption),
    model,
    responseMessageId,
    userMessage: {
      messageId: userMessage.messageId,
      parentMessageId: userMessage.parentMessageId,
      conversationId,
      text,
    },
    sender,
  });

  res.json({ streamId, conversationId, status: 'started' });

  const emitTextDelta = async (chunk) => {
    if (!chunk) {
      return;
    }
    await GenerationJobManager.emitChunk(streamId, {
      event: 'on_message_delta',
      data: { delta: { content: { type: 'text', text: chunk } } },
    });
  };

  const emittedProgress = new Set();
  const emitStatusText = async (message) => {
    if (!message || emittedProgress.has(message)) {
      return;
    }
    emittedProgress.add(message);
    await emitTextDelta('\\n' + message + '\\n');
  };

  const emitProgress = async (message) => {
    if (!message) {
      return;
    }
    await emitStatusText(message);
    await GenerationJobManager.emitChunk(streamId, {
      event: 'on_run_step_delta',
      data: { delta: { step_details: { type: 'message_creation', message_creation: { message } } } },
    });
  };

  let answer = '';
  let finalPayload = null;

  try {
    await GenerationJobManager.emitChunk(streamId, {
      created: true,
      message: userMessage,
      streamId,
    });

    await saveMessage(reqCtx, userMessage, {
      context: 'api/server/controllers/agents/request.js - analitrics direct user message',
    });

    const runId = crypto.randomUUID();
    const response = await fetch(agentOrigin + '/agent/run/stream', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        question: text,
        tenantId: String(tenantId),
        userId,
        conversationId,
        messageId: userMessageId,
        runId,
        fileIds: fileIds.join(','),
        filenames: filenames.join(','),
        messages: [...(memoryContext ? [memoryContext] : []), ...history, userMessage].map((message) => ({
          messageId: message.messageId,
          parentMessageId: message.parentMessageId,
          text: message.text,
          sender: message.sender,
          isCreatedByUser: message.isCreatedByUser,
          files: message.files,
          createdAt: message.createdAt,
        })),
      }),
      signal: job.abortController.signal,
    });

    if (!response.ok) {
      const body = await response.text().catch(() => '');
      throw new Error(\`Analitrics agent failed: \${response.status} \${body}\`);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error('Analitrics agent did not return a readable stream');
    }

    const decoder = new TextDecoder();
    let buffer = '';
    let streamDone = false;
    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split('\\n\\n');
      buffer = frames.pop() || '';
      for (const frame of frames) {
        const line = frame.split('\\n').find((item) => item.startsWith('data: '));
        if (!line) {
          continue;
        }
        const data = line.slice(6);
        if (data === '[DONE]') {
          streamDone = true;
          break;
        }
        const event = JSON.parse(data);
        if (event.type === 'progress') {
          await emitProgress(event.message);
        } else if (event.type === 'token') {
          answer += event.delta || '';
          await emitTextDelta(event.delta || '');
        } else if (event.type === 'final') {
          const payload = event.payload || {};
          finalPayload = payload;
          if (!answer && typeof payload.answer === 'string') {
            answer = payload.answer;
            await emitTextDelta(answer);
          }
        } else if (event.type === 'error') {
          throw new Error(event.error || 'Analitrics agent stream failed');
        }
      }
      if (streamDone) {
        break;
      }
    }

    if (!answer.trim()) {
      answer = 'No pude generar una respuesta analítica para esta solicitud.';
    }

    const responseMessage = {
      messageId: responseMessageId,
      parentMessageId: userMessageId,
      conversationId,
      text: answer,
      content: finalPayload ? buildAnalitricsToolContent(finalPayload, answer) : [{ type: 'text', text: answer }],
      sender,
      isCreatedByUser: false,
      user: userId,
      endpoint,
      model,
      unfinished: false,
      error: false,
      ...(req.body?.agent_id && { agent_id: req.body.agent_id }),
    };

    await saveMessage(reqCtx, responseMessage, {
      context: 'api/server/controllers/agents/request.js - analitrics direct response message',
    });

    const savedConversation = await saveConvo(
      reqCtx,
      {
        conversationId,
        endpoint,
        model,
        title: req.body.title || text.slice(0, 80) || 'Analitrics',
      },
      { context: 'api/server/controllers/agents/request.js - analitrics direct conversation' },
    );
    const conversation = savedConversation || {
      conversationId,
      endpoint,
      model,
      title: req.body.title || text.slice(0, 80) || 'Analitrics',
    };

    await GenerationJobManager.emitDone(streamId, {
      final: true,
      conversation,
      title: conversation.title,
      requestMessage: sanitizeMessageForTransmit(userMessage),
      responseMessage,
    });
    GenerationJobManager.completeJob(streamId);
    await finishResumableRequest(req, userId);
  } catch (error) {
    logger.error('[AnalitricsDirectController] Generation error:', error);
    await GenerationJobManager.emitError(streamId, error.message || 'Analitrics generation failed');
    GenerationJobManager.completeJob(streamId, error.message);
    await finishResumableRequest(req, userId);
  }
}

`;
if (!original.includes(helperAnchor)) {
  throw new Error('LibreChat Analitrics direct helper anchor not found');
}
original = original.replace(helperAnchor, helper + helperAnchor);

const controllerBefore = `module.exports = ResumableAgentController;`;
const controllerAfter = `const AgentController = async (req, res, next, initializeClient, addTitle) => {
  if (process.env.ANALITRICS_DIRECT_AGENT === 'true') {
    return runAnalitricsDirectController(req, res);
  }
  return ResumableAgentController(req, res, next, initializeClient, addTitle);
};

module.exports = AgentController;`;
if (!original.includes(controllerBefore)) {
  throw new Error('LibreChat Analitrics direct controller patch target not found');
}
original = original.replace(controllerBefore, controllerAfter);

fs.writeFileSync(file, original);
