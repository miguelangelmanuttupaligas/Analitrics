import path from 'path';
import { getMongoDb } from '../db.js';
import { config, tabularMimeTypes } from '../config.js';
import type { ConversationTurnSummary, DiscoveredAttachment, LibreChatMessage } from '../types.js';

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function compactText(value: string | undefined, maxLength = config.CONTEXT_MAX_MESSAGE_CHARS): string {
  const compact = (value ?? '').replace(/\s+/g, ' ').trim();
  return compact.length > maxLength ? `${compact.slice(0, maxLength - 1)}…` : compact;
}

function normalizeText(value: string | undefined): string {
  return (value ?? '')
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase();
}

function attachmentFromLibreChatFile(params: {
  userId: string;
  doc: Pick<LibreChatMessage, 'conversationId' | 'messageId'>;
  file: NonNullable<LibreChatMessage['files']>[number];
}): DiscoveredAttachment {
  const relative = params.file.filepath.replace(/^\/uploads\//, '');
  return {
    userId: params.userId,
    conversationId: params.doc.conversationId,
    messageId: params.doc.messageId,
    fileId: params.file.file_id,
    filename: params.file.filename,
    mimeType: params.file.type,
    filepath: params.file.filepath,
    absolutePath: path.join(config.LIBRECHAT_UPLOAD_ROOT, relative),
    bytes: params.file.bytes ?? 0,
  };
}

export async function listRecentTabularAttachments(limit = 25): Promise<DiscoveredAttachment[]> {
  const db = await getMongoDb();
  const messages = db.collection<LibreChatMessage>('messages');
  const docs = await messages
    .find(
      {
        isCreatedByUser: true,
        files: { $exists: true, $ne: [] },
      },
      {
        projection: {
          messageId: 1,
          conversationId: 1,
          createdAt: 1,
          files: 1,
        },
        sort: { createdAt: -1 },
        limit,
      },
    )
    .toArray();

  const attachments: DiscoveredAttachment[] = [];

  for (const doc of docs) {
    for (const file of doc.files ?? []) {
      if (!file.user || !tabularMimeTypes.has(file.type)) {
        continue;
      }

      attachments.push(attachmentFromLibreChatFile({ userId: String(file.user), doc, file }));
    }
  }

  return attachments;
}

export async function findLatestTabularAttachment(params: {
  userId: string;
  conversationId?: string;
  filename?: string;
}): Promise<DiscoveredAttachment | null> {
  for (let attempt = 0; attempt < 4; attempt += 1) {
    const attachment = await findLatestTabularAttachmentOnce(params);
    if (attachment) {
      return attachment;
    }
    if (attempt < 3) {
      await sleep(400);
    }
  }
  return null;
}

export async function listRecentTabularAttachmentsForUser(params: {
  userId: string;
  conversationId?: string;
  filename?: string;
  limit?: number;
}): Promise<DiscoveredAttachment[]> {
  const db = await getMongoDb();
  const messages = db.collection<LibreChatMessage>('messages');
  const query: Record<string, unknown> = {
    isCreatedByUser: true,
    files: { $exists: true, $ne: [] },
  };

  if (params.conversationId) {
    query.conversationId = params.conversationId;
  }

  const docs = await messages
    .find(query, {
      projection: {
        messageId: 1,
        conversationId: 1,
        createdAt: 1,
        files: 1,
      },
      sort: { createdAt: -1 },
      limit: Math.max(1, Math.min(params.limit ?? 12, 50)),
    })
    .toArray();

  const seen = new Set<string>();
  const attachments: DiscoveredAttachment[] = [];

  for (const doc of docs) {
    for (const file of doc.files ?? []) {
      const belongsToUser = !file.user || String(file.user) === params.userId;
      const matchesType = tabularMimeTypes.has(file.type);
      const matchesFilename = params.filename
        ? file.filename.toLowerCase() === params.filename.toLowerCase()
        : true;

      if (!belongsToUser || !matchesType || !matchesFilename || seen.has(file.file_id)) {
        continue;
      }

      attachments.push(attachmentFromLibreChatFile({ userId: params.userId, doc, file }));
      seen.add(file.file_id);
    }
  }

  return attachments;
}

export async function findRecentUserMessageForQuestion(params: {
  userId: string;
  question: string;
  filename?: string;
  limit?: number;
}): Promise<{
  conversationId: string;
  messageId: string;
  text: string;
  attachments: DiscoveredAttachment[];
} | null> {
  const db = await getMongoDb();
  const messages = db.collection<LibreChatMessage>('messages');
  const normalizedQuestion = normalizeText(params.question);
  const docs = await messages
    .find(
      {
        isCreatedByUser: true,
        $or: [{ user: params.userId }, { 'files.user': params.userId }],
      },
      {
        projection: {
          messageId: 1,
          conversationId: 1,
          createdAt: 1,
          text: 1,
          files: 1,
        },
        sort: { createdAt: -1 },
        limit: Math.max(1, Math.min(params.limit ?? 20, 50)),
      },
    )
    .toArray();

  for (const doc of docs) {
    const normalizedText = normalizeText(doc.text);
    const textMatches =
      normalizedText.length > 0 &&
      (normalizedText === normalizedQuestion ||
        normalizedText.includes(normalizedQuestion) ||
        normalizedQuestion.includes(normalizedText));
    const tabularAttachments = (doc.files ?? [])
      .filter((file) => {
        const belongsToUser = !file.user || String(file.user) === params.userId;
        const matchesType = tabularMimeTypes.has(file.type);
        const matchesFilename = params.filename
          ? file.filename.toLowerCase() === params.filename.toLowerCase()
          : true;
        return belongsToUser && matchesType && matchesFilename;
      })
      .map((file) => attachmentFromLibreChatFile({ userId: params.userId, doc, file }));

    if (!textMatches && !params.filename) {
      continue;
    }

    if (params.filename && !tabularAttachments.length) {
      continue;
    }

    return {
      conversationId: doc.conversationId,
      messageId: doc.messageId,
      text: doc.text ?? '',
      attachments: tabularAttachments,
    };
  }

  return null;
}

export async function listRecentConversationMessages(params: {
  userId: string;
  conversationId?: string;
  limit?: number;
}): Promise<ConversationTurnSummary[]> {
  if (!params.conversationId) {
    return [];
  }

  const db = await getMongoDb();
  const messages = db.collection<LibreChatMessage>('messages');
  const docs = await messages
    .find(
      {
        conversationId: params.conversationId,
        text: { $type: 'string', $ne: '' },
      },
      {
        projection: {
          createdAt: 1,
          text: 1,
          isCreatedByUser: 1,
        },
        sort: { createdAt: -1 },
        limit: Math.max(1, Math.min(params.limit ?? config.CONTEXT_MAX_RECENT_MESSAGES, 80)),
      },
    )
    .toArray();

  return docs
    .reverse()
    .map((doc): ConversationTurnSummary => ({
      role: doc.isCreatedByUser ? 'usuario' : 'asistente',
      text: compactText(doc.text),
      createdAt: doc.createdAt?.toISOString(),
    }))
    .filter((turn) => turn.text.length > 0);
}

async function findLatestTabularAttachmentOnce(params: {
  userId: string;
  conversationId?: string;
  filename?: string;
}): Promise<DiscoveredAttachment | null> {
  const db = await getMongoDb();
  const messages = db.collection<LibreChatMessage>('messages');
  const baseQuery: Record<string, unknown> = {
    isCreatedByUser: true,
    files: { $exists: true, $ne: [] },
  };

  if (!params.conversationId && !params.filename) {
    return null;
  }

  const queries: Record<string, unknown>[] = [];
  if (params.conversationId) {
    queries.push({
      ...baseQuery,
      conversationId: params.conversationId,
    });
  } else {
    queries.push(baseQuery);
  }

  for (const query of queries) {
    const docs = await messages
      .find(query, {
        projection: {
          messageId: 1,
          conversationId: 1,
          createdAt: 1,
          files: 1,
        },
        sort: { createdAt: -1 },
        limit: 25,
      })
      .toArray();

    for (const doc of docs) {
      const attachment = (doc.files ?? []).find((file) => {
        const belongsToUser = !file.user || String(file.user) === params.userId;
        const matchesType = tabularMimeTypes.has(file.type);
        const matchesFilename = params.filename
          ? file.filename.toLowerCase() === params.filename.toLowerCase()
          : true;
        return belongsToUser && matchesType && matchesFilename;
      });

      if (!attachment) {
        continue;
      }

      const relative = attachment.filepath.replace(/^\/uploads\//, '');
      return {
        userId: params.userId,
        conversationId: doc.conversationId,
        messageId: doc.messageId,
        fileId: attachment.file_id,
        filename: attachment.filename,
        mimeType: attachment.type,
        filepath: attachment.filepath,
        absolutePath: path.join(config.LIBRECHAT_UPLOAD_ROOT, relative),
        bytes: attachment.bytes ?? 0,
      };
    }
  }

  return null;
}
