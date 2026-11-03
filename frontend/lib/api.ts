/* Shared backend client (BYOK-aware via authHeaders). */

import { authHeaders } from './apiKey';

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://127.0.0.1:8000';

export async function apiPost<T>(
  path: string,
  body: unknown,
  extraHeaders?: Record<string, string>,
): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders(), ...extraHeaders },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`${path} failed: ${res.status} ${res.statusText} ${text.slice(0, 300)}`);
  }
  return (await res.json()) as T;
}
