import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import test from 'node:test';

const listen = (server: ReturnType<typeof createServer>) =>
  new Promise<number>((resolve) => {
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      if (!address || typeof address === 'string') {
        throw new Error('Test server did not expose a TCP port');
      }
      resolve(address.port);
    });
  });

const close = (server: ReturnType<typeof createServer>) =>
  new Promise<void>((resolve, reject) => server.close((error) => (error ? reject(error) : resolve())));

test('forwards JSON file deletion bodies to LibreChat', async () => {
  let receivedContentType = '';
  let receivedBody = '';
  const upstream = createServer((request, response) => {
    receivedContentType = String(request.headers['content-type'] || '');
    request.setEncoding('utf8');
    request.on('data', (chunk) => {
      receivedBody += chunk;
    });
    request.on('end', () => {
      response.writeHead(200, { 'content-type': 'application/json' });
      response.end(JSON.stringify({ ok: true }));
    });
  });
  const upstreamPort = await listen(upstream);

  process.env.LIBRECHAT_API_ORIGIN = `http://127.0.0.1:${upstreamPort}`;
  process.env.NODE_ENV = 'test';
  const { createUploadFileWrapperApp } = await import('./uploadFileWrapperServer.js');
  const wrapper = createUploadFileWrapperApp();
  const wrapperServer = wrapper.listen(0, '127.0.0.1');
  const wrapperPort = await new Promise<number>((resolve) => {
    wrapperServer.on('listening', () => {
      const address = wrapperServer.address();
      if (!address || typeof address === 'string') {
        throw new Error('Wrapper test server did not expose a TCP port');
      }
      resolve(address.port);
    });
  });

  try {
    const payload = { files: [{ file_id: '89557f33-d3ba-4cc1-9661-1e0a306669e7', filepath: 's3://file' }] };
    const response = await fetch(`http://127.0.0.1:${wrapperPort}/api/files`, {
      method: 'DELETE',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(payload),
    });

    assert.equal(response.status, 200);
    assert.match(receivedContentType, /^application\/json/);
    assert.deepEqual(JSON.parse(receivedBody), payload);
  } finally {
    await close(wrapperServer);
    await close(upstream);
  }
});
