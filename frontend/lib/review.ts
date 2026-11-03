/* GDD review client: audit against the Rogers checklist, then apply fixes. */

import { apiPost } from './api';

export interface ReviewCheck {
  item: string;
  status: string; // ok | weak | missing
  detail: string;
}

export interface ReviewSuggestion {
  id: string;
  section: string;
  issue: string;
  proposal: string;
}

export interface ReviewResult {
  status: string;
  score: number;
  verdict: string;
  checks: ReviewCheck[];
  suggestions: ReviewSuggestion[];
  error?: string | null;
}

export interface FixResult {
  status: string;
  doc_format: string; // json | text
  improved_json: Record<string, unknown> | null;
  improved_text: string;
  applied: string[];
  error?: string | null;
}

export function requestReview(docType: string, document: string): Promise<ReviewResult> {
  return apiPost<ReviewResult>('/api/v1/review-gdd', { doc_type: docType, document });
}

export function requestFix(
  docType: string,
  document: string,
  suggestions: ReviewSuggestion[],
  applyIds: string[],
): Promise<FixResult> {
  return apiPost<FixResult>('/api/v1/fix-gdd', {
    doc_type: docType,
    document,
    suggestions,
    apply_ids: applyIds,
  });
}
