import { MongoClient, Db } from 'mongodb';
import { Pool } from 'pg';
import { config } from './config.js';

export const pg = new Pool({
  connectionString: config.POSTGRES_URL,
});

export const mongoClient = new MongoClient(config.MONGO_URL);

let mongoDb: Db | null = null;

export async function getMongoDb(): Promise<Db> {
  if (mongoDb) {
    return mongoDb;
  }
  await mongoClient.connect();
  mongoDb = mongoClient.db();
  return mongoDb;
}

export async function initPostgres(): Promise<void> {
  await pg.query(`
    create schema if not exists analitrics_meta;
    create schema if not exists analitrics_uploads;

    create table if not exists analitrics_meta.uploaded_files (
      upload_id uuid primary key,
      user_id text not null,
      conversation_id text,
      source_file_id text,
      source_message_id text,
      filename text not null,
      mime_type text not null,
      file_hash text not null,
      file_size_bytes bigint not null,
      workbook_sheet_count integer not null default 1,
      import_status text not null default 'ready',
      semantic_summary text,
      business_summary text,
      profile_json jsonb not null default '{}'::jsonb,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now()
    );

    create unique index if not exists uploaded_files_user_hash_idx
      on analitrics_meta.uploaded_files(user_id, file_hash);

    create table if not exists analitrics_meta.uploaded_file_tables (
      id bigserial primary key,
      upload_id uuid not null references analitrics_meta.uploaded_files(upload_id) on delete cascade,
      sheet_name text not null,
      table_name text not null,
      row_count integer not null default 0,
      column_count integer not null default 0,
      columns_json jsonb not null default '[]'::jsonb,
      sample_rows_json jsonb not null default '[]'::jsonb,
      created_at timestamptz not null default now()
    );

    create table if not exists analitrics_meta.conversation_file_contexts (
      id bigserial primary key,
      user_id text not null,
      conversation_id text not null,
      upload_id uuid not null references analitrics_meta.uploaded_files(upload_id) on delete cascade,
      source_file_id text,
      source_message_id text,
      filename text,
      mime_type text,
      is_active boolean not null default true,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now(),
      unique(user_id, conversation_id, upload_id)
    );

    alter table analitrics_meta.conversation_file_contexts
      add column if not exists source_file_id text;
    alter table analitrics_meta.conversation_file_contexts
      add column if not exists source_message_id text;
    alter table analitrics_meta.conversation_file_contexts
      add column if not exists filename text;
    alter table analitrics_meta.conversation_file_contexts
      add column if not exists mime_type text;
    alter table analitrics_meta.conversation_file_contexts
      add column if not exists updated_at timestamptz not null default now();

    create index if not exists conversation_file_contexts_user_convo_active_idx
      on analitrics_meta.conversation_file_contexts(user_id, conversation_id, is_active, updated_at desc);
    create unique index if not exists conversation_file_contexts_user_source_file_idx
      on analitrics_meta.conversation_file_contexts(user_id, conversation_id, source_file_id)
      where source_file_id is not null;

    update analitrics_meta.conversation_file_contexts c
    set
      source_file_id = coalesce(c.source_file_id, f.source_file_id),
      source_message_id = coalesce(c.source_message_id, f.source_message_id),
      filename = coalesce(c.filename, f.filename),
      mime_type = coalesce(c.mime_type, f.mime_type),
      updated_at = coalesce(c.updated_at, c.created_at, now())
    from analitrics_meta.uploaded_files f
    where c.upload_id = f.upload_id;
  `);
}

export async function closeConnections(): Promise<void> {
  await Promise.allSettled([pg.end(), mongoClient.close()]);
}
