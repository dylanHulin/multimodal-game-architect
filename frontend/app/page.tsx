'use client';

import Link from 'next/link';
import dynamic from 'next/dynamic';
import { Suspense, useEffect, useState, useSyncExternalStore } from 'react';
import APIKeyModal from '../components/APIKeyModal';
import CutoutPanel from '../components/CutoutPanel';
import DictationButton from '../components/DictationButton';
import FallbackBadge from '../components/FallbackBadge';
import GenerationProgress, { type ProgressStage } from '../components/GenerationProgress';
import HistoryPanel from '../components/HistoryPanel';
import LanguageSwitcher from '../components/LanguageSwitcher';
import MusicCard from '../components/MusicCard';
import { authHeaders, getUserApiKeySet, subscribeUserApiKey } from '../lib/apiKey';
import {
  COST_CODE_USD,
  COST_IMAGE_USD,
  addSessionSpend,
  estimateGdd,
  estimateRun,
  formatCost,
  getSpendSnapshot,
  subscribeSpend,
} from '../lib/cost';
import type { DemoBundle } from '../lib/demo';
import { pushHistory, type HistoryEntry } from '../lib/history';
import { translateError, tr } from '../lib/i18n';
import { useT } from '../lib/useT';
import { speakText, stopSpeaking } from '../lib/speech';
import {
  downloadBase64Pdf,
  downloadBlob,
  downloadCodePdf,
  downloadGddPdf,
  downloadImage,
  gddToMarkdown,
  gddToText,
  requestStyledPdf,
  slugifyFilename,
  type CodeFormat,
  type GddFormat,
  type ImageFormat,
} from '../lib/download';

// Client-only: the manifest fetch resolves differently on server vs client.
const ExamplesRow = dynamic(() => import('../components/ExamplesRow'), { ssr: false });

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
  basePrompt?: string;
  style?: string;
}

async function apiFetch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`${path} failed: ${res.status} ${res.statusText} ${text.slice(0, 300)}`);
  }
  return (await res.json()) as T;
}

export default function Home() {
  const { t } = useT();
  // Sample prompt follows the UI language until the user types (hydration-safe:
  // t() is store-driven, unlike useState initializers).
  const [prompt, setPrompt] = useState('');
  const [promptTouched, setPromptTouched] = useState(false);
  const effPrompt = promptTouched ? prompt : t('main.defaultPrompt');
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
  const [pdfBusy, setPdfBusy] = useState(false);
  const [codeFormat, setCodeFormat] = useState<CodeFormat>('source');
  const [imgFormat, setImgFormat] = useState<ImageFormat>('png');
  const [keyOpen, setKeyOpen] = useState(false);
  const hasKey = useSyncExternalStore(subscribeUserApiKey, getUserApiKeySet, () => false);
  const [runId, setRunId] = useState(0);
  const spend = useSyncExternalStore(subscribeSpend, getSpendSnapshot, () => 0);
  const [regenGddBusy, setRegenGddBusy] = useState(false);
  const [regenCodeBusy, setRegenCodeBusy] = useState(false);
  const [regenAssetBusy, setRegenAssetBusy] = useState<Record<number, boolean>>({});
  const [speaking, setSpeaking] = useState(false);

  useEffect(() => () => stopSpeaking(), []);

  const handleGenerate = () => {
    stopSpeaking();
    setSpeaking(false);
    setLoading(true);
    setError(null);
    setGddData(null);
    setCodeData(null);
    setAssetList([]);
    setRunId((n) => n + 1);

    const failures: string[] = [];
    const onError = (label: string) => (err: unknown) => {
      failures.push(`${label} : ${err instanceof Error ? err.message : tr('err.unknown')}`);
    };
    let doneGdd: GddData | null = null;
    let doneCode: CodeData | null = null;
    const doneAssets: AssetData[] = [];

    // Code is independent: fire immediately.
    const codeP = apiFetch<CodeData>('/api/v1/generate-code', { prompt: effPrompt, engine }).then(
      (d) => {
        doneCode = d;
        setCodeData(d);
      },
      onError('Code'),
    );

    // Assets are chained on the GDD: they use its visual_style_prompt so the
    // art direction matches the document (raw prompt if the GDD fails).
    const assetsP = apiFetch<GddData>('/api/v1/generate-gdd', {
      prompt: effPrompt,
      doc_type: docType,
      engine,
    })
      .then(
        (g) => {
          doneGdd = g;
          setGddData(g);
          return g.visual_style_prompt || effPrompt;
        },
        (err: unknown) => {
          onError('GDD')(err);
          return effPrompt;
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
              (a) => {
                const full = { ...a, basePrompt: stylePrompt, style: artStyle };
                doneAssets.push(full);
                setAssetList((prev) => [...prev, full]);
              },
              onError(tr('err.asset', { t })),
            ),
          ),
        ),
      );

    void Promise.all([codeP, assetsP]).then(async () => {
      if (failures.length > 0) {
        setError(failures.join('\n'));
      }
      if (doneGdd) {
        addSessionSpend(estimateRun(docType, doneAssets.length, doneCode !== null));
        await pushHistory('main', {
          title: doneGdd.one_sheet?.title ?? tr('err.untitled'),
          docType: doneGdd.document_type,
          gdd: doneGdd,
          code: doneCode,
          images: doneAssets,
        }).catch(() => undefined);
      }
      setLoading(false);
    });
  };

  const regenGdd = () => {
    setRegenGddBusy(true);
    setError(null);
    void apiFetch<GddData>('/api/v1/generate-gdd', { prompt: effPrompt, doc_type: docType, engine })
      .then(
        (g) => {
          setGddData(g);
          addSessionSpend(estimateGdd(docType));
        },
        (err: unknown) =>
          setError(
            t('err.regenGdd', { msg: err instanceof Error ? err.message : tr('err.unknown') }),
          ),
      )
      .finally(() => setRegenGddBusy(false));
  };

  const regenCode = () => {
    setRegenCodeBusy(true);
    setError(null);
    void apiFetch<CodeData>('/api/v1/generate-code', { prompt: effPrompt, engine })
      .then(
        (d) => {
          setCodeData(d);
          addSessionSpend(COST_CODE_USD);
        },
        (err: unknown) =>
          setError(
            t('err.regenScript', { msg: err instanceof Error ? err.message : tr('err.unknown') }),
          ),
      )
      .finally(() => setRegenCodeBusy(false));
  };

  const regenAsset = (index: number) => {
    const current = assetList[index];
    if (!current) return;
    const basePrompt = current.basePrompt ?? effPrompt;
    const style = current.style ?? artStyle;
    setRegenAssetBusy((p) => ({ ...p, [index]: true }));
    void apiFetch<AssetData>('/api/v1/generate-asset', {
      prompt: basePrompt,
      asset_type: current.asset_type,
      style,
    })
      .then(
        (a) => {
          setAssetList((prev) =>
            prev.map((it, j) => (j === index ? { ...a, basePrompt, style } : it)),
          );
          addSessionSpend(COST_IMAGE_USD);
        },
        (err: unknown) =>
          setError(
            t('err.regenVisual', { msg: err instanceof Error ? err.message : tr('err.unknown') }),
          ),
      )
      .finally(() => setRegenAssetBusy((p) => ({ ...p, [index]: false })));
  };

  const narrate = () => {
    if (speaking) {
      stopSpeaking();
      setSpeaking(false);
      return;
    }
    const s = gddData?.one_sheet;
    const text = [s?.title, s?.story_summary, ...(s?.usps ?? [])].filter(Boolean).join('. ');
    if (!text) return;
    if (speakText(text, undefined, () => setSpeaking(false))) {
      setSpeaking(true);
    } else {
      setError(tr('err.narrate'));
    }
  };

  const loadDemo = (bundle: DemoBundle) => {
    stopSpeaking();
    setSpeaking(false);
    setError(null);
    setLoading(false);
    setGddData(bundle.gdd as unknown as GddData);
    setCodeData(bundle.code as unknown as CodeData | null);
    setAssetList(
      (bundle.images ?? []).map((img) => ({
        asset_type: img.asset_type,
        prompt_used: img.prompt_used,
        image_url: `/demo/${img.file}`,
        status: img.status,
      })),
    );
  };

  const restoreHistory = (entry: HistoryEntry) => {
    stopSpeaking();
    setSpeaking(false);
    setError(null);
    setLoading(false);
    setGddData(entry.gdd as unknown as GddData);
    setCodeData(entry.code as CodeData | null);
    setAssetList(entry.images);
  };

  const stages: ProgressStage[] = [
    { label: 'GDD', state: gddData ? 'done' : 'active' },
    { label: t('stage.script'), state: codeData ? 'done' : 'active' },
    {
      label: t('stage.visuals', { done: assetList.length, total: assetTypes.length }),
      state: !loading && assetList.length > 0 ? 'done' : gddData ? 'active' : 'pending',
    },
  ];

  const downloadGdd = () => {
    if (!gddData || pdfBusy) return;
    if (gddFormat === 'pdf-pro' || gddFormat === 'pdf-gamebook') {
      const style = gddFormat === 'pdf-pro' ? 'pro' : 'gamebook';
      const base = `gdd-${slugifyFilename(gddData.one_sheet?.title ?? 'document')}`;
      setPdfBusy(true);
      requestStyledPdf(gddData, style, assetList)
        .then((res) => {
          if (res.status !== 'success') setError(res.error ?? tr('err.downloadGdd'));
          else downloadBase64Pdf(res.pdf_base64, `${base}-${gddFormat}.pdf`);
        })
        .catch(() => setError(tr('err.downloadGdd')))
        .finally(() => setPdfBusy(false));
      return;
    }
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
          setError(tr('err.downloadGdd')),
        );
      } else {
        downloadBlob(new Blob([gddToMarkdown(gddData)], { type: 'text/markdown' }), `${base}.md`);
      }
    } catch {
      setError(tr('err.downloadGdd'));
    }
  };

  const downloadCode = () => {
    if (!codeData) return;
    try {
      const base = codeData.file_name.replace(/\.[^.]+$/, '') || 'script';
      if (codeFormat === 'pdf') {
        void downloadCodePdf(codeData.file_name, codeData.code_content, `${base}.pdf`).catch(() =>
          setError(tr('err.downloadScript')),
        );
        return;
      }
      const name = codeFormat === 'txt' ? `${base}.txt` : codeData.file_name;
      downloadBlob(new Blob([codeData.code_content], { type: 'text/plain' }), name);
    } catch {
      setError(tr('err.downloadScript'));
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
          <p className="text-slate-400 text-sm mt-1">{t('header.tagline')}</p>
        </div>
        <div className="flex items-center gap-3">
          <Link
            href="/gdd-form"
            className="bg-slate-900 text-slate-200 border border-slate-700 hover:border-blue-500 px-3 py-1 rounded-full text-xs font-semibold transition"
          >
            {t('header.builderDoc')}
          </Link>
          <Link
            href="/gdd-review"
            className="bg-slate-900 text-slate-200 border border-slate-700 hover:border-blue-500 px-3 py-1 rounded-full text-xs font-semibold transition"
          >
            {t('nav.review')}
          </Link>
          <LanguageSwitcher />
          <button
            onClick={() => setKeyOpen(true)}
            className="bg-slate-900 text-slate-200 border border-slate-700 hover:border-blue-500 px-3 py-1 rounded-full text-xs font-semibold transition"
          >
            {t('common.apiKey')}
          </button>
          {hasKey ? (
            <span className="bg-emerald-900/40 text-emerald-400 border border-emerald-500/30 px-3 py-1 rounded-full text-xs font-semibold">
              {t('common.personalKey')}
            </span>
          ) : (
            <span className="bg-blue-900/40 text-blue-400 border border-blue-500/30 px-3 py-1 rounded-full text-xs font-semibold">
              Meta AI Pipeline
            </span>
          )}
          <span
            title={t('header.sessionTitle')}
            className="bg-slate-900 text-slate-400 border border-slate-700 px-3 py-1 rounded-full text-xs font-mono"
          >
            {t('common.session')} {formatCost(spend)}
          </span>
        </div>
      </header>

      <Suspense fallback={<p className="max-w-6xl mx-auto mb-8 text-xs text-slate-500">{t('common.loadingExamples')}</p>}>
        <ExamplesRow onLoad={loadDemo} />
      </Suspense>

      <section className="max-w-6xl mx-auto grid grid-cols-1 md:grid-cols-3 gap-8">
        {/* Formulaire de configuration */}
        <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl h-fit">
          <h2 className="text-xl font-bold mb-4 text-slate-200">{t('main.concept')}</h2>

          <div className="flex justify-between items-center mb-1">
            <label className="block text-xs text-slate-400">{t('main.promptLabel')}</label>
            <DictationButton
              onText={(txt) => {
                setPromptTouched(true);
                setPrompt(effPrompt ? `${effPrompt} ${txt}` : txt);
              }}
            />
          </div>
          <textarea
            className="w-full bg-slate-950 border border-slate-800 rounded-lg p-3 text-sm mb-4 focus:outline-none focus:border-blue-500 text-slate-200"
            rows={4}
            value={effPrompt}
            onChange={(e) => {
              setPromptTouched(true);
              setPrompt(e.target.value);
            }}
          />

          <label className="block text-xs text-slate-400 mb-1">{t('main.engineLabel')}</label>
          <select
            className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-sm mb-4 text-slate-200"
            value={engine}
            onChange={(e) => setEngine(e.target.value)}
          >
            <option value="Godot 4">Godot 4 (GDScript)</option>
            <option value="Unity">Unity (C#)</option>
            <option value="Unreal Engine">Unreal Engine (C++)</option>
          </select>

          <label className="block text-xs text-slate-400 mb-1">{t('main.docLabel')}</label>
          <select
            className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-sm mb-6 text-slate-200"
            value={docType}
            onChange={(e) => setDocType(e.target.value)}
          >
            <option value="one_sheet">One-Sheet (Pitch & USPs)</option>
            <option value="beat_chart">{t('main.beatChartOpt')}</option>
            <option value="full_gdd">Full GDD</option>
          </select>

          <label className="block text-xs text-slate-400 mb-1">{t('main.assetsLabel')}</label>
          <div className="space-y-1 mb-4 text-sm text-slate-200">
            {[
              { v: 'sprite', l: t('main.spritesOpt') },
              { v: 'concept_art', l: t('main.conceptOpt') },
              { v: 'ui_concept', l: t('main.uiOpt') },
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

          <label className="block text-xs text-slate-400 mb-1">{t('main.styleLabel')}</label>
          <select
            className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-sm mb-6 text-slate-200"
            value={artStyle}
            onChange={(e) => setArtStyle(e.target.value)}
          >
            <option value="pixel art">Pixel art</option>
            <option value="hand-painted digital art">{t('style.digital')}</option>
            <option value="anime style">Anime / manga</option>
            <option value="watercolor">{t('style.watercolor')}</option>
            <option value="dark realistic">{t('style.dark')}</option>
            <option value="cartoon">Cartoon</option>
          </select>

          <button
            onClick={handleGenerate}
            disabled={loading}
            className="w-full bg-blue-600 hover:bg-blue-500 disabled:bg-slate-800 text-white font-bold py-3 px-4 rounded-lg transition"
          >
            {loading ? t('common.generating') : t('main.launchBtn')}
          </button>
          <p className="mt-2 text-xs text-slate-500">
            {t('common.estimatedCost')}{' '}
            <span className="font-mono text-slate-400">
              {formatCost(estimateRun(docType, assetTypes.length, true))}
            </span>
          </p>

          {error && (
            <p className="mt-4 text-xs text-red-400 bg-red-950/40 border border-red-500/30 rounded-lg p-3 break-words">
              {translateError(error)}
            </p>
          )}
        </div>

        {/* Dashboard de résultat */}
        <div className="md:col-span-2 space-y-6">
          {loading && <GenerationProgress key={runId} stages={stages} />}
          {/* Section GDD */}
          <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl">
            <div className="flex flex-wrap justify-between items-center gap-2 mb-2">
              <h2 className="text-lg font-bold text-blue-400">📄 Game Design Document (GDD Agent)</h2>
              {gddData && (
                <div className="flex items-center gap-2">
                  <select
                    aria-label={t('gdd.ariaFormat')}
                    className="bg-slate-950 border border-slate-800 rounded-lg p-1 text-xs text-slate-200"
                    value={gddFormat}
                    onChange={(e) => setGddFormat(e.target.value as GddFormat)}
                  >
                    <option value="md">Markdown</option>
                    <option value="json">JSON</option>
                    <option value="txt">{t('common.textFormat')}</option>
                    <option value="pdf">PDF</option>
                    <option value="pdf-pro">PDF Pro</option>
                    <option value="pdf-gamebook">PDF Gamebook</option>
                  </select>
                  <button
                    onClick={narrate}
                    className="bg-slate-950 text-slate-300 border border-slate-700 hover:border-blue-500 text-xs font-semibold py-1 px-3 rounded-lg transition"
                  >
                    {speaking ? t('common.stop') : t('common.listen')}
                  </button>
                  <button
                    onClick={regenGdd}
                    disabled={regenGddBusy || loading}
                    className="bg-slate-950 text-slate-300 border border-slate-700 hover:border-blue-500 disabled:opacity-50 text-xs font-semibold py-1 px-3 rounded-lg transition"
                  >
                    {regenGddBusy ? '…' : t('common.regenerate')}
                  </button>
                  <button
                    onClick={downloadGdd}
                    disabled={pdfBusy}
                    className="bg-blue-600 hover:bg-blue-500 disabled:bg-slate-800 text-white text-xs font-bold py-1 px-3 rounded-lg transition"
                  >
                    {pdfBusy ? '…' : t('common.download')}
                  </button>
                </div>
              )}
            </div>
            {gddData ? (
              <div className="space-y-4 text-sm text-slate-300">
                <p><strong className="text-white">{t('common.title')}</strong> {gddData.one_sheet?.title}</p>
                <p><strong className="text-white">{t('common.summary')}</strong> {gddData.one_sheet?.story_summary}</p>
                <p className="text-xs text-slate-500">{t('common.format')} <span className="font-mono text-slate-400">{gddData.document_type}</span></p>
                <FallbackBadge status={gddData.status} message={t('gdd.fallback')} />
                <div>
                  <strong className="text-white block mb-1">{t('gdd.usps')}</strong>
                  <ul className="list-disc list-inside space-y-1 text-slate-400">
                    {gddData.one_sheet?.usps?.map((usp: string, idx: number) => (
                      <li key={idx}>{usp}</li>
                    ))}
                  </ul>
                </div>
                {gddData.beat_chart && gddData.beat_chart.length > 0 && (
                  <div>
                    <strong className="text-white block mb-1">{t('gdd.beatChart')}</strong>
                    <ul className="space-y-2">
                      {gddData.beat_chart.map((lvl: BeatChartLevelData, idx: number) => (
                        <li key={idx} className="bg-slate-950 border border-slate-800 rounded-lg p-3">
                          <p className="text-slate-200 font-semibold">{lvl.level_name} <span className="text-slate-500 font-normal">({lvl.estimated_play_time})</span></p>
                          <p className="text-slate-400 text-xs mt-1">{lvl.progression_focus}</p>
                          <p className="text-slate-500 text-xs mt-1">{t('gdd.mechanics')} {(lvl.mechanics_introduced ?? []).join(', ')}</p>
                          <p className="text-slate-500 text-xs">{t('gdd.enemies')} {(lvl.enemies_introduced ?? []).join(', ')}</p>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            ) : (
              <p className="text-xs text-slate-500 italic">{loading ? t('common.generating') : t('common.waiting')}</p>
            )}
          </div>

          {/* Section Code */}
          <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl">
            <div className="flex flex-wrap justify-between items-center gap-2 mb-2">
              <h2 className="text-lg font-bold text-emerald-400">{t('code.title')}</h2>
              {codeData && (
                <div className="flex items-center gap-2">
                  <select
                    aria-label={t('code.ariaFormat')}
                    className="bg-slate-950 border border-slate-800 rounded-lg p-1 text-xs text-slate-200"
                    value={codeFormat}
                    onChange={(e) => setCodeFormat(e.target.value as CodeFormat)}
                  >
                    <option value="source">{t('common.sourceFile')}</option>
                    <option value="txt">{t('common.txtFile')}</option>
                    <option value="pdf">PDF</option>
                  </select>
                  <button
                    onClick={regenCode}
                    disabled={regenCodeBusy || loading}
                    className="bg-slate-950 text-slate-300 border border-slate-700 hover:border-blue-500 disabled:opacity-50 text-xs font-semibold py-1 px-3 rounded-lg transition"
                  >
                    {regenCodeBusy ? '…' : t('common.regenerate')}
                  </button>
                  <button
                    onClick={downloadCode}
                    className="bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold py-1 px-3 rounded-lg transition"
                  >
                    {t('common.download')}
                  </button>
                </div>
              )}
            </div>
            {codeData ? (
              <div>
                <span className="text-xs font-mono text-emerald-500 mb-2 block">{codeData.file_name} ({codeData.language})</span>
                <FallbackBadge status={codeData.status} message={t('code.fallback')} />
                <pre className="bg-slate-950 p-4 rounded-lg text-xs font-mono text-slate-300 overflow-x-auto border border-slate-800">
                  {codeData.code_content}
                </pre>
              </div>
            ) : (
              <p className="text-xs text-slate-500 italic">{loading ? t('common.generating') : t('common.waiting')}</p>
            )}
          </div>

          {/* Section Assets Visuels */}
          <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl">
            <div className="flex flex-wrap justify-between items-center gap-2 mb-2">
              <h2 className="text-lg font-bold text-purple-400">{t('assets.title')}</h2>
              {assetList.length > 0 && (
                <select
                  aria-label={t('assets.ariaFormat')}
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
                      <div className="flex items-center gap-2">
                        {a.asset_type === 'sprite' && (
                          <CutoutPanel imageUrl={a.image_url} fileBase={`${a.asset_type}-${idx + 1}`} />
                        )}
                        <button
                          onClick={() => regenAsset(idx)}
                          disabled={regenAssetBusy[idx] || loading}
                          className="bg-slate-950 text-slate-300 border border-slate-700 hover:border-blue-500 disabled:opacity-50 text-xs font-semibold py-1 px-3 rounded-lg transition"
                        >
                          {regenAssetBusy[idx] ? '…' : t('common.regenerate')}
                        </button>
                        <button
                          onClick={() => downloadAsset(a, idx)}
                          className="bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold py-1 px-3 rounded-lg transition"
                        >
                          {t('common.download')}
                        </button>
                      </div>
                    </div>
                    <p className="text-xs text-slate-400"><strong>{t('gdd.prompt')}</strong> {a.prompt_used}</p>
                    <img src={a.image_url} alt={`Generated ${a.asset_type}`} className="w-full max-w-sm rounded-lg border border-slate-800 bg-slate-950" />
                    <FallbackBadge status={a.status} message={t('assets.fallback')} />
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-slate-500 italic">{loading ? t('assets.waitingStyle') : t('common.waiting')}</p>
            )}
          </div>
          <MusicCard />
        </div>
      </section>

      <div className="max-w-6xl mx-auto mt-8">
        <HistoryPanel page="main" onRestore={restoreHistory} />
      </div>
      {keyOpen && <APIKeyModal onClose={() => setKeyOpen(false)} />}
    </main>
  );
}
