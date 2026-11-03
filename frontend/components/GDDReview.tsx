'use client';

import { useState, useSyncExternalStore } from 'react';
import APIKeyModal from './APIKeyModal';
import GenerationProgress from './GenerationProgress';
import { isNetworkError } from '../lib/api';
import { getUserApiKeySet, subscribeUserApiKey } from '../lib/apiKey';
import {
  COST_FIX_USD,
  COST_REVIEW_USD,
  addSessionSpend,
  formatCost,
  getSpendSnapshot,
  subscribeSpend,
} from '../lib/cost';
import {
  downloadBase64Pdf,
  downloadBlob,
  downloadGddPdf,
  downloadTextPdf,
  gddToMarkdown,
  gddToText,
  requestStyledPdf,
  slugifyFilename,
  type GddDownloadData,
  type GddFormat,
} from '../lib/download';
import { getLatestEntry, subscribeHistory, type HistoryEntry } from '../lib/history';
import { translateError, tr } from '../lib/i18n';
import { requestFix, requestReview, type FixResult, type ReviewResult } from '../lib/review';
import { useT } from '../lib/useT';

const DOC_TYPES = ['one_sheet', 'ten_pager', 'beat_chart', 'full_gdd'] as const;
const DOC_LABELS: Record<(typeof DOC_TYPES)[number], string> = {
  one_sheet: 'One-Sheet',
  ten_pager: 'Ten-Pager',
  beat_chart: 'Beat Chart',
  full_gdd: 'Full GDD',
};

const STATUS_BADGE: Record<string, string> = {
  ok: 'bg-emerald-900/40 text-emerald-400 border-emerald-500/30',
  weak: 'bg-amber-900/40 text-amber-400 border-amber-500/30',
  missing: 'bg-red-900/40 text-red-400 border-red-500/30',
};

function latestOrNull(): HistoryEntry | null {
  return getLatestEntry();
}

function scoreColor(score: number): string {
  if (score >= 8) return 'text-emerald-400 border-emerald-500/30';
  if (score >= 5) return 'text-amber-400 border-amber-500/30';
  return 'text-red-400 border-red-500/30';
}

export default function GDDReview() {
  const { t } = useT();
  const latest = useSyncExternalStore(subscribeHistory, latestOrNull, () => null);
  const hasKey = useSyncExternalStore(subscribeUserApiKey, getUserApiKeySet, () => false);
  const spend = useSyncExternalStore(subscribeSpend, getSpendSnapshot, () => 0);

  const [source, setSource] = useState<'last' | 'paste' | 'file'>('last');
  const [pasted, setPasted] = useState('');
  const [fileText, setFileText] = useState('');
  const [fileName, setFileName] = useState('');
  const [docType, setDocType] = useState<string>('one_sheet');
  const [auditing, setAuditing] = useState(false);
  const [fixing, setFixing] = useState(false);
  const [review, setReview] = useState<{ result: ReviewResult; document: string } | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [fix, setFix] = useState<FixResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [gddFormat, setGddFormat] = useState<GddFormat>('md');
  const [pdfBusy, setPdfBusy] = useState(false);
  const [keyOpen, setKeyOpen] = useState(false);

  const pickSource = (s: 'last' | 'paste' | 'file') => {
    setSource(s);
    if (s === 'last' && latest && (DOC_TYPES as readonly string[]).includes(latest.docType)) {
      setDocType(latest.docType);
    }
  };

  const onFile = (f: File | undefined) => {
    setError(null);
    if (!f) return;
    if (f.size > 200 * 1024) {
      setFileText('');
      setFileName('');
      setError(t('review.fileBig'));
      return;
    }
    f.text()
      .then((text) => {
        if (!text.trim()) {
          setFileText('');
          setFileName('');
          setError(t('review.badFile'));
          return;
        }
        setFileText(text);
        setFileName(f.name);
      })
      .catch(() => {
        setFileText('');
        setFileName('');
        setError(t('review.badFile'));
      });
  };

  const audit = async () => {
    const document =
      source === 'last'
        ? latest
          ? JSON.stringify(latest.gdd)
          : ''
        : source === 'file'
          ? fileText.trim()
          : pasted.trim();
    if (!document) {
      setError(t('review.emptyDoc'));
      return;
    }
    setAuditing(true);
    setError(null);
    setReview(null);
    setFix(null);
    try {
      const res = await requestReview(docType, document);
      if (res.status !== 'success') {
        setError(res.error ?? t('review.auditFailed'));
        return;
      }
      setReview({ result: res, document });
      setSelected(res.suggestions.map((s) => s.id));
      addSessionSpend(COST_REVIEW_USD);
    } catch (err) {
      setError(isNetworkError(err) ? t('err.coldStart') : t('review.net'));
    } finally {
      setAuditing(false);
    }
  };

  const applyFixes = async () => {
    if (!review) return;
    if (selected.length === 0) {
      setError(t('review.needSelection'));
      return;
    }
    setFixing(true);
    setError(null);
    setFix(null);
    try {
      const res = await requestFix(docType, review.document, review.result.suggestions, selected);
      if (res.status !== 'success') {
        setError(res.error ?? t('review.fixFailed'));
        return;
      }
      setFix(res);
      addSessionSpend(COST_FIX_USD);
    } catch (err) {
      setError(isNetworkError(err) ? t('err.coldStart') : t('review.net'));
    } finally {
      setFixing(false);
    }
  };

  const toggle = (id: string) =>
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  const downloadImprovedJson = () => {
    const data = fix?.improved_json as GddDownloadData | null | undefined;
    if (!data || pdfBusy) return;
    if (gddFormat === 'pdf-pro' || gddFormat === 'pdf-gamebook') {
      const style = gddFormat === 'pdf-pro' ? 'pro' : 'gamebook';
      const base = `gdd-review-${slugifyFilename(String(data.one_sheet?.title ?? 'document'))}`;
      setPdfBusy(true);
      requestStyledPdf(data, style, [])
        .then((res) => {
          if (res.status !== 'success') setError(res.error ?? tr('err.downloadGdd'));
          else downloadBase64Pdf(res.pdf_base64, `${base}-${gddFormat}.pdf`);
        })
        .catch(() => setError(tr('err.downloadGdd')))
        .finally(() => setPdfBusy(false));
      return;
    }
    try {
      const base = `gdd-review-${slugifyFilename(String(data.one_sheet?.title ?? 'document'))}`;
      if (gddFormat === 'json') {
        downloadBlob(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }), `${base}.json`);
      } else if (gddFormat === 'txt') {
        downloadBlob(new Blob([gddToText(data)], { type: 'text/plain' }), `${base}.txt`);
      } else if (gddFormat === 'pdf') {
        void downloadGddPdf(data, `${base}.pdf`).catch(() => setError(t('err.downloadGdd')));
      } else {
        downloadBlob(new Blob([gddToMarkdown(data)], { type: 'text/markdown' }), `${base}.md`);
      }
    } catch {
      setError(t('err.downloadGdd'));
    }
  };

  const downloadImprovedText = (ext: 'md' | 'txt') => {
    if (!fix?.improved_text) return;
    try {
      downloadBlob(
        new Blob([fix.improved_text], { type: ext === 'md' ? 'text/markdown' : 'text/plain' }),
        `gdd-review.${ext}`,
      );
    } catch {
      setError(t('err.downloadGdd'));
    }
  };

  const downloadImprovedTextPdf = () => {
    if (!fix?.improved_text) return;
    void downloadTextPdf(fix.improved_text, 'gdd-review.pdf').catch(() =>
      setError(t('err.downloadGdd')),
    );
  };

  const reset = () => {
    setReview(null);
    setFix(null);
    setError(null);
    setSelected([]);
  };

  const improved = fix?.improved_json as GddDownloadData | null | undefined;

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
      <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl h-fit space-y-4">
        <div className="flex justify-between items-center">
          <div className="flex gap-2">
            <button
              onClick={() => pickSource('last')}
              className={`px-3 py-1 rounded-lg text-xs font-semibold border transition ${
                source === 'last'
                  ? 'bg-blue-600 border-blue-600 text-white'
                  : 'bg-slate-950 border-slate-700 text-slate-300 hover:border-blue-500'
              }`}
            >
              {t('review.srcLast')}
            </button>
            <button
              onClick={() => pickSource('paste')}
              className={`px-3 py-1 rounded-lg text-xs font-semibold border transition ${
                source === 'paste'
                  ? 'bg-blue-600 border-blue-600 text-white'
                  : 'bg-slate-950 border-slate-700 text-slate-300 hover:border-blue-500'
              }`}
            >
              {t('review.srcPaste')}
            </button>
            <button
              onClick={() => pickSource('file')}
              className={`px-3 py-1 rounded-lg text-xs font-semibold border transition ${
                source === 'file'
                  ? 'bg-blue-600 border-blue-600 text-white'
                  : 'bg-slate-950 border-slate-700 text-slate-300 hover:border-blue-500'
              }`}
            >
              {t('review.srcFile')}
            </button>
          </div>
          <div className="flex items-center gap-2">
            {hasKey && <span className="text-xs text-emerald-400">{t('common.personalKeyActive')}</span>}
            <button
              onClick={() => setKeyOpen(true)}
              className="bg-slate-950 text-slate-300 border border-slate-700 hover:border-blue-500 px-2 py-1 rounded-lg text-xs font-semibold transition"
            >
              {t('common.apiKey')}
            </button>
          </div>
        </div>

        {source === 'last' ? (
          latest ? (
            <div className="bg-slate-950 border border-slate-800 rounded-lg p-3">
              <p className="text-sm text-slate-200 truncate">{latest.title}</p>
              <p className="text-xs text-slate-500 font-mono mt-1">{latest.docType}</p>
            </div>
          ) : (
            <p className="text-xs text-slate-500 italic">{t('review.noHistory')}</p>
          )
        ) : source === 'file' ? (
          <div className="space-y-2">
            <label className="block w-full cursor-pointer bg-slate-950 border border-dashed border-slate-700 hover:border-blue-500 rounded-lg p-4 text-center text-sm text-slate-300 transition">
              <input
                type="file"
                accept=".md,.txt,.json,text/markdown,text/plain,application/json"
                className="hidden"
                aria-label={t('review.srcFile')}
                onChange={(e) => {
                  onFile(e.target.files?.[0]);
                  e.target.value = '';
                }}
              />
              {fileName || t('review.filePh')}
            </label>
            {fileName && (
              <p className="text-xs text-slate-500 font-mono truncate">
                {fileName} · {(fileText.length / 1024).toFixed(1)} KB
              </p>
            )}
          </div>
        ) : (
          <textarea
            aria-label={t('review.srcPaste')}
            rows={8}
            placeholder={t('review.pastePh')}
            value={pasted}
            onChange={(e) => setPasted(e.target.value)}
            className="w-full bg-slate-950 border border-slate-800 rounded-lg p-3 text-sm text-slate-200 focus:outline-none focus:border-blue-500"
          />
        )}

        <div>
          <label className="block text-xs text-slate-400 mb-1">{t('form.docType')}</label>
          <select
            className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-sm text-slate-200 focus:outline-none focus:border-blue-500"
            value={docType}
            onChange={(e) => setDocType(e.target.value)}
          >
            {DOC_TYPES.map((d) => (
              <option key={d} value={d}>
                {DOC_LABELS[d]}
              </option>
            ))}
          </select>
        </div>

        <div className="flex gap-2">
          <button
            onClick={() => void audit()}
            disabled={auditing || fixing}
            className="flex-1 bg-blue-600 hover:bg-blue-500 disabled:bg-slate-800 text-white font-bold py-3 px-4 rounded-lg transition"
          >
            {auditing ? t('review.auditing') : t('review.audit')}
          </button>
          {review && (
            <button
              onClick={reset}
              disabled={auditing || fixing}
              className="bg-slate-950 text-slate-300 border border-slate-700 hover:border-blue-500 disabled:opacity-50 px-3 py-1 rounded-lg text-xs font-semibold transition"
            >
              {t('review.newAudit')}
            </button>
          )}
        </div>
        <p className="text-xs text-slate-500">
          {t('common.estimatedCost')}{' '}
          <span className="font-mono text-slate-400">
            {formatCost(COST_REVIEW_USD + COST_FIX_USD)}
          </span>{' '}
          · {t('common.session')} <span className="font-mono text-slate-400">{formatCost(spend)}</span>
        </p>

        {error && (
          <p className="text-xs text-red-400 bg-red-950/40 border border-red-500/30 rounded-lg p-3 break-words whitespace-pre-line">
            {translateError(error)}
          </p>
        )}
      </div>

      <div className="space-y-6">
        {(auditing || fixing) && (
          <GenerationProgress
            stages={[{ label: auditing ? t('review.auditing') : t('review.applying'), state: 'active' }]}
          />
        )}

        {review ? (
          <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl space-y-4">
            <div className="flex items-center gap-4">
              <span
                className={`text-3xl font-extrabold border rounded-xl px-4 py-2 ${scoreColor(review.result.score)}`}
              >
                {review.result.score}/10
              </span>
              <div>
                <p className="text-xs text-slate-500">{t('review.score')}</p>
                <p className="text-sm text-slate-300">{review.result.verdict}</p>
              </div>
            </div>

            <div>
              <h3 className="text-sm font-bold text-slate-300 mb-2">{t('review.checks')}</h3>
              <ul className="space-y-1">
                {review.result.checks.map((c, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm">
                    <span
                      className={`shrink-0 text-xs font-semibold border rounded-full px-2 py-0.5 ${STATUS_BADGE[c.status] ?? STATUS_BADGE.missing}`}
                    >
                      {t(
                        c.status === 'ok'
                          ? 'review.stOk'
                          : c.status === 'weak'
                            ? 'review.stWeak'
                            : 'review.stMissing',
                      )}
                    </span>
                    <span className="text-slate-300">
                      {c.item}
                      {c.detail && <span className="text-slate-500"> — {c.detail}</span>}
                    </span>
                  </li>
                ))}
              </ul>
            </div>

            <div>
              <div className="flex justify-between items-center mb-2">
                <h3 className="text-sm font-bold text-slate-300">{t('review.sugg')}</h3>
                {review.result.suggestions.length > 0 && (
                  <button
                    onClick={() =>
                      setSelected(
                        selected.length === review.result.suggestions.length
                          ? []
                          : review.result.suggestions.map((s) => s.id),
                      )
                    }
                    className="text-xs text-slate-400 hover:text-slate-200 transition"
                  >
                    {selected.length === review.result.suggestions.length
                      ? t('review.deselect')
                      : t('review.selectAll')}
                  </button>
                )}
              </div>
              {review.result.suggestions.length === 0 ? (
                <p className="text-xs text-emerald-400 italic">{t('review.noSugg')}</p>
              ) : (
                <ul className="space-y-2">
                  {review.result.suggestions.map((s) => (
                    <li key={s.id} className="bg-slate-950 border border-slate-800 rounded-lg p-3">
                      <label className="flex items-start gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          className="accent-blue-600 mt-1"
                          checked={selected.includes(s.id)}
                          onChange={() => toggle(s.id)}
                        />
                        <span>
                          <span className="block text-sm text-slate-200">
                            <span className="font-mono text-blue-400 text-xs">{s.id}</span>{' '}
                            {s.section && <strong>{s.section} — </strong>}
                            {s.issue}
                          </span>
                          <span className="block text-xs text-slate-400 mt-1">{s.proposal}</span>
                        </span>
                      </label>
                    </li>
                  ))}
                </ul>
              )}
              {review.result.suggestions.length > 0 && (
                <button
                  onClick={() => void applyFixes()}
                  disabled={fixing || auditing || selected.length === 0}
                  className="mt-3 w-full bg-blue-600 hover:bg-blue-500 disabled:bg-slate-800 text-white font-bold py-2 px-4 rounded-lg transition"
                >
                  {fixing
                    ? t('review.applying')
                    : t(selected.length === 1 ? 'review.applyOne' : 'review.applyMany', {
                        n: selected.length,
                      })}
                </button>
              )}
            </div>
          </div>
        ) : (
          !auditing && (
            <p className="text-xs text-slate-500 italic">{t('common.waiting')}</p>
          )
        )}

        {fix && fix.status === 'success' && (
          <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl space-y-3">
            <div className="flex flex-wrap justify-between items-center gap-2">
              <h2 className="text-lg font-bold text-emerald-400">{t('review.improved')}</h2>
              {fix.doc_format === 'json' ? (
                <div className="flex items-center gap-2">
                  <select
                    aria-label={t('gdd.ariaFormat')}
                    className="bg-slate-950 border border-slate-800 rounded-lg p-1 text-xs text-slate-200"
                    value={gddFormat}
                    onChange={(e) => setGddFormat(e.target.value as GddFormat)}
                  >
                    <option value="md">Markdown</option>
                    <option value="json">JSON</option>
                    <option value="txt">{t('common.textFormat')}</option>
                    <option value="pdf">PDF</option>
                    <option value="pdf-pro">PDF Pro</option>
                    <option value="pdf-gamebook">PDF Gamebook</option>
                  </select>
                  <button
                    onClick={downloadImprovedJson}
                    disabled={pdfBusy}
                    className="bg-blue-600 hover:bg-blue-500 disabled:bg-slate-800 text-white text-xs font-bold py-1 px-3 rounded-lg transition"
                  >
                    {pdfBusy ? '…' : t('common.download')}
                  </button>
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => downloadImprovedText('md')}
                    className="bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold py-1 px-3 rounded-lg transition"
                  >
                    MD
                  </button>
                  <button
                    onClick={() => downloadImprovedText('txt')}
                    className="bg-slate-950 text-slate-300 border border-slate-700 hover:border-blue-500 text-xs font-semibold py-1 px-3 rounded-lg transition"
                  >
                    TXT
                  </button>
                  <button
                    onClick={downloadImprovedTextPdf}
                    className="bg-slate-950 text-slate-300 border border-slate-700 hover:border-blue-500 text-xs font-semibold py-1 px-3 rounded-lg transition"
                  >
                    PDF
                  </button>
                </div>
              )}
            </div>
            <p className="text-xs text-slate-500">
              {t('review.applied')}{' '}
              <span className="font-mono text-slate-400">{fix.applied.join(', ')}</span>
            </p>
            {fix.doc_format === 'json' && improved ? (
              <div className="space-y-2 text-sm text-slate-300">
                <p>
                  <strong className="text-white">{t('common.title')}</strong>{' '}
                  {improved.one_sheet?.title}
                </p>
                <p>
                  <strong className="text-white">{t('common.summary')}</strong>{' '}
                  {improved.one_sheet?.story_summary}
                </p>
                {(improved.one_sheet?.usps?.length ?? 0) > 0 && (
                  <ul className="list-disc list-inside space-y-1 text-slate-400">
                    {improved.one_sheet?.usps?.map((u: string, i: number) => (
                      <li key={i}>{u}</li>
                    ))}
                  </ul>
                )}
              </div>
            ) : (
              <pre className="bg-slate-950 p-4 rounded-lg text-xs text-slate-300 overflow-x-auto border border-slate-800 whitespace-pre-wrap">
                {fix.improved_text}
              </pre>
            )}
          </div>
        )}
      </div>
      {keyOpen && <APIKeyModal onClose={() => setKeyOpen(false)} />}
    </div>
  );
}
