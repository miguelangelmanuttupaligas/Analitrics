import fs from 'fs/promises';
import { parse as parseCsv } from 'csv-parse/sync';
import XLSX from 'xlsx';
import { pg } from '../db.js';
import { config } from '../config.js';
import type { DiscoveredAttachment, ImportedContext, InferredColumn, ParsedSheet } from '../types.js';
import {
  assertSelectOnly,
  isBooleanLike,
  isDateLike,
  isNumericLike,
  normalizeCellValue,
  sha256,
  slugify,
  toUuidLikeHash,
  truncateText,
  uniqueColumnNames,
} from '../utils.js';

async function activateExclusiveConversationContext(params: {
  userId: string;
  conversationId: string;
  uploadId: string;
  sourceFileId?: string;
  sourceMessageId?: string;
  filename?: string;
  mimeType?: string;
}): Promise<void> {
  await pg.query(
    `
      update analitrics_meta.conversation_file_contexts
      set is_active = false
      where user_id = $1
        and conversation_id = $2
        and upload_id <> $3
    `,
    [params.userId, params.conversationId, params.uploadId],
  );

  await pg.query(
    `
      insert into analitrics_meta.conversation_file_contexts(
        user_id, conversation_id, upload_id, source_file_id, source_message_id, filename, mime_type, is_active
      )
      values ($1, $2, $3, $4, $5, $6, $7, true)
      on conflict (user_id, conversation_id, upload_id)
      do update set
        is_active = true,
        source_file_id = excluded.source_file_id,
        source_message_id = excluded.source_message_id,
        filename = excluded.filename,
        mime_type = excluded.mime_type,
        updated_at = now()
    `,
    [
      params.userId,
      params.conversationId,
      params.uploadId,
      params.sourceFileId ?? null,
      params.sourceMessageId ?? null,
      params.filename ?? null,
      params.mimeType ?? null,
    ],
  );
}

function inferColumnType(values: unknown[]): InferredColumn['pgType'] {
  const meaningful = values.filter((value) => normalizeCellValue(value) !== null);
  if (meaningful.length === 0) {
    return 'text';
  }
  if (meaningful.every(isBooleanLike)) {
    return 'boolean';
  }
  if (meaningful.every(isNumericLike)) {
    const allIntegers = meaningful.every((value) => {
      const num = typeof value === 'number' ? value : Number(String(value).replace(/,/g, ''));
      return Number.isInteger(num);
    });
    return allIntegers ? 'bigint' : 'numeric';
  }
  if (meaningful.every(isDateLike)) {
    return 'timestamptz';
  }
  return 'text';
}

function parseCsvBuffer(buffer: Buffer): ParsedSheet[] {
  const text = buffer.toString('utf-8');
  const records = parseCsv(text, {
    columns: true,
    skip_empty_lines: true,
    bom: true,
  }) as Record<string, unknown>[];
  return [buildParsedSheet('csv', records)];
}

function parseWorkbookBuffer(buffer: Buffer): ParsedSheet[] {
  const workbook = XLSX.read(buffer, {
    type: 'buffer',
    cellDates: true,
    raw: false,
  });
  return workbook.SheetNames.map((sheetName) => {
    const rows = XLSX.utils.sheet_to_json<Record<string, unknown>>(workbook.Sheets[sheetName], {
      defval: null,
      raw: false,
    });
    return buildParsedSheet(sheetName, rows);
  });
}

function buildParsedSheet(sheetName: string, rows: Record<string, unknown>[]): ParsedSheet {
  const allKeys = Array.from(
    rows.reduce((acc, row) => {
      Object.keys(row).forEach((key) => acc.add(key));
      return acc;
    }, new Set<string>()),
  );
  const normalizedColumns = uniqueColumnNames(allKeys);
  const columns = allKeys.map((sourceName, index) => {
    const values = rows.map((row) => row[sourceName]);
    const sampleValues = Array.from(
      new Set(values.map(normalizeCellValue).filter((value) => value !== null)),
    ).slice(0, 5) as Array<string | number | boolean | null>;
    return {
      sourceName,
      columnName: normalizedColumns[index] ?? `col_${index + 1}`,
      pgType: inferColumnType(values),
      nullCount: values.filter((value) => normalizeCellValue(value) === null).length,
      sampleValues,
    } satisfies InferredColumn;
  });

  const normalizedRows = rows.map((row) => {
    const normalizedRow: Record<string, unknown> = {};
    columns.forEach((column) => {
      normalizedRow[column.columnName] = normalizeCellValue(row[column.sourceName]);
    });
    return normalizedRow;
  });

  return {
    sheetName,
    rows: normalizedRows,
    columns,
  };
}

function coerceValue(value: unknown, pgType: InferredColumn['pgType']): unknown {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  if (pgType === 'boolean') {
    if (typeof value === 'boolean') {
      return value;
    }
    const normalized = String(value).trim().toLowerCase();
    return ['true', 'yes', 'si', 'sí', '1'].includes(normalized);
  }
  if (pgType === 'bigint') {
    return Number.parseInt(String(value).replace(/,/g, ''), 10);
  }
  if (pgType === 'numeric') {
    return Number(String(value).replace(/,/g, ''));
  }
  if (pgType === 'timestamptz') {
    const date = value instanceof Date ? value : new Date(String(value));
    return Number.isNaN(date.getTime()) ? null : date.toISOString();
  }
  return String(value);
}

function buildSemanticSummary(filename: string, sheets: ParsedSheet[]): string {
  const parts = sheets.map(
    (sheet) =>
      `${sheet.sheetName}: ${sheet.rows.length} filas, ${sheet.columns.length} columnas (${sheet.columns
        .slice(0, 8)
        .map((c) => c.sourceName)
        .join(', ')})`,
  );
  return truncateText(`Archivo ${filename}. ${parts.join(' | ')}`, 800);
}

function buildBusinessSummary(filename: string, sheets: ParsedSheet[]): string {
  const dominantColumns = sheets
    .flatMap((sheet) => sheet.columns.map((column) => column.sourceName))
    .slice(0, 10)
    .join(', ');
  return truncateText(
    `El archivo ${filename} fue cargado en memoria analítica y parece contener información tabular utilizable para preguntas de negocio. Las primeras dimensiones observadas incluyen: ${dominantColumns}.`,
    800,
  );
}

async function persistSheetTable(uploadId: string, sheet: ParsedSheet, sheetIndex: number): Promise<string> {
  const tableName = `file_${slugify(uploadId.replace(/-/g, '').slice(0, 12))}__${slugify(sheet.sheetName) || `sheet_${sheetIndex + 1}`}`;
  const qualifiedName = `analitrics_uploads.${tableName}`;
  const columnSql = sheet.columns
    .map((column) => `"${column.columnName}" ${column.pgType}`)
    .join(', ');

  await pg.query(`drop table if exists ${qualifiedName}`);
  await pg.query(`create table ${qualifiedName} (${columnSql})`);

  if (sheet.rows.length > 0) {
    const batchSize = 500;
    for (let start = 0; start < sheet.rows.length; start += batchSize) {
      const batch = sheet.rows.slice(start, start + batchSize);
      const values: unknown[] = [];
      const tuples = batch
        .map((row, rowIndex) => {
          const placeholders = sheet.columns.map((column, colIndex) => {
            values.push(coerceValue(row[column.columnName], column.pgType));
            return `$${rowIndex * sheet.columns.length + colIndex + 1}`;
          });
          return `(${placeholders.join(', ')})`;
        })
        .join(', ');
      const insertSql = `insert into ${qualifiedName} (${sheet.columns
        .map((column) => `"${column.columnName}"`)
        .join(', ')}) values ${tuples}`;
      await pg.query(insertSql, values);
    }
  }

  return tableName;
}

export async function importAttachmentIntoPostgres(attachment: DiscoveredAttachment): Promise<ImportedContext> {
  if (attachment.bytes > config.MAX_TABULAR_UPLOAD_BYTES) {
    throw new Error(
      `El archivo ${attachment.filename} supera el límite de ${Math.floor(config.MAX_TABULAR_UPLOAD_BYTES / 1024 / 1024)} MB.`,
    );
  }

  const fileBuffer = await fs.readFile(attachment.absolutePath);
  if (fileBuffer.byteLength > config.MAX_TABULAR_UPLOAD_BYTES) {
    throw new Error(
      `El archivo ${attachment.filename} supera el límite de ${Math.floor(config.MAX_TABULAR_UPLOAD_BYTES / 1024 / 1024)} MB.`,
    );
  }
  const fileHash = sha256(fileBuffer);
  const uploadId = toUuidLikeHash(sha256(Buffer.from(`${attachment.userId}:${fileHash}`, 'utf-8')));
  const existing = await pg.query<{
    upload_id: string;
    semantic_summary: string | null;
    business_summary: string | null;
  }>(
    `
      select upload_id, semantic_summary, business_summary
      from analitrics_meta.uploaded_files
      where upload_id = $2
         or (user_id = $1 and file_hash = $3)
      limit 1
    `,
    [attachment.userId, uploadId, fileHash],
  );

  if (existing.rowCount) {
    const uploadId = existing.rows[0].upload_id;
    await activateExclusiveConversationContext({
      userId: attachment.userId,
      conversationId: attachment.conversationId,
      uploadId,
      sourceFileId: attachment.fileId,
      sourceMessageId: attachment.messageId,
      filename: attachment.filename,
      mimeType: attachment.mimeType,
    });
    return getImportedContext(uploadId);
  }

  const sheets =
    attachment.mimeType === 'text/csv' || attachment.mimeType === 'application/csv'
      ? parseCsvBuffer(fileBuffer)
      : parseWorkbookBuffer(fileBuffer);

  const semanticSummary = buildSemanticSummary(attachment.filename, sheets);
  const businessSummary = buildBusinessSummary(attachment.filename, sheets);
  const profileJson = {
    sheetCount: sheets.length,
    sheets: sheets.map((sheet) => ({
      sheetName: sheet.sheetName,
      rowCount: sheet.rows.length,
      columnCount: sheet.columns.length,
      columns: sheet.columns.map((column) => ({
        sourceName: column.sourceName,
        columnName: column.columnName,
        pgType: column.pgType,
        nullCount: column.nullCount,
        sampleValues: column.sampleValues,
      })),
    })),
  };

  await pg.query('begin');
  try {
    await pg.query(
      `
        insert into analitrics_meta.uploaded_files (
          upload_id, user_id, conversation_id, source_file_id, source_message_id, filename, mime_type,
          file_hash, file_size_bytes, workbook_sheet_count, semantic_summary, business_summary, profile_json
        ) values (
          $1, $2, $3, $4, $5, $6, $7,
          $8, $9, $10, $11, $12, $13::jsonb
        )
        on conflict (upload_id) do update set
          conversation_id = excluded.conversation_id,
          source_file_id = excluded.source_file_id,
          source_message_id = excluded.source_message_id,
          filename = excluded.filename,
          mime_type = excluded.mime_type,
          file_size_bytes = excluded.file_size_bytes,
          workbook_sheet_count = excluded.workbook_sheet_count,
          semantic_summary = excluded.semantic_summary,
          business_summary = excluded.business_summary,
          profile_json = excluded.profile_json,
          import_status = 'ready',
          updated_at = now()
      `,
      [
        uploadId,
        attachment.userId,
        attachment.conversationId,
        attachment.fileId,
        attachment.messageId,
        attachment.filename,
        attachment.mimeType,
        fileHash,
        attachment.bytes || fileBuffer.byteLength,
        sheets.length,
        semanticSummary,
        businessSummary,
        JSON.stringify(profileJson),
      ],
    );

    await pg.query('delete from analitrics_meta.uploaded_file_tables where upload_id = $1', [uploadId]);

    for (const [index, sheet] of sheets.entries()) {
      const tableName = await persistSheetTable(uploadId, sheet, index);
      await pg.query(
        `
          insert into analitrics_meta.uploaded_file_tables (
            upload_id, sheet_name, table_name, row_count, column_count, columns_json, sample_rows_json
          ) values ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb)
        `,
        [
          uploadId,
          sheet.sheetName,
          tableName,
          sheet.rows.length,
          sheet.columns.length,
          JSON.stringify(sheet.columns),
          JSON.stringify(sheet.rows.slice(0, 5)),
        ],
      );
    }

    await activateExclusiveConversationContext({
      userId: attachment.userId,
      conversationId: attachment.conversationId,
      uploadId,
      sourceFileId: attachment.fileId,
      sourceMessageId: attachment.messageId,
      filename: attachment.filename,
      mimeType: attachment.mimeType,
    });
    await pg.query('commit');
  } catch (error) {
    await pg.query('rollback');
    if (
      error instanceof Error &&
      /duplicate key value violates unique constraint "uploaded_files_pkey"/i.test(error.message)
    ) {
      await activateExclusiveConversationContext({
        userId: attachment.userId,
        conversationId: attachment.conversationId,
        uploadId,
        sourceFileId: attachment.fileId,
        sourceMessageId: attachment.messageId,
        filename: attachment.filename,
        mimeType: attachment.mimeType,
      });
      return getImportedContext(uploadId, attachment.conversationId);
    }
    throw error;
  }

  return getImportedContext(uploadId);
}

export async function getImportedContext(
  uploadId: string,
  conversationId?: string,
): Promise<ImportedContext> {
  const [fileResult, tablesResult] = await Promise.all([
    pg.query<{
      upload_id: string;
      filename: string;
      conversation_id: string;
      semantic_summary: string | null;
      business_summary: string | null;
    }>(
      `
        select
          f.upload_id,
          f.filename,
          coalesce(c.conversation_id, f.conversation_id) as conversation_id,
          f.semantic_summary,
          f.business_summary
        from analitrics_meta.uploaded_files f
        left join lateral (
          select conversation_id
          from analitrics_meta.conversation_file_contexts
          where upload_id = f.upload_id
            and ($2::text is null or conversation_id = $2)
          order by
            case when conversation_id = $2 then 0 else 1 end,
            updated_at desc,
            created_at desc
          limit 1
        ) c on true
        where f.upload_id = $1
      `,
      [uploadId, conversationId ?? null],
    ),
    pg.query<{
      sheet_name: string;
      table_name: string;
      row_count: number;
      column_count: number;
    }>(
      `
        select sheet_name, table_name, row_count, column_count
        from analitrics_meta.uploaded_file_tables
        where upload_id = $1
        order by id
      `,
      [uploadId],
    ),
  ]);

  if (!fileResult.rowCount) {
    throw new Error('No se encontró el contexto importado.');
  }

  const file = fileResult.rows[0];
  return {
    uploadId: file.upload_id,
    filename: file.filename,
    conversationId: file.conversation_id,
    summary: file.semantic_summary ?? '',
    businessSummary: file.business_summary ?? '',
    tables: tablesResult.rows.map((row: { sheet_name: string; table_name: string; row_count: number; column_count: number }) => ({
      sheetName: row.sheet_name,
      tableName: row.table_name,
      rowCount: row.row_count,
      columnCount: row.column_count,
    })),
  };
}

export async function listActiveContexts(userId: string, conversationId?: string): Promise<ImportedContext[]> {
  if (!conversationId) {
    return [];
  }

  const query = `
    select distinct on (f.upload_id) f.upload_id
    from analitrics_meta.uploaded_files f
    left join analitrics_meta.conversation_file_contexts c
      on c.upload_id = f.upload_id
     and c.user_id = $1
    where f.user_id = $1
      and (
        $2::text is null
        or (
          c.conversation_id = $2
          and c.is_active = true
        )
        or (
          not exists (
            select 1
            from analitrics_meta.conversation_file_contexts cx
            where cx.upload_id = f.upload_id
              and cx.user_id = $1
          )
          and f.conversation_id = $2
        )
      )
    order by f.upload_id, c.updated_at desc nulls last, c.created_at desc nulls last, f.created_at desc
    limit 1
  `;
  const result = await pg.query<{ upload_id: string }>(query, [userId, conversationId ?? null]);
  return Promise.all(
    result.rows.map((row: { upload_id: string }) => getImportedContext(row.upload_id, conversationId)),
  );
}

export async function getCurrentContext(params: {
  userId: string;
  conversationId?: string;
  filename?: string;
}): Promise<ImportedContext | null> {
  if (!params.conversationId && !params.filename) {
    return null;
  }

  const result = await pg.query<{ upload_id: string }>(
    `
      select f.upload_id
      from analitrics_meta.uploaded_files f
      left join analitrics_meta.conversation_file_contexts c
        on c.upload_id = f.upload_id
       and c.user_id = $1
      where f.user_id = $1
        and (
          $2::text is null
          or (
            c.conversation_id = $2
            and c.is_active = true
          )
          or (
            not exists (
              select 1
              from analitrics_meta.conversation_file_contexts cx
              where cx.upload_id = f.upload_id
                and cx.user_id = $1
            )
            and f.conversation_id = $2
          )
        )
        and ($3::text is null or lower(f.filename) = lower($3))
      order by coalesce(c.updated_at, c.created_at, f.created_at) desc, f.created_at desc
      limit 1
    `,
    [params.userId, params.conversationId ?? null, params.filename ?? null],
  );
  if (!result.rowCount) {
    return null;
  }
  return getImportedContext(result.rows[0].upload_id, params.conversationId);
}

function normalizeFilenameCandidate(value: string): string {
  return value
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .replace(/\.[a-z0-9]+$/i, '')
    .replace(/[_\-.]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase();
}

export async function findImportedContextsMentionedInQuestion(params: {
  userId: string;
  question: string;
}): Promise<ImportedContext[]> {
  const result = await pg.query<{
    upload_id: string;
    filename: string;
  }>(
    `
      select upload_id, filename
      from analitrics_meta.uploaded_files
      where user_id = $1
      order by updated_at desc, created_at desc
      limit 50
    `,
    [params.userId],
  );

  const normalizedQuestion = normalizeFilenameCandidate(params.question);
  const matches = result.rows.filter((row) => {
    const filename = normalizeFilenameCandidate(row.filename);
    return filename.length > 0 && normalizedQuestion.includes(filename);
  });

  return Promise.all(matches.map((row) => getImportedContext(row.upload_id)));
}

export async function describeCurrentContext(params: {
  userId: string;
  conversationId?: string;
  filename?: string;
}): Promise<string> {
  const context = await getCurrentContext(params);
  if (!context) {
    return 'No hay contexto tabular importado todavía para este usuario o conversación.';
  }
  const tableLines = context.tables.map(
    (table) =>
      `- ${table.sheetName} -> analitrics_uploads.${table.tableName} (${table.rowCount} filas, ${table.columnCount} columnas)`,
  );
  return [
    `Archivo activo: ${context.filename}`,
    `Resumen técnico: ${context.summary}`,
    `Resumen de negocio: ${context.businessSummary}`,
    'Tablas disponibles:',
    ...tableLines,
  ].join('\n');
}

export async function runSelectQuery(sql: string): Promise<{ rowCount: number; rows: Record<string, unknown>[] }> {
  assertSelectOnly(sql);
  const client = await pg.connect();
  try {
    await client.query('begin transaction read only');
    await client.query("set local statement_timeout = '15000ms'");
    const result = await client.query(sql);
    await client.query('commit');
    return {
      rowCount: result.rowCount ?? result.rows.length,
      rows: result.rows.slice(0, 200),
    };
  } catch (error) {
    await client.query('rollback').catch(() => undefined);
    throw error;
  } finally {
    client.release();
  }
}
