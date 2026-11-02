'use client';

import { useEffect, useState } from 'react';

export interface ProgressStage {
  label: string;
  state: 'pending' | 'active' | 'done';
}

const DOT: Record<ProgressStage['state'], string> = {
  done: 'bg-emerald-500',
  active: 'bg-blue-500 animate-pulse',
  pending: 'bg-slate-700',
};

export default function GenerationProgress({ stages }: { stages: ProgressStage[] }) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const t0 = Date.now();
    const timer = window.setInterval(
      () => setElapsed(Math.floor((Date.now() - t0) / 1000)),
      500,
    );
    return () => window.clearInterval(timer);
  }, []);

  return (
    <div
      aria-live="polite"
      className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs bg-slate-950 border border-slate-800 rounded-lg px-3 py-2"
    >
      {stages.map((s) => (
        <span key={s.label} className="flex items-center gap-2">
          <span className={`inline-block w-2 h-2 rounded-full ${DOT[s.state]}`} />
          <span className={s.state === 'done' ? 'text-slate-200' : 'text-slate-400'}>
            {s.label}
          </span>
        </span>
      ))}
      <span className="ml-auto font-mono text-slate-500">{elapsed} s</span>
    </div>
  );
}
