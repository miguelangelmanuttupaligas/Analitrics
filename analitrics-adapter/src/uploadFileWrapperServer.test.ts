import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import test from 'node:test';

const close = (server: ReturnType<typeof createServer>) =>
  new Promise<void>((resolve, reject) => server.close((error) => (error ? reject(error) : resolve())));

test('forwards JSON deletion bodies and rebuilds multipart uploads safely', async () => {
  const received: Array<{ contentType: string; body: string }> = [];
  const upstream = createServer((request, response) => {
    let body = '';
    request.setEncoding('utf8');
    request.on('data', (chunk) => {
      body += chunk;
    });
    request.on('end', () => {
      received.push({
        contentType: String(request.headers['content-type'] || ''),
        body,
      });
      response.writeHead(200, { 'content-type': 'application/json' });
      response.end(JSON.stringify({ ok: true }));
    });
  });
  const upstreamPort = await new Promise<number>((resolve) => {
    upstream.listen(0, '127.0.0.1', () => {
      const address = upstream.address();
      if (!address || typeof address === 'string') {
        throw new Error('Test server did not expose a TCP port');
      }
      resolve(address.port);
    });
  });

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
    const deletion = { files: [{ file_id: '89557f33-d3ba-4cc1-9661-1e0a306669e7', filepath: 's3://file' }] };
    const deleteResponse = await fetch(`http://127.0.0.1:${wrapperPort}/api/files`, {
      method: 'DELETE',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(deletion),
    });
    assert.equal(deleteResponse.status, 200);

    const upload = new FormData();
    upload.append('tool_resource', 'context');
    upload.append('message_file', 'true');
    upload.append(
      'file',
      new Blob(['course,amount\nAnalitica,100\n'], {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      }),
      'baseline.xlsx',
    );
    const uploadResponse = await fetch(`http://127.0.0.1:${wrapperPort}/api/files`, {
      method: 'POST',
      body: upload,
    });
    assert.equal(uploadResponse.status, 200);
    assert.equal(received.length, 2);

    assert.match(received[0].contentType, /^application\/json/);
    assert.deepEqual(JSON.parse(received[0].body), deletion);

    const multipart = received[1];
    const boundary = multipart.contentType.match(/boundary=([^;]+)/i)?.[1];
    assert.ok(boundary, 'upstream request must have a multipart boundary');
    assert.ok(multipart.body.includes(`--${boundary}`), 'body must use the forwarded boundary');
    assert.match(multipart.body, /analitrics_storage_policy/);
  } finally {
    await close(wrapperServer);
    await close(upstream);
  }
});
