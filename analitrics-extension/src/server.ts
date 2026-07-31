import express from 'express';
import { createMcpExpressApp } from '@modelcontextprotocol/sdk/server/express.js';
import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { config } from './config.js';
import { closeConnections, initPostgres } from './db.js';
import { createMcpServer } from './services/mcpServer.js';
import { describeCurrentContext, listActiveContexts } from './services/ingestion.js';
import { findLatestTabularAttachment } from './services/librechatFiles.js';
import { importAttachmentIntoPostgres } from './services/ingestion.js';
import { syncRecentTabularAttachments } from './services/autoImport.js';

function getUserContext(req: express.Request): { userId: string; conversationId?: string } {
  const userIdHeader = req.header('x-librechat-user-id') ?? req.header(config.ALLOWED_USER_HEADER);
  if (!userIdHeader) {
    throw new Error('Falta el header de usuario LibreChat.');
  }
  return {
    userId: userIdHeader,
    conversationId: req.header('x-librechat-conversation-id') ?? undefined,
  };
}

async function main(): Promise<void> {
  await initPostgres();
  await syncRecentTabularAttachments();

  const app = createMcpExpressApp({ host: '0.0.0.0' });

  app.get('/health', (_req, res) => {
    res.json({ ok: true, service: 'analitrics-extension' });
  });

  app.post('/api/import-latest', async (req, res) => {
    try {
      const context = getUserContext(req);
      const attachment = await findLatestTabularAttachment({
        userId: context.userId,
        conversationId: req.body?.conversationId ?? context.conversationId,
        filename: req.body?.filename,
      });
      if (!attachment) {
        res.status(404).json({ error: 'No se encontró archivo tabular reciente.' });
        return;
      }
      const imported = await importAttachmentIntoPostgres(attachment);
      res.json(imported);
    } catch (error) {
      res.status(500).json({ error: error instanceof Error ? error.message : 'Error interno' });
    }
  });

  app.get('/api/context', async (req, res) => {
    try {
      const context = getUserContext(req);
      const description = await describeCurrentContext({
        userId: context.userId,
        conversationId:
          typeof req.query.conversationId === 'string'
            ? req.query.conversationId
            : context.conversationId,
        filename: typeof req.query.filename === 'string' ? req.query.filename : undefined,
      });
      res.json({ description });
    } catch (error) {
      res.status(500).json({ error: error instanceof Error ? error.message : 'Error interno' });
    }
  });

  app.get('/api/contexts', async (req, res) => {
    try {
      const context = getUserContext(req);
      const contexts = await listActiveContexts(
        context.userId,
        typeof req.query.conversationId === 'string'
          ? req.query.conversationId
          : context.conversationId,
      );
      res.json({ contexts });
    } catch (error) {
      res.status(500).json({ error: error instanceof Error ? error.message : 'Error interno' });
    }
  });

  app.post('/mcp', async (req, res) => {
    let server: McpServer | null = null;
    let transport: StreamableHTTPServerTransport | null = null;
    try {
      const context = getUserContext(req);
      server = createMcpServer(context);
      transport = new StreamableHTTPServerTransport({
        sessionIdGenerator: undefined,
      });
      await server.connect(transport);
      await transport.handleRequest(req, res, req.body);
      res.on('close', () => {
        void transport?.close();
        void server?.close();
      });
    } catch (error) {
      console.error('MCP request failed', error);
      if (!res.headersSent) {
        res.status(500).json({
          jsonrpc: '2.0',
          error: {
            code: -32603,
            message: error instanceof Error ? error.message : 'Internal server error',
          },
          id: null,
        });
      }
      await Promise.allSettled(
        [transport?.close(), server?.close()].filter(
          (promise): promise is Promise<void> => promise != null,
        ),
      );
    }
  });

  app.get('/mcp', (_req, res) => {
    res.status(405).json({
      jsonrpc: '2.0',
      error: {
        code: -32000,
        message: 'Method not allowed.',
      },
      id: null,
    });
  });

  const server = app.listen(config.PORT, '0.0.0.0', () => {
    console.log(`Analitrics extension listening on port ${config.PORT}`);
  });

  const autoImportTimer = setInterval(() => {
    void syncRecentTabularAttachments().then((count) => {
      if (count > 0) {
        console.log(`Auto import completed: ${count} archivo(s) tabulares sincronizados.`);
      }
    });
  }, 5000);
  autoImportTimer.unref();

  const shutdown = async () => {
    clearInterval(autoImportTimer);
    server.close();
    await closeConnections();
    process.exit(0);
  };

  process.on('SIGINT', () => {
    void shutdown();
  });
  process.on('SIGTERM', () => {
    void shutdown();
  });
}

void main().catch((error) => {
  console.error('Failed to start Analitrics extension', error);
  process.exit(1);
});
