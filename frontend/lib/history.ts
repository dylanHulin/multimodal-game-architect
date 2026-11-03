/* Local generation history (localStorage): GDD + code in full, visuals as
thumbnails to stay under quota. Restoring an entry repopulates the results.
Exposed as an external store so panels stay in sync without effects. */

import { imageToThumbnail, type GddDownloadData } from './download';

export interface HistoryImage {
  asset_type: string;
  prompt_used: string;
  image_url: string;
  status: string;
}

export interface HistoryCode {
  engine: string;
  file_name: string;
  language: string;
  code_content: string;
  status?: string;
}

export interface HistoryEntry {
  id: string;
  ts: number;
  page: 'main' | 'form';
  title: string;
  docType: string;
  gdd: GddDownloadData;
  code: HistoryCode | null;
  images: HistoryImage[];
}

export type HistoryPage = 'main' | 'form';

const MAX_ENTRIES = 8;

function keyOf(page: HistoryPage): string {
  return `mgh_history_${page}`;
}

function readStored(page: HistoryPage): HistoryEntry[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = window.localStorage.getItem(keyOf(page));
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? (parsed as HistoryEntry[]) : [];
  } catch {
    return [];
  }
}

type Listener = () => void;
const listeners = new Set<Listener>();
const cache: Record<HistoryPage, HistoryEntry[]> = { main: [], form: [] };
const cacheReady: Record<HistoryPage, boolean> = { main: false, form: false };

function emit(): void {
  listeners.forEach((fn) => fn());
}

export function subscribeHistory(fn: Listener): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

export function getHistorySnapshot(page: HistoryPage): HistoryEntry[] {
  if (!cacheReady[page]) {
    cache[page] = readStored(page);
    cacheReady[page] = true;
  }
  return cache[page];
}

function persist(page: HistoryPage, entries: HistoryEntry[]): HistoryEntry[] {
  cache[page] = entries.slice(0, MAX_ENTRIES);
  cacheReady[page] = true;
  try {
    window.localStorage.setItem(keyOf(page), JSON.stringify(cache[page]));
  } catch {
    // Quota exceeded: keep only the newest half and retry once.
    cache[page] = cache[page].slice(0, Math.max(1, Math.floor(MAX_ENTRIES / 2)));
    try {
      window.localStorage.setItem(keyOf(page), JSON.stringify(cache[page]));
    } catch {
      /* storage unusable: history is best-effort */
    }
  }
  emit();
  return cache[page];
}

async function thumb(src: string): Promise<string> {
  try {
    return await imageToThumbnail(src);
  } catch {
    return src;
  }
}

export async function pushHistory(
  page: HistoryPage,
  entry: Omit<HistoryEntry, 'id' | 'ts' | 'page'>,
): Promise<void> {
  const images: HistoryImage[] = [];
  for (const img of entry.images) {
    images.push({ ...img, image_url: await thumb(img.image_url) });
  }
  persist(page, [
    {
      ...entry,
      images,
      page,
      id: `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
      ts: Date.now(),
    },
    ...getHistorySnapshot(page),
  ]);
}

export function getLatestEntry(): HistoryEntry | null {
  const all = [...getHistorySnapshot('main'), ...getHistorySnapshot('form')];
  if (all.length === 0) return null;
  return all.reduce((a, b) => (b.ts > a.ts ? b : a));
}

export function deleteHistoryEntry(page: HistoryPage, id: string): void {
  persist(
    page,
    getHistorySnapshot(page).filter((e) => e.id !== id),
  );
}
