'use client';

import { use, useState } from 'react';
import { loadBundle, loadManifest, type DemoBundle, type DemoManifestEntry } from '../lib/demo';

let cachedManifest: Promise<DemoManifestEntry[]> | null = null;

function manifest(): Promise<DemoManifestEntry[]> {
  if (!cachedManifest) cachedManifest = loadManifest().catch(() => []);
  return cachedManifest;
}

export default function ExamplesRow({ onLoad }: { onLoad: (bundle: DemoBundle) => void }) {
  const entries = use(manifest());
  const [busy, setBusy] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  if (entries.length === 0) return null;

  const load = async (entry: DemoManifestEntry) => {
    setBusy(entry.id);
    setFailed(false);
    try {
      onLoad(await loadBundle(entry));
    } catch {
      setFailed(true);
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="max-w-6xl mx-auto mb-8">
      <div className="flex items-center gap-3 mb-3">
        <h2 className="text-lg font-bold text-slate-200">Exemples instantanés</h2>
        <span className="bg-emerald-900/40 text-emerald-400 border border-emerald-500/30 px-2 py-0.5 rounded-full text-xs font-semibold">
          0 $ · sans réseau Meta
        </span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {entries.map((e) => (
          <button
            key={e.id}
            onClick={() => void load(e)}
            disabled={busy !== null}
            className="flex items-center gap-4 text-left bg-slate-900 border border-slate-800 hover:border-blue-500 disabled:opacity-60 rounded-xl p-3 transition"
          >
            <img
              src={e.thumb}
              alt=""
              className="w-20 h-20 object-cover rounded-lg border border-slate-800 bg-slate-950"
            />
            <span>
              <span className="block text-sm font-bold text-slate-100">
                {busy === e.id ? 'Chargement…' : e.title}
              </span>
              <span className="block text-xs text-slate-500 font-mono mt-1">
                {e.genre} · {e.docType} · {e.engine}
              </span>
            </span>
          </button>
        ))}
      </div>
      {failed && <p className="text-xs text-amber-400 mt-2">Exemple illisible.</p>}
    </section>
  );
}
