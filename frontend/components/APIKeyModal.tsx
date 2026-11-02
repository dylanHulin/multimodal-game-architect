'use client';

import { useState } from 'react';
import { getUserApiKey, setUserApiKey } from '../lib/apiKey';

export default function APIKeyModal({ onClose }: { onClose: () => void }) {
  const [value, setValue] = useState('');
  // Read on render: the modal only ever mounts from a click (post-hydration),
  // and the parent remounts it on every open so state starts fresh.
  const hasKey = getUserApiKey() !== null;

  const save = () => {
    const v = value.trim();
    if (!v) return;
    setUserApiKey(v);
    onClose();
  };

  const clear = () => {
    setUserApiKey(null);
    onClose();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Clé API personnelle"
    >
      <div
        className="w-full max-w-md bg-slate-900 border border-slate-700 rounded-xl p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-bold text-slate-100">Clé API personnelle</h2>
        <p className="text-xs text-slate-400 mt-1 mb-4">
          Utilisée pour les appels Meta à la place de la clé serveur. Stockée uniquement dans
          ce navigateur, jamais sur le serveur.
        </p>
        {hasKey && (
          <p className="text-xs text-emerald-400 bg-emerald-950/40 border border-emerald-500/30 rounded-lg p-2 mb-4">
            Une clé est déjà configurée — enregistrer une nouvelle clé la remplace.
          </p>
        )}
        <label className="block text-xs text-slate-400 mb-1" htmlFor="byok-key">
          Clé API Meta
        </label>
        <input
          id="byok-key"
          type="password"
          autoComplete="off"
          placeholder="Collez votre clé ici"
          className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-sm text-slate-200 focus:outline-none focus:border-blue-500"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') save();
          }}
        />
        <div className="flex justify-end gap-2 mt-5">
          {hasKey && (
            <button
              onClick={clear}
              className="bg-slate-950 text-red-400 border border-slate-700 hover:border-red-500 px-3 py-1 rounded-lg text-sm font-semibold transition"
            >
              Supprimer
            </button>
          )}
          <button
            onClick={onClose}
            className="bg-slate-950 text-slate-300 border border-slate-700 hover:border-slate-500 px-3 py-1 rounded-lg text-sm font-semibold transition"
          >
            Annuler
          </button>
          <button
            onClick={save}
            disabled={!value.trim()}
            className="bg-blue-600 hover:bg-blue-500 disabled:bg-slate-800 disabled:text-slate-500 text-white px-3 py-1 rounded-lg text-sm font-bold transition"
          >
            Enregistrer
          </button>
        </div>
      </div>
    </div>
  );
}
