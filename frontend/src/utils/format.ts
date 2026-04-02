export function normalizeBase(url: string): string {
  return (url || '').trim().replace(/\/$/, '');
}

export function csvToArray(value: string): string[] {
  return value
    .split(',')
    .map((v) => v.trim())
    .filter(Boolean);
}

export function pretty(value: unknown): string {
  return JSON.stringify(value ?? {}, null, 2);
}

export function asText(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined;
}
