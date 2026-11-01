'use client';

import Link from 'next/link';
import { useState } from 'react';
import {
  downloadBlob,
  downloadCodePdf,
  downloadGddPdf,
  downloadImage,
  gddToMarkdown,
  gddToText,
  slugifyFilename,
  type CodeFormat,
  type GddFormat,
  type ImageFormat,
} from '../lib/download';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://127.0.0.1:8000';

interface BeatChartLevelData {
  level_name: string;
  progression_focus: string;
  mechanics_introduced?: string[];
  enemies_introduced?: string[];
  estimated_play_time?: string;
}

interface GddData {
  document_type: string;
  one_sheet?: {
    title?: string;
    story_summary?: string;
    usps?: string[];
  };
  beat_chart?: BeatChartLevelData[] | null;
  visual_style_prompt?: string;
  status?: string;
}

interface CodeData {
  engine: string;
  file_name: string;
  language: string;
  code_content: string;
  status?: string;
}

interface AssetData {
  asset_type: string;
  prompt_used: string;
  image_url: string;
  status: string;
}

async function apiFetch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`${path} failed: ${res.status} ${res.statusText} ${text.slice(0, 300)}`);
  }
  return (await res.json()) as T;
}

export default function Home() {
  const [prompt, setPrompt] = useState('Un jeu de survie contre des hordes de zombies dans un cimetière');
  const [engine, setEngine] = useState('Godot 4');
  const [docType, setDocType] = useState('beat_chart');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [gddData, setGddData] = useState<GddData | null>(null);
  const [codeData, setCodeData] = useState<CodeData | null>(null);
  const [assetTypes, setAssetTypes] = useState<string[]>(['sprite']);
  const [artStyle, setArtStyle] = useState('pixel art');
  const [assetList, setAssetList] = useState<AssetData[]>([]);
  const [gddFormat, setGddFormat] = useState<GddFormat>('md');
  const [codeFormat, setCodeFormat] = useState<CodeFormat>('source');
  const [imgFormat, setImgFormat] = useState<ImageFormat>('png');

  const handleGenerate = () => {
    setLoading(true);
    setError(null);
    setGddData(null);
    setCodeData(null);
    setAssetList([]);

    const failures: string[] = [];
    const onError = (label: string) => (err: unknown) => {
      failures.push(`${label} : ${err instanceof Error ? err.message : 'Unknown error'}`);
    };

    // Code is independent: fire immediately.
    const codeP = apiFetch<CodeData>('/api/v1/generate-code', { prompt, engine }).then(
      setCodeData,
      onError('Code'),
    );

    // Assets are chained on the GDD: they use its visual_style_prompt so the
    // art direction matches the document (raw prompt if the GDD fails).
    const assetsP = apiFetch<GddData>('/api/v1/generate-gdd', {
      prompt,
      doc_type: docType,
      engine,
    })
      .then(
        (g) => {
          setGddData(g);
          return g.visual_style_prompt || prompt;
        },
        (err: unknown) => {
          onError('GDD')(err);
          return prompt;
        },
      )
      .then((stylePrompt) =>
        Promise.all(
          assetTypes.map((t) =>
            apiFetch<AssetData>('/api/v1/generate-asset', {
              prompt: stylePrompt,
              asset_type: t,
              style: artStyle,
            }).then(
              (a) => setAssetList((prev) => [...prev, a]),
              onError(`Asset (${t})`),
            ),
          ),
        ),
      );

    void Promise.all([codeP, assetsP]).then(() => {
      if (failures.length > 0) {
        setError(failures.join('\n'));
      }
      setLoading(false);
    });
  };

  const downloadGdd = () => {
    if (!gddData) return;
    try {
      const base = `gdd-${slugifyFilename(gddData.one_sheet?.title ?? 'document')}`;
      if (gddFormat === 'json') {
        downloadBlob(
          new Blob([JSON.stringify(gddData, null, 2)], { type: 'application/json' }),
          `${base}.json`,
        );
      } else if (gddFormat === 'txt') {
        downloadBlob(new Blob([gddToText(gddData)], { type: 'text/plain' }), `${base}.txt`);
      } else if (gddFormat === 'pdf') {
        void downloadGddPdf(gddData, `${base}.pdf`).catch(() =>
          setError('Téléchargement du GDD impossible.'),
        );
      } else {
        downloadBlob(new Blob([gddToMarkdown(gddData)], { type: 'text/markdown' }), `${base}.md`);
      }
    } catch {
      setError('Téléchargement du GDD impossible.');
    }
  };

  const downloadCode = () => {
    if (!codeData) return;
    try {
      const base = codeData.file_name.replace(/\.[^.]+$/, '') || 'script';
      if (codeFormat === 'pdf') {
        void downloadCodePdf(codeData.file_name, codeData.code_content, `${base}.pdf`).catch(() =>
          setError('Téléchargement du script impossible.'),
        );
        return;
      }
      const name = codeFormat === 'txt' ? `${base}.txt` : codeData.file_name;
      downloadBlob(new Blob([codeData.code_content], { type: 'text/plain' }), name);
    } catch {
      setError('Téléchargement du script impossible.');
    }
  };

  const downloadAsset = (a: AssetData, i: number) => {
    void downloadImage(a.image_url, `${a.asset_type}-${i + 1}`, imgFormat);
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
        <div className="flex items-center gap-3">
          <Link
            href="/gdd-form"
            className="bg-slate-900 text-slate-200 border border-slate-700 hover:border-blue-500 px-3 py-1 rounded-full text-xs font-semibold transition"
          >
            Document Rogers →
          </Link>
          <span className="bg-blue-900/40 text-blue-400 border border-blue-500/30 px-3 py-1 rounded-full text-xs font-semibold">
            Meta AI Pipeline
          </span>
        </div>
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
            <option value="Unreal Engine">Unreal Engine (C++)</option>
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

          <label className="block text-xs text-slate-400 mb-1">Assets visuels (~0,01 $ / image)</label>
          <div className="space-y-1 mb-4 text-sm text-slate-200">
            {[
              { v: 'sprite', l: 'Sprites' },
              { v: 'concept_art', l: 'Concept arts' },
              { v: 'ui_concept', l: 'UI concept' },
            ].map((o) => (
              <label key={o.v} className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  className="accent-blue-600"
                  checked={assetTypes.includes(o.v)}
                  onChange={() =>
                    setAssetTypes((prev) =>
                      prev.includes(o.v) ? prev.filter((t) => t !== o.v) : [...prev, o.v],
                    )
                  }
                />
                {o.l}
              </label>
            ))}
          </div>

          <label className="block text-xs text-slate-400 mb-1">Style graphique</label>
          <select
            className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-sm mb-6 text-slate-200"
            value={artStyle}
            onChange={(e) => setArtStyle(e.target.value)}
          >
            <option value="pixel art">Pixel art</option>
            <option value="hand-painted digital art">Peinture numérique</option>
            <option value="anime style">Anime / manga</option>
            <option value="watercolor">Aquarelle</option>
            <option value="dark realistic">Réaliste sombre</option>
            <option value="cartoon">Cartoon</option>
          </select>

          <button
            onClick={handleGenerate}
            disabled={loading}
            className="w-full bg-blue-600 hover:bg-blue-500 disabled:bg-slate-800 text-white font-bold py-3 px-4 rounded-lg transition"
          >
            {loading ? 'Génération en cours...' : '⚡ Lancer le Pipeline IA'}
          </button>

          {error && (
            <p className="mt-4 text-xs text-red-400 bg-red-950/40 border border-red-500/30 rounded-lg p-3 break-words">
              {error}
            </p>
          )}
        </div>

        {/* Dashboard de résultat */}
        <div className="md:col-span-2 space-y-6">
          {/* Section GDD */}
          <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl">
            <div className="flex flex-wrap justify-between items-center gap-2 mb-2">
              <h2 className="text-lg font-bold text-blue-400">📄 Game Design Document (GDD Agent)</h2>
              {gddData && (
                <div className="flex items-center gap-2">
                  <select
                    aria-label="Format du GDD"
                    className="bg-slate-950 border border-slate-800 rounded-lg p-1 text-xs text-slate-200"
                    value={gddFormat}
                    onChange={(e) => setGddFormat(e.target.value as GddFormat)}
                  >
                    <option value="md">Markdown</option>
                    <option value="json">JSON</option>
                    <option value="txt">Texte</option>
                    <option value="pdf">PDF</option>
                  </select>
                  <button
                    onClick={downloadGdd}
                    className="bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold py-1 px-3 rounded-lg transition"
                  >
                    Télécharger
                  </button>
                </div>
              )}
            </div>
            {gddData ? (
              <div className="space-y-4 text-sm text-slate-300">
                <p><strong className="text-white">Titre :</strong> {gddData.one_sheet?.title}</p>
                <p><strong className="text-white">Résumé :</strong> {gddData.one_sheet?.story_summary}</p>
                <p className="text-xs text-slate-500">Format : <span className="font-mono text-slate-400">{gddData.document_type}</span></p>
                {gddData.status && gddData.status !== 'success' && (
                  <p className="text-xs text-amber-400 italic">Contenu de secours : la réponse Meta était inutilisable (voir les logs backend).</p>
                )}
                <div>
                  <strong className="text-white block mb-1">USPs (Unique Selling Points) :</strong>
                  <ul className="list-disc list-inside space-y-1 text-slate-400">
                    {gddData.one_sheet?.usps?.map((usp: string, idx: number) => (
                      <li key={idx}>{usp}</li>
                    ))}
                  </ul>
                </div>
                {gddData.beat_chart && gddData.beat_chart.length > 0 && (
                  <div>
                    <strong className="text-white block mb-1">Beat Chart (Progression) :</strong>
                    <ul className="space-y-2">
                      {gddData.beat_chart.map((lvl: BeatChartLevelData, idx: number) => (
                        <li key={idx} className="bg-slate-950 border border-slate-800 rounded-lg p-3">
                          <p className="text-slate-200 font-semibold">{lvl.level_name} <span className="text-slate-500 font-normal">({lvl.estimated_play_time})</span></p>
                          <p className="text-slate-400 text-xs mt-1">{lvl.progression_focus}</p>
                          <p className="text-slate-500 text-xs mt-1">Mécaniques : {(lvl.mechanics_introduced ?? []).join(', ')}</p>
                          <p className="text-slate-500 text-xs">Ennemis : {(lvl.enemies_introduced ?? []).join(', ')}</p>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            ) : (
              <p className="text-xs text-slate-500 italic">{loading ? 'Génération en cours...' : 'En attente de génération...'}</p>
            )}
          </div>

          {/* Section Code */}
          <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl">
            <div className="flex flex-wrap justify-between items-center gap-2 mb-2">
              <h2 className="text-lg font-bold text-emerald-400">💻 Script de Contrôleur (Code Agent)</h2>
              {codeData && (
                <div className="flex items-center gap-2">
                  <select
                    aria-label="Format du script"
                    className="bg-slate-950 border border-slate-800 rounded-lg p-1 text-xs text-slate-200"
                    value={codeFormat}
                    onChange={(e) => setCodeFormat(e.target.value as CodeFormat)}
                  >
                    <option value="source">Fichier source</option>
                    <option value="txt">Texte (.txt)</option>
                    <option value="pdf">PDF</option>
                  </select>
                  <button
                    onClick={downloadCode}
                    className="bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold py-1 px-3 rounded-lg transition"
                  >
                    Télécharger
                  </button>
                </div>
              )}
            </div>
            {codeData ? (
              <div>
                <span className="text-xs font-mono text-emerald-500 mb-2 block">{codeData.file_name} ({codeData.language})</span>
                {codeData.status && codeData.status !== 'success' && (
                  <p className="text-xs text-amber-400 italic mb-2">Script de secours : la génération Meta a échoué (voir les logs backend).</p>
                )}
                <pre className="bg-slate-950 p-4 rounded-lg text-xs font-mono text-slate-300 overflow-x-auto border border-slate-800">
                  {codeData.code_content}
                </pre>
              </div>
            ) : (
              <p className="text-xs text-slate-500 italic">{loading ? 'Génération en cours...' : 'En attente de génération...'}</p>
            )}
          </div>

          {/* Section Assets Visuels */}
          <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl">
            <div className="flex flex-wrap justify-between items-center gap-2 mb-2">
              <h2 className="text-lg font-bold text-purple-400">🎨 Assets Visuels (Meta Muse Image Agent)</h2>
              {assetList.length > 0 && (
                <select
                  aria-label="Format des images"
                  className="bg-slate-950 border border-slate-800 rounded-lg p-1 text-xs text-slate-200"
                  value={imgFormat}
                  onChange={(e) => setImgFormat(e.target.value as ImageFormat)}
                >
                  <option value="png">PNG</option>
                  <option value="jpg">JPEG</option>
                  <option value="webp">WEBP</option>
                  <option value="pdf">PDF</option>
                </select>
              )}
            </div>
            {assetList.length > 0 ? (
              <div className="space-y-4">
                {assetList.map((a, idx) => (
                  <div key={idx} className="space-y-2 border-b border-slate-800 pb-4 last:border-0 last:pb-0">
                    <div className="flex justify-between items-center">
                      <p className="text-xs font-mono text-purple-400">{a.asset_type}</p>
                      <button
                        onClick={() => downloadAsset(a, idx)}
                        className="bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold py-1 px-3 rounded-lg transition"
                      >
                        Télécharger
                      </button>
                    </div>
                    <p className="text-xs text-slate-400"><strong>Prompt :</strong> {a.prompt_used}</p>
                    <img src={a.image_url} alt={`Generated ${a.asset_type}`} className="w-full max-w-sm rounded-lg border border-slate-800 bg-slate-950" />
                    {a.status !== 'success' && (
                      <p className="text-xs text-amber-400 italic">Aperçu simulé : la génération Meta Muse Image a échoué (voir les logs backend).</p>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-slate-500 italic">{loading ? 'En attente du style visuel (GDD)...' : 'En attente de génération...'}</p>
            )}
          </div>
        </div>
      </section>
    </main>
  );
}
