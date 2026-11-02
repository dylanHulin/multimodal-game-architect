'use client';

import { useState } from 'react';
import { COST_CUTOUT_USD, addSessionSpend } from '../lib/cost';
import { compositeCutout, requestCutout } from '../lib/cutout';
import { blobToDataUrl, downloadImage } from '../lib/download';
import { translateError } from '../lib/i18n';
import { useT } from '../lib/useT';

const CHECKER = {
  backgroundImage: 'repeating-conic-gradient(#1e293b 0 25%, #0f172a 0 50%)',
  backgroundSize: '16px 16px',
} as const;

export default function CutoutPanel({
  imageUrl,
  fileBase,
}: {
  imageUrl: string;
  fileBase: string;
}) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const [concept, setConcept] = useState('character');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="bg-slate-950 text-slate-300 border border-slate-700 hover:border-blue-500 text-xs font-semibold py-1 px-3 rounded-lg transition"
      >
        {t('cut.title')}
      </button>
    );
  }

  const run = async () => {
    setBusy(true);
    setMessage(null);
    setResult(null);
    try {
      // SAM needs the pixels inline: resolve remote/relative URLs to a data URL
      // client-side so the backend never has to fetch (works for /demo/*.webp).
      let dataUrl = imageUrl;
      if (!dataUrl.startsWith('data:')) {
        const res = await fetch(dataUrl);
        if (!res.ok) throw new Error('fetch');
        dataUrl = await blobToDataUrl(await res.blob());
      }
      const res = await requestCutout(dataUrl, concept.trim() || 'character');
      if (res.status === 'no_match') {
        setMessage(t('cut.noMatch', { c: res.concept || concept }));
        return;
      }
      if (res.status !== 'success') {
        setMessage(res.error ?? t('cut.failed'));
        return;
      }
      setResult(await compositeCutout(dataUrl, res.masks, res.boxes));
      addSessionSpend(COST_CUTOUT_USD);
    } catch {
      setMessage(t('cut.net'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-2 bg-slate-950 border border-slate-800 rounded-lg p-3">
      <div className="flex flex-wrap items-center gap-2">
        <input
          aria-label={t('cut.aria')}
          className="flex-1 min-w-32 bg-slate-900 border border-slate-800 rounded-lg p-1 text-xs text-slate-200 focus:outline-none focus:border-blue-500"
          value={concept}
          onChange={(e) => setConcept(e.target.value)}
          placeholder="character"
        />
        <button
          onClick={() => void run()}
          disabled={busy}
          className="bg-blue-600 hover:bg-blue-500 disabled:bg-slate-800 text-white text-xs font-bold py-1 px-3 rounded-lg transition"
        >
          {busy ? t('cut.running') : t('common.launch')}
        </button>
        <button
          onClick={() => setOpen(false)}
          className="text-slate-500 hover:text-slate-300 text-xs transition"
        >
          {t('common.close')}
        </button>
      </div>
      {message && <p className="text-xs text-amber-400">{translateError(message)}</p>}
      {result && (
        <div className="space-y-2">
          <img
            src={result}
            alt={t('cut.alt')}
            style={CHECKER}
            className="w-full max-w-sm rounded-lg border border-slate-800"
          />
          <button
            onClick={() => void downloadImage(result, `${fileBase}-cutout`, 'png')}
            className="bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold py-1 px-3 rounded-lg transition"
          >
            {t('cut.png')}
          </button>
        </div>
      )}
    </div>
  );
}
