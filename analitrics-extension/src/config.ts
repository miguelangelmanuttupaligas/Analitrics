import { z } from 'zod';

const envSchema = z.object({
  PORT: z.coerce.number().default(3095),
  POSTGRES_URL: z.string().min(1),
  MONGO_URL: z.string().min(1),
  LIBRECHAT_UPLOAD_ROOT: z.string().min(1),
  ALLOWED_USER_HEADER: z.string().default('x-librechat-user-id'),
  OPENAI_API_KEY: z.string().optional(),
  WORKER_MODEL: z.string().default('gpt-4.1-mini'),
  CONTEXT_MAX_ASSETS: z.coerce.number().int().positive().default(4),
  CONTEXT_MAX_TABLES_PER_ASSET: z.coerce.number().int().positive().default(3),
  CONTEXT_MAX_COLUMNS_PER_TABLE: z.coerce.number().int().positive().default(12),
  CONTEXT_MAX_SAMPLE_ROWS_PER_TABLE: z.coerce.number().int().positive().default(3),
});

export const config = envSchema.parse({
  PORT: process.env.PORT,
  POSTGRES_URL: process.env.POSTGRES_URL,
  MONGO_URL: process.env.MONGO_URL,
  LIBRECHAT_UPLOAD_ROOT: process.env.LIBRECHAT_UPLOAD_ROOT,
  ALLOWED_USER_HEADER: process.env.ALLOWED_USER_HEADER,
  OPENAI_API_KEY: process.env.OPENAI_API_KEY,
  WORKER_MODEL: process.env.WORKER_MODEL,
  CONTEXT_MAX_ASSETS: process.env.CONTEXT_MAX_ASSETS,
  CONTEXT_MAX_TABLES_PER_ASSET: process.env.CONTEXT_MAX_TABLES_PER_ASSET,
  CONTEXT_MAX_COLUMNS_PER_TABLE: process.env.CONTEXT_MAX_COLUMNS_PER_TABLE,
  CONTEXT_MAX_SAMPLE_ROWS_PER_TABLE: process.env.CONTEXT_MAX_SAMPLE_ROWS_PER_TABLE,
});

export const tabularMimeTypes = new Set([
  'text/csv',
  'application/csv',
  'application/vnd.ms-excel',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
]);
