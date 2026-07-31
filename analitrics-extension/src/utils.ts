import crypto from 'crypto';

export function slugify(value: string): string {
  return value
    .normalize('NFKD')
    .replace(/[^\w\s-]/g, '')
    .trim()
    .replace(/[-\s]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .toLowerCase();
}

export function uniqueColumnNames(values: string[]): string[] {
  const counts = new Map<string, number>();
  return values.map((value, index) => {
    const base = slugify(value) || `col_${index + 1}`;
    const count = counts.get(base) ?? 0;
    counts.set(base, count + 1);
    return count === 0 ? base : `${base}_${count + 1}`;
  });
}

export function sha256(input: Buffer): string {
  return crypto.createHash('sha256').update(input).digest('hex');
}

export function toUuidLikeHash(hash: string): string {
  return `${hash.slice(0, 8)}-${hash.slice(8, 12)}-${hash.slice(12, 16)}-${hash.slice(16, 20)}-${hash.slice(20, 32)}`;
}

export function isNumericLike(value: unknown): boolean {
  if (typeof value === 'number') {
    return Number.isFinite(value);
  }
  if (typeof value !== 'string') {
    return false;
  }
  const normalized = value.replace(/,/g, '').trim();
  return normalized !== '' && !Number.isNaN(Number(normalized));
}

export function isBooleanLike(value: unknown): boolean {
  if (typeof value === 'boolean') {
    return true;
  }
  if (typeof value !== 'string') {
    return false;
  }
  const normalized = value.trim().toLowerCase();
  return ['true', 'false', 'yes', 'no', 'si', 'sí', '0', '1'].includes(normalized);
}

export function isDateLike(value: unknown): boolean {
  if (value instanceof Date && !Number.isNaN(value.getTime())) {
    return true;
  }
  if (typeof value !== 'string') {
    return false;
  }
  const normalized = value.trim();
  if (normalized.length < 6) {
    return false;
  }
  const parsed = Date.parse(normalized);
  return !Number.isNaN(parsed);
}

export function normalizeCellValue(value: unknown): string | number | boolean | null {
  if (value === undefined || value === null || value === '') {
    return null;
  }
  if (value instanceof Date) {
    return value.toISOString();
  }
  if (typeof value === 'string') {
    return value.trim();
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return value;
  }
  return String(value);
}

export function truncateText(value: string, maxLength = 500): string {
  if (value.length <= maxLength) {
    return value;
  }
  return `${value.slice(0, maxLength - 1)}…`;
}

export function assertSelectOnly(sql: string): void {
  const normalized = sql.trim().toLowerCase();
  if (!(normalized.startsWith('select') || normalized.startsWith('with'))) {
    throw new Error('Solo se permiten consultas SELECT o WITH.');
  }
  const forbidden = [
    ' insert ',
    ' update ',
    ' delete ',
    ' drop ',
    ' alter ',
    ' truncate ',
    ' create ',
    ' grant ',
    ' revoke ',
    ' comment ',
    ' copy ',
  ];
  const padded = ` ${normalized.replace(/\s+/g, ' ')} `;
  for (const token of forbidden) {
    if (padded.includes(token)) {
      throw new Error('La consulta contiene una operación no permitida.');
    }
  }
}
