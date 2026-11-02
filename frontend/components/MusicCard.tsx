'use client';

import { useState, useSyncExternalStore } from 'react';
import { getReplicateApiKeySet, subscribeReplicateApiKey } from '../lib/apiKey';
import { COST_MUSIC_USD, addSessionSpend, formatCost } from '../lib/cost';
import { slugifyFilename } from '../lib/download';
import { translateError } from '../lib/i18n';
import { useT } from '../lib/useT';
import {
  MUSIC_DURATIONS,
  MUSIC_STYLES,
  downloadDataUrl,
  mp3DataUrl,
  requestMp3,
  requestMusic,
  wavDataUrl,
} from '../lib/music';

function BillingBadge() {
  const { t } = useT();
  const hasRepKey = useSyncExternalStore(
    subscribeReplicateApiKey,
    getReplicateApiKeySet,
    () => false,
  );
  return (
    <span className="text-xs text-slate-500" title={t('music.billingHint')}>
      {formatCost(COST_MUSIC_USD)} ·{' '}
      <span className={hasRepKey ? 'text-emerald-400' : 'text-slate-400'}>
        {hasRepKey ? t('music.billingOwn') : t('music.billingServer')}
      </span>
    </span>
  );
}

export default function MusicCard() {
  const { t } = useT();
  const [prompt, setPrompt] = useState('');
  const [style, setStyle] = useState(MUSIC_STYLES[0]);
  const [duration, setDuration] = useState(MUSIC_DURATIONS[1]);
  const [busy, setBusy] = useState(false);
  const [mp3Busy, setMp3Busy] = useState(false);
  const [track, setTrack] = useState<{ src: string; secs: number; prompt: string } | null>(
    null,
  );
  const [trackB64, setTrackB64] = useState('');
  const [message, setMessage] = useState<string | null>(null);

  const generate = async () => {
    if (!prompt.trim() || busy) return;
    setBusy(true);
    setMessage(null);
    setTrack(null);
    try {
      const res = await requestMusic(prompt.trim(), style, duration);
      if (res.status !== 'success') {
        setMessage(res.error ?? t('music.failed'));
        return;
      }
      addSessionSpend(COST_MUSIC_USD);
      setTrackB64(res.audio_base64);
      setTrack({
        src: wavDataUrl(res.audio_base64),
        secs: res.duration_sec,
        prompt: res.prompt_used,
      });
    } catch {
      setMessage(t('music.net'));
    } finally {
      setBusy(false);
    }
  };

  const fileBase = `${t('music.fileBase')}-${slugifyFilename(prompt) || 'concept'}`;

  const downloadWav = () => {
    if (track) downloadDataUrl(track.src, `${fileBase}.wav`);
  };

  const downloadMp3 = async () => {
    if (!trackB64 || mp3Busy) return;
    setMp3Busy(true);
    try {
      const res = await requestMp3(trackB64);
      if (res.status !== 'success') {
        setMessage(res.error ?? t('music.mp3Failed'));
        return;
      }
      downloadDataUrl(mp3DataUrl(res.audio_base64), `${fileBase}.mp3`);
    } catch {
      setMessage(t('music.mp3Net'));
    } finally {
      setMp3Busy(false);
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl space-y-3">
      <div className="flex flex-wrap justify-between items-center gap-2">
        <h2 className="text-lg font-bold text-blue-400">{t('music.title')}</h2>
        <BillingBadge />
      </div>
      <input
        aria-label={t('music.title')}
        className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-sm text-slate-200 focus:outline-none focus:border-blue-500"
        placeholder={t('music.placeholder')}
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
      />
      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label={t('main.styleLabel')}
          className="bg-slate-950 border border-slate-800 rounded-lg p-1 text-xs text-slate-200"
          value={style}
          onChange={(e) => setStyle(e.target.value)}
        >
          {MUSIC_STYLES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <select
          aria-label={t('music.duration')}
          className="bg-slate-950 border border-slate-800 rounded-lg p-1 text-xs text-slate-200"
          value={duration}
          onChange={(e) => setDuration(Number(e.target.value))}
        >
          {MUSIC_DURATIONS.map((d) => (
            <option key={d} value={d}>
              {d} s
            </option>
          ))}
        </select>
        <button
          onClick={() => void generate()}
          disabled={busy || !prompt.trim()}
          className="bg-blue-600 hover:bg-blue-500 disabled:bg-slate-800 text-white text-xs font-bold py-1 px-3 rounded-lg transition"
        >
          {busy ? t('music.composing') : t('music.generate')}
        </button>
      </div>
      {message && <p className="text-xs text-amber-400">{translateError(message)}</p>}
      {track ? (
        <div className="space-y-2">
          <p className="text-xs text-slate-400 truncate" title={track.prompt}>
            {track.prompt} · {track.secs.toFixed(0)} s · {t('music.loop')}
          </p>
          <audio controls loop src={track.src} className="w-full" />
          <div className="flex items-center gap-2">
            <button
              onClick={downloadWav}
              className="bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold py-1 px-3 rounded-lg transition"
            >
              WAV
            </button>
            <button
              onClick={() => void downloadMp3()}
              disabled={mp3Busy}
              className="bg-slate-950 text-slate-300 border border-slate-700 hover:border-blue-500 disabled:opacity-50 text-xs font-semibold py-1 px-3 rounded-lg transition"
            >
              {mp3Busy ? '…' : 'MP3'}
            </button>
          </div>
        </div>
      ) : (
        !busy && <p className="text-xs text-slate-500 italic">{t('music.waiting')}</p>
      )}
    </div>
  );
}
