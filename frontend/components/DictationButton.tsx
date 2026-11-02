'use client';

import { useEffect, useRef, useState } from 'react';
import { COST_TRANSCRIBE_USD, addSessionSpend } from '../lib/cost';
import { startDictation, transcribeWav, type DictationSession } from '../lib/voice';

function MicIcon({ recording }: { recording: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      className="w-4 h-4"
      aria-hidden="true"
    >
      <rect x="9" y="2" width="6" height="12" rx="3" fill={recording ? 'currentColor' : 'none'} />
      <path d="M5 10a7 7 0 0 0 14 0" />
      <path d="M12 17v4" />
    </svg>
  );
}

export default function DictationButton({
  onText,
  maxSeconds = 30,
}: {
  onText: (text: string) => void;
  maxSeconds?: number;
}) {
  const [state, setState] = useState<'idle' | 'recording' | 'working'>('idle');
  const [error, setError] = useState<string | null>(null);
  const session = useRef<DictationSession | null>(null);

  useEffect(() => () => session.current?.cancel(), []);

  const finish = async () => {
    const s = session.current;
    session.current = null;
    if (!s) {
      setState('idle');
      return;
    }
    setState('working');
    try {
      const wav = await s.stop();
      const res = await transcribeWav(wav);
      if (res.status !== 'success' || !res.transcript.trim()) {
        setError(res.error ?? 'Aucune parole détectée.');
      } else {
        addSessionSpend(COST_TRANSCRIBE_USD);
        onText(res.transcript.trim());
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Dictée impossible.');
    } finally {
      setState('idle');
    }
  };

  const toggle = async () => {
    if (state === 'recording') {
      await finish();
      return;
    }
    if (state !== 'idle') return;
    setError(null);
    try {
      session.current = await startDictation(maxSeconds, () => void finish());
      setState('recording');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Dictée impossible.');
    }
  };

  return (
    <span className="inline-flex items-center gap-2">
      <button
        onClick={() => void toggle()}
        disabled={state === 'working'}
        title={state === 'recording' ? 'Arrêter et transcrire' : 'Dicter au micro (Muse Voice)'}
        aria-label={state === 'recording' ? 'Arrêter la dictée' : 'Dicter au micro'}
        className={`p-1.5 rounded-lg border transition ${
          state === 'recording'
            ? 'bg-red-950/60 text-red-400 border-red-500/50 animate-pulse'
            : 'bg-slate-950 text-slate-400 border-slate-800 hover:border-blue-500 hover:text-slate-200'
        }`}
      >
        <MicIcon recording={state === 'recording'} />
      </button>
      {state === 'working' && <span className="text-xs text-slate-500">Transcription…</span>}
      {state === 'recording' && <span className="text-xs text-red-400">Écoute…</span>}
      {error && <span className="text-xs text-amber-400">{error}</span>}
    </span>
  );
}
