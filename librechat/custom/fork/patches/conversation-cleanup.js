const fs = require('fs');
const file = '/app/api/server/routes/convos.js';
let original = fs.readFileSync(file, 'utf8');

const helperAnchor = `const router = express.Router();
const archiveAllHandler = createArchiveAllHandler({ archiveAllConvos: db.archiveAllConvos });
router.use(requireJwtAuth);
`;
const helper = `const router = express.Router();
const archiveAllHandler = createArchiveAllHandler({ archiveAllConvos: db.archiveAllConvos });
router.use(requireJwtAuth);

async function deleteAnalitricsConversation(req, conversationId) {
  if (!conversationId) {
    return;
  }
  const agentOrigin = process.env.ANALITRICS_AGENT_ORIGIN || 'http://analytics-agent:8090';
  try {
    const response = await fetch(agentOrigin + '/agent/conversations/delete', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        tenantId: req.user?.tenantId || req.headers['x-tenant-id'] || 'analitrics',
        userId: String(req.user.id),
        conversationId,
      }),
    });
    if (!response.ok) {
      const body = await response.text().catch(() => '');
      logger.warn('Analitrics conversation cleanup failed for ' + conversationId + ': ' + response.status + ' ' + body);
    }
  } catch (error) {
    logger.warn('Analitrics conversation cleanup unavailable for ' + conversationId + ': ' + error.message);
  }
}
`;
if (!original.includes(helperAnchor)) {
  throw new Error('LibreChat convos helper anchor not found');
}
original = original.replace(helperAnchor, helper);

const before = `    // HITL: prune the deleted conversations' durable checkpoints — a paused run's
    // checkpoint would otherwise persist until the Mongo TTL. Never throws.
    await deleteAgentCheckpoints(
      deletedConversationIds,
      req.config?.endpoints?.[EModelEndpoint.agents]?.checkpointer,
    );`;
const after = `    await Promise.all(deletedConversationIds.map((id) => deleteAnalitricsConversation(req, id)));
    // HITL: prune the deleted conversations' durable checkpoints — a paused run's
    // checkpoint would otherwise persist until the Mongo TTL. Never throws.
    await deleteAgentCheckpoints(
      deletedConversationIds,
      req.config?.endpoints?.[EModelEndpoint.agents]?.checkpointer,
    );`;
if (!original.includes(before)) {
  throw new Error('LibreChat convos delete patch target not found');
}
fs.writeFileSync(file, original.replace(before, after));
