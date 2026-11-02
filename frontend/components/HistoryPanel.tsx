'use client';

import { useState, useSyncExternalStore } from 'react';
import {
  deleteHistoryEntry,
  getHistorySnapshot,
  subscribeHistory,
  type HistoryEntry,
  type HistoryPage,
} from '../lib/history';
import { LOCALES } from '../lib/i18n';
import { useT } from '../lib/useT';

function fmtDate(ts: number, locale: string): string {
  return new Date(ts).toLocaleString(locale, {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

// Stable server snapshot: useSyncExternalStore requires a cached value.
const EMPTY_HISTORY: HistoryEntry[] = [];
function getServerSnapshot(): HistoryEntry[] {
  return EMPTY_HISTORY;
}

export default function HistoryPanel({
  page,
  onRestore,
}: {
  page: HistoryPage;
  onRestore: (entry: HistoryEntry) => void;
}) {
  const { lang, t } = useT();
  const [open, setOpen] = useState(false);
  const entries = useSyncExternalStore(
    subscribeHistory,
    () => getHistorySnapshot(page),
    getServerSnapshot,
  );

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex justify-between items-center p-4 text-sm font-bold text-slate-200"
      >
        <span>{t('hist.title')}</span>
        <span className="text-xs font-mono text-slate-500">
          {entries.length} · {open ? '−' : '+'}
        </span>
      </button>
      {open && (
        <div className="px-4 pb-4 space-y-2">
          {entries.length === 0 && (
            <p className="text-xs text-slate-500 italic">{t('hist.empty')}</p>
          )}
          {entries.map((e) => (
            <div
              key={e.id}
              className="flex items-center gap-3 bg-slate-950 border border-slate-800 rounded-lg p-2"
            >
              {e.images[0] ? (
                <img
                  src={e.images[0].image_url}
                  alt=""
                  className="w-12 h-12 object-cover rounded border border-slate-800"
                />
              ) : (
                <div className="w-12 h-12 rounded border border-slate-800 bg-slate-900" />
              )}
              <div className="flex-1 min-w-0">
                <p className="text-sm text-slate-200 truncate">{e.title}</p>
                <p className="text-xs text-slate-500 font-mono">
                  {e.docType} · {fmtDate(e.ts, LOCALES[lang])}
                </p>
              </div>
              <button
                onClick={() => onRestore(e)}
                className="bg-slate-900 text-slate-200 border border-slate-700 hover:border-blue-500 px-2 py-1 rounded-lg text-xs font-semibold transition"
              >
                {t('hist.reload')}
              </button>
              <button
                onClick={() => deleteHistoryEntry(page, e.id)}
                aria-label={t('hist.delete', { t: e.title })}
                className="text-slate-600 hover:text-red-400 text-sm px-1 transition"
              >
                ×
              </button>
            </div>
          ))}
          {entries.length > 0 && (
            <p className="text-xs text-slate-600">{t('hist.thumbs')}</p>
          )}
        </div>
      )}
    </div>
  );
}
