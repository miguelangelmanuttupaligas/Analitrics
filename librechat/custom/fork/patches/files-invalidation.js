const fs = require('fs');
const file = '/app/api/server/routes/files/files.js';
let original = fs.readFileSync(file, 'utf8');
const helperAnchor = `const router = express.Router();
`;
const helper = `const router = express.Router();

async function invalidateAnalitricsFiles(req, files) {
  const tabularExtensions = new Set(['.csv', '.xls', '.xlsx', '.ods']);
  const tabularMimeTypes = new Set([
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
  ]);
  const agentOrigin = process.env.ANALITRICS_AGENT_ORIGIN || 'http://analytics-agent:8090';
  const candidates = (files || []).filter((file) => {
    const filename = String(file.filename || '').toLowerCase();
    const dot = filename.lastIndexOf('.');
    const extension = dot >= 0 ? filename.slice(dot) : '';
    return file.file_id && (tabularMimeTypes.has(file.type) || tabularMimeTypes.has(file.mimeType) || tabularExtensions.has(extension));
  });

  for (const file of candidates) {
    try {
      const response = await fetch(agentOrigin + '/agent/files/invalidate', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          tenantId: file.tenantId || req.user?.tenantId || 'analitrics',
          userId: String(file.user || req.user.id),
          fileId: file.file_id,
          reason: 'librechat_file_delete',
        }),
      });
      if (!response.ok) {
        const body = await response.text().catch(() => '');
        logger.warn('Analitrics file invalidation failed for ' + file.file_id + ': ' + response.status + ' ' + body);
      }
    } catch (error) {
      logger.warn('Analitrics file invalidation unavailable for ' + file.file_id + ': ' + error.message);
    }
  }
}
`;
if (!original.includes(helperAnchor)) {
  throw new Error('LibreChat file route helper anchor not found');
}
original = original.replace(helperAnchor, helper);
const replacements = [
  [
    `await processDeleteRequest({ req, files: ownedFiles });`,
    `await invalidateAnalitricsFiles(req, ownedFiles);
      await processDeleteRequest({ req, files: ownedFiles });`,
  ],
  [
    `await processDeleteRequest({ req, files: authorizedFiles });`,
    `await invalidateAnalitricsFiles(req, authorizedFiles);
    await processDeleteRequest({ req, files: authorizedFiles });`,
  ],
];
for (const [before, after] of replacements) {
  if (!original.includes(before)) {
    throw new Error('LibreChat file delete patch target not found: ' + before);
  }
  original = original.replace(before, after);
}
fs.writeFileSync(file, original);
