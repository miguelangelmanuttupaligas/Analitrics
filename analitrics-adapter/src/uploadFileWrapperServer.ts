import express from 'express';
import { Readable } from 'node:stream';

const config = {
  PORT: Number(process.env.PORT ?? 3096),
  LIBRECHAT_API_ORIGIN: process.env.LIBRECHAT_API_ORIGIN ?? 'http://api:3080',
  TABULAR_CONTEXT_TO_S3_ENABLED: process.env.TABULAR_CONTEXT_TO_S3_ENABLED !== 'false',
  MAX_FILE_BYTES: Number(process.env.ANALITRICS_MAX_FILE_BYTES ?? 25 * 1024 * 1024),
};

const TABULAR_EXTENSIONS = new Set([
  '.csv',
  '.xls',
  '.xlsx',
  '.ods',
  // Extend here as Analitrics accepts more tabular formats, e.g. '.tsv'.
]);
const TABULAR_MIME_TYPES = new Set([
  'text/csv',
  'application/csv',
  'application/vnd.ms-excel',
  'application/msexcel',
  'application/x-msexcel',
  'application/x-ms-excel',
  'application/x-excel',
  'application/x-dos_ms_excel',
  'application/xls',
  'application/x-xls',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'application/vnd.oasis.opendocument.spreadsheet',
  // Extend here as Analitrics accepts more tabular MIME types.
]);

type RequestInitWithDuplex = RequestInit & { duplex: 'half' };

function isTabularFile(file: File): boolean {
  const lowerName = file.name.toLowerCase();
  const extension = lowerName.includes('.') ? lowerName.slice(lowerName.lastIndexOf('.')) : '';
  return TABULAR_MIME_TYPES.has(file.type) || TABULAR_EXTENSIONS.has(extension);
}

function shouldRewriteContext(formData: FormData): boolean {
  if (!config.TABULAR_CONTEXT_TO_S3_ENABLED) {
    return false;
  }

  const toolResource = formData.get('tool_resource');
  if (toolResource !== 'context') {
    return false;
  }

  const messageFile = formData.get('message_file');
  if (messageFile !== 'true') {
    return false;
  }

  for (const value of formData.values()) {
    if (value instanceof File && isTabularFile(value)) {
      return true;
    }
  }

  return false;
}

function buildForwardHeaders(req: express.Request): Headers {
  const headers = new Headers();
  const passthrough = [
    'accept',
    'authorization',
    'cookie',
    // DELETE /api/files carries JSON. Without this header LibreChat ignores
    // the body and returns a false-successful empty deletion.
    'content-type',
    'user-agent',
    'x-forwarded-for',
    'x-forwarded-host',
    'x-forwarded-port',
    'x-forwarded-proto',
    'x-real-ip',
    'x-tenant-id',
  ];

  for (const name of passthrough) {
    const value = req.header(name);
    if (value) {
      headers.set(name, value);
    }
  }

  return headers;
}

async function parseMultipart(req: express.Request): Promise<FormData> {
  const url = `${config.LIBRECHAT_API_ORIGIN}${req.originalUrl}`;
  const init = {
    method: req.method,
    headers: req.headers as HeadersInit,
    body: Readable.toWeb(req) as ReadableStream,
    duplex: 'half',
  } as RequestInitWithDuplex;
  const webRequest = new Request(url, init);

  return webRequest.formData();
}

function rewriteFormData(formData: FormData, rewriteContext: boolean): FormData {
  const next = new FormData();

  for (const [key, value] of formData.entries()) {
    if (rewriteContext && key === 'tool_resource' && value === 'context') {
      continue;
    }

    if (value instanceof File) {
      if (value.size > config.MAX_FILE_BYTES) {
        throw new Error(
          `El archivo ${value.name} pesa ${value.size} bytes y excede el limite permitido de ${config.MAX_FILE_BYTES} bytes`,
        );
      }
      next.append(key, value, value.name);
    } else {
      next.append(key, value);
    }
  }

  if (rewriteContext) {
    next.append('analitrics_storage_policy', 'tabular_original_s3');
  }

  return next;
}

async function proxyRaw(req: express.Request, res: express.Response): Promise<void> {
  const target = `${config.LIBRECHAT_API_ORIGIN}${req.originalUrl}`;
  const hasBody = !['GET', 'HEAD'].includes(req.method);
  const response = await fetch(target, {
    method: req.method,
    headers: buildForwardHeaders(req),
    body: hasBody ? (Readable.toWeb(req) as ReadableStream) : undefined,
    duplex: hasBody ? 'half' : undefined,
  } as RequestInitWithDuplex);

  await relayResponse(response, res);
}

async function relayResponse(response: Response, res: express.Response): Promise<void> {
  res.status(response.status);

  const contentType = response.headers.get('content-type');
  if (contentType) {
    res.setHeader('content-type', contentType);
  }

  const body = Buffer.from(await response.arrayBuffer());
  res.send(body);
}

async function proxyUpload(req: express.Request, res: express.Response): Promise<void> {
  const formData = await parseMultipart(req);
  const rewriteContext = shouldRewriteContext(formData);
  const body = rewriteFormData(formData, rewriteContext);

  const response = await fetch(`${config.LIBRECHAT_API_ORIGIN}${req.originalUrl}`, {
    method: req.method,
    headers: buildForwardHeaders(req),
    body,
  });

  await relayResponse(response, res);
}

async function main(): Promise<void> {
  const app = express();

  app.get('/health', (_req, res) => {
    res.json({ ok: true, service: 'analitrics-upload-file-wrapper' });
  });

  app.all('/api/files', async (req, res) => {
    try {
      const contentType = req.header('content-type') ?? '';
      if (req.method === 'POST' && contentType.includes('multipart/form-data')) {
        await proxyUpload(req, res);
        return;
      }

      await proxyRaw(req, res);
    } catch (error) {
      console.error('Upload wrapper failed', error);
      res.status(502).json({
        error: error instanceof Error ? error.message : 'Upload wrapper failed',
      });
    }
  });

  app.listen(config.PORT, '0.0.0.0', () => {
    console.log(`Analitrics upload-file-wrapper listening on port ${config.PORT}`);
  });
}

void main().catch((error) => {
  console.error('Failed to start Analitrics upload-file-wrapper', error);
  process.exit(1);
});
