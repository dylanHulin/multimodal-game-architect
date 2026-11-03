/* BYOK helpers: user-provided Meta API key persisted in localStorage,
   exposed as an external store so badges stay in sync without effects. */

export const USER_API_KEY_NAME = 'user_api_key';

export function getUserApiKey(): string | null {
  if (typeof window === 'undefined') return null;
  const v = window.localStorage.getItem(USER_API_KEY_NAME);
  return v && v.trim() ? v.trim() : null;
}

type Listener = () => void;
const listeners = new Set<Listener>();

export function subscribeUserApiKey(fn: Listener): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

export function getUserApiKeySet(): boolean {
  return getUserApiKey() !== null;
}

export function setUserApiKey(value: string | null): void {
  if (value && value.trim()) {
    window.localStorage.setItem(USER_API_KEY_NAME, value.trim());
  } else {
    window.localStorage.removeItem(USER_API_KEY_NAME);
  }
  listeners.forEach((fn) => fn());
}

export function authHeaders(): Record<string, string> {
  const key = getUserApiKey();
  return key ? { Authorization: `Bearer ${key}` } : {};
}

export const REPLICATE_API_KEY_NAME = 'replicate_api_key';

export function getReplicateApiKey(): string | null {
  if (typeof window === 'undefined') return null;
  const v = window.localStorage.getItem(REPLICATE_API_KEY_NAME);
  return v && v.trim() ? v.trim() : null;
}

const repListeners = new Set<Listener>();

export function subscribeReplicateApiKey(fn: Listener): () => void {
  repListeners.add(fn);
  return () => {
    repListeners.delete(fn);
  };
}

export function getReplicateApiKeySet(): boolean {
  return getReplicateApiKey() !== null;
}

export function setReplicateApiKey(value: string | null): void {
  if (value && value.trim()) {
    window.localStorage.setItem(REPLICATE_API_KEY_NAME, value.trim());
  } else {
    window.localStorage.removeItem(REPLICATE_API_KEY_NAME);
  }
  repListeners.forEach((fn) => fn());
}

export function replicateHeaders(): Record<string, string> {
  const key = getReplicateApiKey();
  return key ? { 'X-Replicate-Key': key } : {};
}
