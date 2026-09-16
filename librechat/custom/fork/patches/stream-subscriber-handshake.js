const fs = require('fs');

const file = process.env.LIBRECHAT_AGENT_STREAM_ROUTE_FILE || '/app/api/server/routes/agents/index.js';
let source = fs.readFileSync(file, 'utf8');

const anchor = `  if (attachmentAbortController.signal.aborted) {
    result?.unsubscribe();
    return;
  }
  if (!result) {`;
const replacement = `  if (attachmentAbortController.signal.aborted) {
    result?.unsubscribe();
    return;
  }

  // The direct Analitrics controller waits for this durable acknowledgement
  // before it begins a fast generation. Without it, a final response can be
  // produced before the browser has attached its resumable SSE connection.
  if (result && !res.writableEnded) {
    await GenerationJobManager.updateMetadata(
      streamId,
      { analitricsStreamSubscriberAttachedAt: Date.now() },
      authorizedGenerationCreatedAt,
    );
  }

  if (!result) {`;

if (!source.includes(replacement)) {
  if (!source.includes(anchor)) {
    throw new Error('LibreChat stream subscriber handshake patch anchor not found');
  }
  source = source.replace(anchor, replacement);
}

fs.writeFileSync(file, source);
