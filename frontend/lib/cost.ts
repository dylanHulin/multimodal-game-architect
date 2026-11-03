/* Cost estimates (documented, honest): shown with ~ everywhere, never billed amounts.

Observed Meta pricing: images ~$0.01, SAM $2.50/1k images, voice $0.18/h audio.
Text estimates below are rough orders of magnitude for a GDD/code completion.
*/

export const COST_IMAGE_USD = 0.01;
export const COST_CODE_USD = 0.02;
export const COST_CUTOUT_USD = 0.0025;
export const COST_TRANSCRIBE_USD = 0.001;
export const COST_MUSIC_USD = 0.035; // Replicate page: meta/musicgen ~$0.033/run
export const COST_REVIEW_USD = 0.03; // Wonder audit pass: rough per-run estimate
export const COST_FIX_USD = 0.04; // Wonder fix pass (longer output): rough estimate

const COST_GDD: Record<string, number> = {
  one_sheet: 0.02,
  ten_pager: 0.035,
  beat_chart: 0.03,
  full_gdd: 0.06,
};

export function estimateGdd(docType: string): number {
  return COST_GDD[docType] ?? 0.03;
}

export function estimateRun(docType: string, imageCount: number, withCode: boolean): number {
  return estimateGdd(docType) + imageCount * COST_IMAGE_USD + (withCode ? COST_CODE_USD : 0);
}

export function formatCost(usd: number): string {
  const digits = usd > 0 && usd < 0.01 ? 4 : 2;
  return `~${usd.toFixed(digits)} $`;
}

const SPEND_KEY = 'mgh_spend_micro';

function readMicro(): number {
  if (typeof window === 'undefined') return 0;
  const raw = Number(window.localStorage.getItem(SPEND_KEY) ?? 0);
  return Number.isFinite(raw) && raw > 0 ? Math.round(raw) : 0;
}

type Listener = () => void;
const listeners = new Set<Listener>();
let cachedMicro: number | null = null;

export function subscribeSpend(fn: Listener): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

export function getSpendSnapshot(): number {
  if (cachedMicro === null) cachedMicro = readMicro();
  return cachedMicro / 1_000_000;
}

export function getSessionSpend(): number {
  return getSpendSnapshot();
}

export function addSessionSpend(usd: number): number {
  if (typeof window === 'undefined' || !(usd > 0)) return getSpendSnapshot();
  cachedMicro = Math.round(getSpendSnapshot() * 1_000_000 + usd * 1_000_000);
  try {
    window.localStorage.setItem(SPEND_KEY, String(cachedMicro));
  } catch {
    /* storage full/blocked: spend tracking is best-effort */
  }
  listeners.forEach((fn) => fn());
  return cachedMicro / 1_000_000;
}
