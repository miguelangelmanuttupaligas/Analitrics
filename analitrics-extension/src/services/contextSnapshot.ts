import { pg } from '../db.js';
import { config } from '../config.js';
import type {
  ContextAssetSummary,
  ContextAttachmentSummary,
  ConversationTurnSummary,
  ContextSnapshot,
  ContextTableProfile,
} from '../types.js';
import { importAttachmentIntoPostgres, listActiveContexts } from './ingestion.js';
import { listRecentConversationMessages, listRecentTabularAttachmentsForUser } from './librechatFiles.js';

export type RequestContext = {
  userId: string;
  conversationId?: string;
};

export type OrchestrationOptions = {
  filename?: string;
  conversationId?: string;
  conversationHistory?: ConversationTurnSummary[];
};

export const CONTEXT_BUDGET = {
  maxAssets: config.CONTEXT_MAX_ASSETS,
  maxTablesPerAsset: config.CONTEXT_MAX_TABLES_PER_ASSET,
  maxColumnsPerTable: config.CONTEXT_MAX_COLUMNS_PER_TABLE,
  maxSampleRowsPerTable: config.CONTEXT_MAX_SAMPLE_ROWS_PER_TABLE,
  maxRecentMessages: config.CONTEXT_MAX_RECENT_MESSAGES,
} as const;

function trimTableProfile(table: ContextTableProfile): ContextTableProfile {
  return {
    ...table,
    columns: table.columns.slice(0, CONTEXT_BUDGET.maxColumnsPerTable),
    sampleRows: table.sampleRows.slice(0, CONTEXT_BUDGET.maxSampleRowsPerTable),
  };
}

async function loadTableProfiles(uploadId: string): Promise<ContextTableProfile[]> {
  const result = await pg.query<{
    sheet_name: string;
    table_name: string;
    row_count: number;
    column_count: number;
    columns_json: unknown;
    sample_rows_json: unknown;
  }>(
    `
      select sheet_name, table_name, row_count, column_count, columns_json, sample_rows_json
      from analitrics_meta.uploaded_file_tables
      where upload_id = $1
      order by id
    `,
    [uploadId],
  );

  return result.rows.map((row) => ({
    sheetName: row.sheet_name,
    tableName: row.table_name,
    rowCount: row.row_count,
    columnCount: row.column_count,
    columns: Array.isArray(row.columns_json)
      ? (row.columns_json as ContextTableProfile['columns'])
      : [],
    sampleRows: Array.isArray(row.sample_rows_json)
      ? (row.sample_rows_json as Record<string, unknown>[])
      : [],
  }));
}

async function loadCorporateTables(): Promise<Array<{ schema: string; table: string }>> {
  const result = await pg.query<{ schemaname: string; tablename: string }>(
    `
      select schemaname, tablename
      from pg_tables
      where schemaname not in ('pg_catalog', 'information_schema', 'analitrics_meta', 'analitrics_uploads')
      order by schemaname, tablename
      limit 25
    `,
  );

  return result.rows.map((row) => ({
    schema: row.schemaname,
    table: row.tablename,
  }));
}

export async function buildContextSnapshot(
  baseContext: RequestContext,
  options: OrchestrationOptions = {},
): Promise<ContextSnapshot> {
  const conversationId = options.conversationId ?? baseContext.conversationId;
  const [recentAttachments, corporateTables, loadedConversationHistory] = await Promise.all([
    listRecentTabularAttachmentsForUser({
      userId: baseContext.userId,
      conversationId,
      filename: options.filename,
      limit: CONTEXT_BUDGET.maxAssets,
    }).catch(() => []),
    loadCorporateTables(),
    listRecentConversationMessages({
      userId: baseContext.userId,
      conversationId,
      limit: CONTEXT_BUDGET.maxRecentMessages,
    }).catch(() => []),
  ]);
  const conversationHistory = options.conversationHistory ?? loadedConversationHistory;

  const existingImports = recentAttachments.length
    ? await pg.query<{ source_file_id: string }>(
        `
          select distinct source_file_id
          from analitrics_meta.conversation_file_contexts
          where user_id = $1
            and source_file_id = any($2::text[])
        `,
        [baseContext.userId, recentAttachments.map((attachment) => attachment.fileId)],
      )
    : { rows: [] as Array<{ source_file_id: string }> };

  const importedFileIds = new Set(existingImports.rows.map((row) => row.source_file_id));
  const attachmentsToImport = recentAttachments.filter(
    (attachment) => !importedFileIds.has(attachment.fileId),
  );

  for (const attachment of attachmentsToImport) {
    try {
      await importAttachmentIntoPostgres(attachment);
      importedFileIds.add(attachment.fileId);
    } catch {
      // El snapshot debe sobrevivir aunque algún adjunto falle en importación.
    }
  }

  const importedContexts = await listActiveContexts(baseContext.userId, conversationId);
  const profiledAssets = await Promise.all(
    importedContexts.map(async (context, index) => {
      const tables = await loadTableProfiles(context.uploadId);
      return {
        ...context,
        tableCount: tables.length,
        totalRows: tables.reduce((total, table) => total + table.rowCount, 0),
        totalColumns: tables.reduce((total, table) => total + table.columnCount, 0),
        matchedBy: ['pendiente_seleccion_worker'],
        recencyRank: index,
        score: 0,
        tables: tables.slice(0, CONTEXT_BUDGET.maxTablesPerAsset).map(trimTableProfile),
      } satisfies ContextAssetSummary;
    }),
  );

  const candidateAssets = profiledAssets.filter((asset) =>
    options.filename ? asset.filename.toLowerCase() === options.filename.toLowerCase() : true,
  );

  const selectedAssets = candidateAssets.slice(0, CONTEXT_BUDGET.maxAssets);
  const latestAttachment = recentAttachments[0] ?? null;
  const primaryAsset = selectedAssets[0] ?? null;

  return {
    userId: baseContext.userId,
    conversationId,
    filenameHint: options.filename,
    budget: {
      maxAssets: CONTEXT_BUDGET.maxAssets,
      maxTablesPerAsset: CONTEXT_BUDGET.maxTablesPerAsset,
      maxColumnsPerTable: CONTEXT_BUDGET.maxColumnsPerTable,
      maxSampleRowsPerTable: CONTEXT_BUDGET.maxSampleRowsPerTable,
    },
    selectedAssets,
    availableAssets: candidateAssets.map((asset) => ({
      uploadId: asset.uploadId,
      filename: asset.filename,
      conversationId: asset.conversationId,
      summary: asset.summary,
      businessSummary: asset.businessSummary,
      tableCount: asset.tableCount,
      totalRows: asset.totalRows,
      totalColumns: asset.totalColumns,
      recencyRank: asset.recencyRank,
    })),
    recentAttachments: recentAttachments.map<ContextAttachmentSummary>((attachment) => ({
      available: true,
      fileId: attachment.fileId,
      filename: attachment.filename,
      conversationId: attachment.conversationId,
      mimeType: attachment.mimeType,
      imported: importedFileIds.has(attachment.fileId),
    })),
    conversationHistory,
    activeFile: {
      available: primaryAsset != null,
      filename: primaryAsset?.filename,
      summary: primaryAsset?.summary,
      businessSummary: primaryAsset?.businessSummary,
      uploadId: primaryAsset?.uploadId,
      tables: primaryAsset?.tables ?? [],
    },
    latestAttachment: {
      available: latestAttachment != null,
      filename: latestAttachment?.filename,
      conversationId: latestAttachment?.conversationId,
    },
    corporateTables,
  };
}

export function applyContextSelection(
  snapshot: ContextSnapshot,
  selection: { selectedUploadIds: string[]; rationale: string },
): ContextSnapshot {
  const selectedSet = new Set(selection.selectedUploadIds);
  const selectedAssets = snapshot.selectedAssets
    .filter((asset) => selectedSet.has(asset.uploadId))
    .slice(0, snapshot.budget.maxAssets)
    .map((asset) => ({
      ...asset,
      matchedBy:
        asset.matchedBy.length > 0 ? asset.matchedBy : [selection.rationale || 'seleccion_worker'],
    }));

  const primaryAsset = selectedAssets[0] ?? null;

  return {
    ...snapshot,
    selectedAssets,
    activeFile: {
      available: primaryAsset != null,
      filename: primaryAsset?.filename,
      summary: primaryAsset?.summary,
      businessSummary: primaryAsset?.businessSummary,
      uploadId: primaryAsset?.uploadId,
      tables: primaryAsset?.tables ?? [],
    },
  };
}

export function buildSelectedAssetsDescription(snapshot: ContextSnapshot): string {
  if (!snapshot.selectedAssets.length) {
    return 'No hay activos tabulares seleccionados en contexto.';
  }

  const assetsDescription = snapshot.selectedAssets
    .map((asset, index) => {
      const tableLines = asset.tables.map(
        (table) =>
          `- Hoja ${table.sheetName} -> analitrics_uploads.${table.tableName} (${table.rowCount} filas, ${table.columnCount} columnas: ${table.columns
            .map((column) => column.columnName)
            .join(', ')})`,
      );
      return [
        `Activo ${index + 1}: ${asset.filename}`,
        `Resumen técnico: ${asset.summary}`,
        `Resumen de negocio: ${asset.businessSummary}`,
        `Coincidencias: ${asset.matchedBy.join(', ') || 'reciente'}`,
        ...tableLines,
      ].join('\n');
    })
    .join('\n\n');

  const recentHistory = snapshot.conversationHistory.length
    ? snapshot.conversationHistory
        .map((turn) => `${turn.role}: ${turn.text}`)
        .join('\n')
    : 'Sin historial conversacional reciente.';

  return [assetsDescription, `Historial conversacional reciente:\n${recentHistory}`].join('\n\n');
}
