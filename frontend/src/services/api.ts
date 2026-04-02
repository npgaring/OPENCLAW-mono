import type { JsonMap } from '../types/governed';
import { normalizeBase } from '../utils/format';

function readErrorMessage(parsed: unknown, status: number): string {
  if (typeof parsed === 'object' && parsed !== null) {
    const bag = parsed as JsonMap;
    const detail = bag.detail;
    if (typeof detail === 'string') return detail;
    if (typeof detail === 'object' && detail !== null) {
      const msg = (detail as JsonMap).message;
      if (typeof msg === 'string') return msg;
    }
    const msg = bag.message;
    if (typeof msg === 'string') return msg;
  }
  return `HTTP ${status}`;
}

export async function request<T>(
  base: string,
  path: string,
  method: 'GET' | 'POST',
  apiToken: string,
  body?: JsonMap,
): Promise<T> {
  const url = `${normalizeBase(base)}${path}`;
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (apiToken.trim()) {
    headers.Authorization = `Bearer ${apiToken.trim()}`;
  }
  const res = await fetch(url, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let parsed: unknown = {};
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = { raw: text };
    }
  }
  if (!res.ok) {
    throw new Error(readErrorMessage(parsed, res.status));
  }
  return parsed as T;
}
