import { pg } from '../db.js';
import { importAttachmentIntoPostgres } from './ingestion.js';
import { listRecentTabularAttachments } from './librechatFiles.js';

const processedAttachmentIds = new Set<string>();

export async function syncRecentTabularAttachments(limit = 25): Promise<number> {
  const attachments = await listRecentTabularAttachments(limit);
  let imported = 0;

  for (const attachment of attachments) {
    if (processedAttachmentIds.has(attachment.fileId)) {
      continue;
    }

    const existing = await pg.query<{ upload_id: string }>(
      `
        select upload_id
        from analitrics_meta.conversation_file_contexts
        where user_id = $1
          and conversation_id = $2
          and source_file_id = $3
        limit 1
      `,
      [attachment.userId, attachment.conversationId, attachment.fileId],
    );

    if (existing.rowCount) {
      processedAttachmentIds.add(attachment.fileId);
      continue;
    }

    try {
      await importAttachmentIntoPostgres(attachment);
      processedAttachmentIds.add(attachment.fileId);
      imported += 1;
    } catch (error) {
      console.error('Auto import failed', {
        filename: attachment.filename,
        fileId: attachment.fileId,
        conversationId: attachment.conversationId,
        error: error instanceof Error ? error.message : String(error),
      });
    }
  }

  return imported;
}
