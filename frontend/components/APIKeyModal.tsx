'use client';

import { useState, useSyncExternalStore } from 'react';
import {
  getReplicateApiKeySet,
  getUserApiKeySet,
  setReplicateApiKey,
  setUserApiKey,
  subscribeReplicateApiKey,
  subscribeUserApiKey,
} from '../lib/apiKey';
import { useT } from '../lib/useT';

export default function APIKeyModal({ onClose }: { onClose: () => void }) {
  const { t } = useT();
  const [metaValue, setMetaValue] = useState('');
  const [repValue, setRepValue] = useState('');
  const hasMeta = useSyncExternalStore(subscribeUserApiKey, getUserApiKeySet, () => false);
  const hasRep = useSyncExternalStore(
    subscribeReplicateApiKey,
    getReplicateApiKeySet,
    () => false,
  );

  const save = () => {
    if (metaValue.trim()) setUserApiKey(metaValue.trim());
    if (repValue.trim()) setReplicateApiKey(repValue.trim());
    onClose();
  };

  const inputClass =
    'w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-sm text-slate-200 focus:outline-none focus:border-blue-500';

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={t('modal.title')}
    >
      <div
        className="w-full max-w-md bg-slate-900 border border-slate-700 rounded-xl p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-bold text-slate-100">{t('modal.title')}</h2>
        <p className="text-xs text-slate-400 mt-1 mb-4">{t('modal.desc')}</p>

        <div className="flex items-center justify-between mb-1">
          <label className="block text-xs text-slate-400" htmlFor="byok-meta">
            {t('modal.metaLabel')}
          </label>
          {hasMeta && (
            <button
              onClick={() => setUserApiKey(null)}
              className="text-xs text-red-400 hover:text-red-300"
            >
              {t('common.remove')}
            </button>
          )}
        </div>
        <input
          id="byok-meta"
          type="password"
          autoComplete="off"
          placeholder={hasMeta ? t('modal.configured') : t('modal.metaPlaceholder')}
          className={inputClass}
          value={metaValue}
          onChange={(e) => setMetaValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') save();
          }}
        />

        <div className="flex items-center justify-between mb-1 mt-4">
          <label className="block text-xs text-slate-400" htmlFor="byok-replicate">
            {t('modal.repLabel')}
          </label>
          {hasRep && (
            <button
              onClick={() => setReplicateApiKey(null)}
              className="text-xs text-red-400 hover:text-red-300"
            >
              {t('common.remove')}
            </button>
          )}
        </div>
        <input
          id="byok-replicate"
          type="password"
          autoComplete="off"
          placeholder={hasRep ? t('modal.configured') : t('modal.repPlaceholder')}
          className={inputClass}
          value={repValue}
          onChange={(e) => setRepValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') save();
          }}
        />

        <div className="flex justify-end gap-2 mt-5">
          <button
            onClick={onClose}
            className="bg-slate-950 text-slate-300 border border-slate-700 hover:border-slate-500 px-3 py-1 rounded-lg text-sm font-semibold transition"
          >
            {t('common.cancel')}
          </button>
          <button
            onClick={save}
            disabled={!metaValue.trim() && !repValue.trim()}
            className="bg-blue-600 hover:bg-blue-500 disabled:bg-slate-800 disabled:text-slate-500 text-white px-3 py-1 rounded-lg text-sm font-bold transition"
          >
            {t('common.save')}
          </button>
        </div>
      </div>
    </div>
  );
}
