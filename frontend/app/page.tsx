'use client';

import { useState } from 'react';

export default function Home() {
  const [prompt, setPrompt] = useState('Un jeu de survie contre des hordes de zombies dans un cimetière');
  const [engine, setEngine] = useState('Godot 4');
  const [docType, setDocType] = useState('beat_chart');
  const [loading, setLoading] = useState(false);

  const [gddData, setGddData] = useState<any>(null);
  const [codeData, setCodeData] = useState<any>(null);
  const [assetData, setAssetData] = useState<any>(null);

  const handleGenerate = async () => {
    setLoading(true);
    setGddData(null);
    setCodeData(null);
    setAssetData(null);

    try {
      // 1. Appel GDD Agent
      const resGdd = await fetch('http://127.0.0.1:8000/api/v1/generate-gdd', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, doc_type: docType, engine }),
      });
      const dataGdd = await resGdd.json();
      setGddData(dataGdd);

      // 2. Appel Code Agent
      const resCode = await fetch('http://localhost:8000/api/v1/generate-code', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, engine }),
      });
      const dataCode = await resCode.json();
      setCodeData(dataCode);

      // 3. Appel Asset Agent
      const resAsset = await fetch('http://localhost:8000/api/v1/generate-asset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, asset_type: 'sprite_sheet' }),
      });
      const dataAsset = await resAsset.json();
      setAssetData(dataAsset);
    } catch (err) {
      console.error('Erreur lors de la génération :', err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100 p-8">
      <header className="max-w-6xl mx-auto mb-10 border-b border-slate-800 pb-6 flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-extrabold text-blue-500">🎮 MultiModal-GameArchitect</h1>
          <p className="text-slate-400 text-sm mt-1">
            Built for Meta AI Developer Hackathon • Scott Rogers Game Design Framework
          </p>
        </div>
        <span className="bg-blue-900/40 text-blue-400 border border-blue-500/30 px-3 py-1 rounded-full text-xs font-semibold">
          Meta AI Pipeline
        </span>
      </header>

      <section className="max-w-6xl mx-auto grid grid-cols-1 md:grid-cols-3 gap-8">
        {/* Formulaire de configuration */}
        <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl h-fit">
          <h2 className="text-xl font-bold mb-4 text-slate-200">1. Concept du Jeu</h2>
          
          <label className="block text-xs text-slate-400 mb-1">Prompt de départ</label>
          <textarea
            className="w-full bg-slate-950 border border-slate-800 rounded-lg p-3 text-sm mb-4 focus:outline-none focus:border-blue-500 text-slate-200"
            rows={4}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
          />

          <label className="block text-xs text-slate-400 mb-1">Moteur Cible</label>
          <select
            className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-sm mb-4 text-slate-200"
            value={engine}
            onChange={(e) => setEngine(e.target.value)}
          >
            <option value="Godot 4">Godot 4 (GDScript)</option>
            <option value="Unity">Unity (C#)</option>
          </select>

          <label className="block text-xs text-slate-400 mb-1">Format de Document (Rogers Framework)</label>
          <select
            className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-sm mb-6 text-slate-200"
            value={docType}
            onChange={(e) => setDocType(e.target.value)}
          >
            <option value="one_sheet">One-Sheet (Pitch & USPs)</option>
            <option value="beat_chart">Beat Chart (Progression)</option>
            <option value="full_gdd">Full GDD</option>
          </select>

          <button
            onClick={handleGenerate}
            disabled={loading}
            className="w-full bg-blue-600 hover:bg-blue-500 disabled:bg-slate-800 text-white font-bold py-3 px-4 rounded-lg transition"
          >
            {loading ? 'Génération en cours...' : '⚡ Lancer le Pipeline IA'}
          </button>
        </div>

        {/* Dashboard de résultat */}
        <div className="md:col-span-2 space-y-6">
          {/* Section GDD */}
          <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl">
            <h2 className="text-lg font-bold text-blue-400 mb-2">📄 Game Design Document (GDD Agent)</h2>
            {gddData ? (
              <div className="space-y-4 text-sm text-slate-300">
                <p><strong className="text-white">Titre :</strong> {gddData.one_sheet?.title}</p>
                <p><strong className="text-white">Résumé :</strong> {gddData.one_sheet?.story_summary}</p>
                <div>
                  <strong className="text-white block mb-1">USPs (Unique Selling Points) :</strong>
                  <ul className="list-disc list-inside space-y-1 text-slate-400">
                    {gddData.one_sheet?.usps?.map((usp: string, idx: number) => (
                      <li key={idx}>{usp}</li>
                    ))}
                  </ul>
                </div>
              </div>
            ) : (
              <p className="text-xs text-slate-500 italic">En attente de génération...</p>
            )}
          </div>

          {/* Section Code */}
          <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl">
            <h2 className="text-lg font-bold text-emerald-400 mb-2">💻 Script de Contrôleur (Code Agent)</h2>
            {codeData ? (
              <div>
                <span className="text-xs font-mono text-emerald-500 mb-2 block">{codeData.file_name} ({codeData.language})</span>
                <pre className="bg-slate-950 p-4 rounded-lg text-xs font-mono text-slate-300 overflow-x-auto border border-slate-800">
                  {codeData.code_content}
                </pre>
              </div>
            ) : (
              <p className="text-xs text-slate-500 italic">En attente de génération...</p>
            )}
          </div>

          {/* Section Assets Visuels */}
          <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl">
            <h2 className="text-lg font-bold text-purple-400 mb-2">🎨 Assets Visuels (Meta Muse Image Agent)</h2>
            {assetData ? (
              <div className="space-y-3">
                <p className="text-xs text-slate-400"><strong>Prompt :</strong> {assetData.prompt_used}</p>
                <img src={assetData.image_url} alt="Generated Sprite" className="w-32 h-32 rounded-lg border border-slate-800 bg-slate-950" />
              </div>
            ) : (
              <p className="text-xs text-slate-500 italic">En attente de génération...</p>
            )}
          </div>
        </div>
      </section>
    </main>
  );
}