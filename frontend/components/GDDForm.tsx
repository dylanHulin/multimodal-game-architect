'use client';

import { Suspense, useEffect, useRef, useState, useSyncExternalStore, type ChangeEvent } from 'react';
import dynamic from 'next/dynamic';
import APIKeyModal from './APIKeyModal';
import CutoutPanel from './CutoutPanel';
import DictationButton from './DictationButton';
import FallbackBadge from './FallbackBadge';
import GenerationProgress from './GenerationProgress';
import HistoryPanel from './HistoryPanel';
import MusicCard from './MusicCard';
import { apiPost } from '../lib/api';
import { authHeaders, getUserApiKeySet, subscribeUserApiKey } from '../lib/apiKey';
import {
  COST_IMAGE_USD,
  addSessionSpend,
  estimateRun,
  formatCost,
  getSpendSnapshot,
  subscribeSpend,
} from '../lib/cost';
import type { DemoBundle } from '../lib/demo';
import { pushHistory, type HistoryEntry } from '../lib/history';
import { translateError, tr, type I18nKey } from '../lib/i18n';
import { useT } from '../lib/useT';
import { speakText, stopSpeaking } from '../lib/speech';
import {
  downloadBase64Pdf,
  downloadBlob,
  downloadGddPdf,
  downloadImage,
  gddToMarkdown,
  gddToText,
  requestStyledPdf,
  slugifyFilename,
  type GddFormat,
  type ImageFormat,
} from '../lib/download';

// Client-only: the manifest fetch resolves differently on server vs client.
const ExamplesRow = dynamic(() => import('./ExamplesRow'), { ssr: false });

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://127.0.0.1:8000';

type DocType = 'one_sheet' | 'ten_pager' | 'full_gdd';

interface VisualRow {
  asset_type: string;
  label: string;
  enabled: boolean;
  count: number;
  style: string;
}

interface GeneratedImage {
  asset_type: string;
  prompt_used: string;
  image_url: string;
  status: string;
}

interface AssetResp {
  asset_type: string;
  prompt_used: string;
  image_url: string;
  status: string;
}

interface BeatLevel {
  level_name: string;
  progression_focus: string;
  mechanics_introduced?: string[];
  enemies_introduced?: string[];
  estimated_play_time?: string;
}

interface GddResult {
  document_type: string;
  status: string;
  one_sheet: {
    title?: string;
    story_summary?: string;
    usps?: string[];
    target_systems?: string[];
    target_age?: string;
    esrb_rating?: string;
  };
  beat_chart?: BeatLevel[] | null;
  visual_style_prompt?: string;
  ten_pager?: {
    camera?: string | null;
    character?: string | null;
    controls?: string | null;
    core_loop?: string | null;
    menu_flow?: string | null;
  } | null;
  full_gdd?: {
    lore?: string | null;
    level_design?: string | null;
    features?: string[];
    ai_type?: string | null;
    physics_engine?: string | null;
  } | null;
  images?: GeneratedImage[];
}

const inputCls =
  'w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-sm text-slate-200 focus:outline-none focus:border-blue-500';
const labelCls = 'block text-xs text-slate-400 mb-1';

const CAMERAS = [
  { v: '', l: 'common.choose' },
  { v: 'first_person', l: 'cam.first' },
  { v: 'third_person', l: 'cam.third' },
  { v: 'top_down', l: 'cam.top' },
  { v: 'side_view', l: 'cam.side' },
  { v: 'isometric', l: 'cam.iso' },
];

const AI_TYPES = [
  { v: '', l: 'common.choose' },
  { v: 'finite_state_machine', l: 'ai.fsm' },
  { v: 'behavior_tree', l: 'ai.bt' },
  { v: 'utility_ai', l: 'ai.util' },
  { v: 'goap', l: 'GOAP' },
];

const PHYSICS = [
  { v: '', l: 'common.choose' },
  { v: 'builtin', l: 'phy.builtin' },
  { v: 'physx', l: 'PhysX' },
  { v: 'box2d', l: 'Box2D' },
  { v: 'rapier', l: 'Rapier' },
  { v: 'custom', l: 'phy.custom' },
];

const FEATURES = [
  { v: 'day_night_cycle', l: 'feat.daynight' },
  { v: 'multiplayer', l: 'feat.multi' },
  { v: 'procedural_generation', l: 'feat.proc' },
  { v: 'achievements', l: 'feat.achieve' },
  { v: 'cloud_saves', l: 'feat.cloud' },
  { v: 'mod_support', l: 'feat.mods' },
];

const GENRES = [
  { v: 'action', l: 'Action' },
  { v: 'adventure', l: 'genre.adventure' },
  { v: 'role-playing-games-rpg', l: 'RPG' },
  { v: 'strategy', l: 'genre.strategy' },
  { v: 'shooter', l: 'Shooter' },
  { v: 'simulation', l: 'Simulation' },
  { v: 'platformer', l: 'genre.platformer' },
  { v: 'puzzle', l: 'Puzzle' },
  { v: 'racing', l: 'genre.racing' },
  { v: 'sports', l: 'genre.sports' },
  { v: 'indie', l: 'genre.indie' },
  { v: 'casual', l: 'Casual' },
];

const ENGINES = [
  { v: 'Godot 4', l: 'Godot 4' },
  { v: 'Unity', l: 'Unity' },
  { v: 'Unreal Engine', l: 'Unreal Engine' },
];

const STYLES = [
  { v: 'pixel art', l: 'Pixel art' },
  { v: 'hand-painted digital art', l: 'style.digital' },
  { v: 'anime style', l: 'Anime / manga' },
  { v: 'watercolor', l: 'style.watercolor' },
  { v: 'dark realistic', l: 'style.dark' },
  { v: 'cartoon', l: 'Cartoon' },
];

/* Option labels hold either an I18nKey (always dotted) or a universal literal
(engine names, acronyms): tx() renders both without extra dictionaries. */
function tx(t: (key: I18nKey) => string, s: string): string {
  return s.includes('.') ? t(s as I18nKey) : s;
}

function AutoTextarea({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);
  return (
    <textarea
      ref={ref}
      rows={3}
      placeholder={placeholder}
      value={value}
      onChange={(e) => {
        onChange(e.target.value);
        const el = ref.current;
        if (el) {
          el.style.height = 'auto';
          el.style.height = `${el.scrollHeight}px`;
        }
      }}
      className={`${inputCls} resize-none overflow-hidden`}
    />
  );
}

export default function GDDForm() {
  const { t } = useT();
  const [docType, setDocType] = useState<DocType>('one_sheet');
  const [fields, setFields] = useState<Record<string, string>>({ genre: 'action', engine: 'Godot 4' });
  const [features, setFeatures] = useState<string[]>([]);
  const [visuals, setVisuals] = useState<VisualRow[]>([
    { asset_type: 'concept_art', label: 'Concept Art', enabled: true, count: 2, style: 'pixel art' },
    { asset_type: 'ui_concept', label: 'UI Concept', enabled: false, count: 1, style: 'pixel art' },
    { asset_type: 'sprite', label: 'form.rowSprite', enabled: false, count: 1, style: 'pixel art' },
  ]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<GddResult | null>(null);
  const [gddFormat, setGddFormat] = useState<GddFormat>('md');
  const [pdfBusy, setPdfBusy] = useState(false);
  const [imgFormat, setImgFormat] = useState<ImageFormat>('png');
  const [keyOpen, setKeyOpen] = useState(false);
  const hasKey = useSyncExternalStore(subscribeUserApiKey, getUserApiKeySet, () => false);
  const [runId, setRunId] = useState(0);
  const spend = useSyncExternalStore(subscribeSpend, getSpendSnapshot, () => 0);
  const [regenImgBusy, setRegenImgBusy] = useState<Record<number, boolean>>({});
  const [speaking, setSpeaking] = useState(false);

  useEffect(() => () => stopSpeaking(), []);

  const set =
    (k: string) =>
    (e: ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
      setFields((p) => ({ ...p, [k]: e.target.value }));

  const toggleFeature = (v: string) =>
    setFeatures((p) => (p.includes(v) ? p.filter((f) => f !== v) : [...p, v]));

  const toggleVisual = (asset_type: string) =>
    setVisuals((p) => p.map((r) => (r.asset_type === asset_type ? { ...r, enabled: !r.enabled } : r)));

  const setVisualCount = (asset_type: string, count: number) =>
    setVisuals((p) => p.map((r) => (r.asset_type === asset_type ? { ...r, count } : r)));

  const setVisualStyle = (asset_type: string, style: string) =>
    setVisuals((p) => p.map((r) => (r.asset_type === asset_type ? { ...r, style } : r)));

  const handleSubmit = async () => {
    stopSpeaking();
    setSpeaking(false);
    setLoading(true);
    setError(null);
    setResult(null);
    setRunId((n) => n + 1);
    const clean = (v?: string) => (v && v.trim() ? v.trim() : undefined);
    // Only send fields belonging to the selected doc type: values typed under
    // another type linger in state and must not leak into the request.
    const payload = {
      doc_type: docType,
      genre: fields.genre || undefined,
      engine: fields.engine || undefined,
      title: clean(fields.title),
      platform: clean(fields.platform),
      audience: clean(fields.audience),
      pitch: clean(fields.pitch),
      usp: clean(fields.usp),
      ...(docType !== 'one_sheet'
        ? {
            camera: clean(fields.camera),
            character: clean(fields.character),
            controls: clean(fields.controls),
            core_loop: clean(fields.core_loop),
            menu_flow: clean(fields.menu_flow),
          }
        : {}),
      ...(docType === 'full_gdd'
        ? {
            lore: clean(fields.lore),
            level_design: clean(fields.level_design),
            features,
            ai_type: clean(fields.ai_type),
            physics_engine: clean(fields.physics_engine),
          }
        : {}),
      visuals: visuals.map((v) => ({
        asset_type: v.asset_type,
        enabled: v.enabled,
        count: v.count,
        style: v.style,
      })),
    };
    try {
      const res = await fetch(`${API_URL}/api/v1/generate-gdd`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const text = await res.text().catch(() => '');
        throw new Error(`generate-gdd failed: ${res.status} ${res.statusText} ${text.slice(0, 300)}`);
      }
      const data = (await res.json()) as GddResult;
      setResult(data);
      addSessionSpend(estimateRun(docType, data.images?.length ?? 0, false));
      const { images: _images, ...gddOnly } = data;
      void _images;
      await pushHistory('form', {
        title: data.one_sheet?.title ?? tr('err.untitled'),
        docType: data.document_type,
        gdd: gddOnly,
        code: null,
        images: data.images ?? [],
      }).catch(() => undefined);
    } catch (err) {
      setError(err instanceof Error ? err.message : tr('err.unknown'));
    } finally {
      setLoading(false);
    }
  };

  const regenImage = (index: number) => {
    const img = result?.images?.[index];
    if (!img || !result) return;
    const row = visuals.find((r) => r.asset_type === img.asset_type);
    setRegenImgBusy((p) => ({ ...p, [index]: true }));
    void apiPost<AssetResp>('/api/v1/generate-asset', {
      prompt: result.visual_style_prompt || 'game art',
      asset_type: img.asset_type,
      style: row?.style ?? 'pixel art',
    })
      .then(
        (a) => {
          setResult((prev) =>
            prev
              ? {
                  ...prev,
                  images: (prev.images ?? []).map((it, j) =>
                    j === index
                      ? {
                          asset_type: a.asset_type,
                          prompt_used: a.prompt_used,
                          image_url: a.image_url,
                          status: a.status,
                        }
                      : it,
                  ),
                }
              : prev,
          );
          addSessionSpend(COST_IMAGE_USD);
        },
        (err: unknown) =>
          setError(
            t('err.regenVisual', { msg: err instanceof Error ? err.message : tr('err.unknown') }),
          ),
      )
      .finally(() => setRegenImgBusy((p) => ({ ...p, [index]: false })));
  };

  const narrate = () => {
    if (speaking) {
      stopSpeaking();
      setSpeaking(false);
      return;
    }
    const s = result?.one_sheet;
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
    setResult({
      ...(bundle.gdd as unknown as GddResult),
      images: (bundle.images ?? []).map((img) => ({
        asset_type: img.asset_type,
        prompt_used: img.prompt_used,
        image_url: `/demo/${img.file}`,
        status: img.status,
      })),
    });
  };

  const restoreHistory = (entry: HistoryEntry) => {
    stopSpeaking();
    setSpeaking(false);
    setError(null);
    setLoading(false);
    setResult({ ...(entry.gdd as unknown as GddResult), images: entry.images });
  };

  const downloadGdd = () => {
    if (!result || pdfBusy) return;
    if (gddFormat === 'pdf-pro' || gddFormat === 'pdf-gamebook') {
      const style = gddFormat === 'pdf-pro' ? 'pro' : 'gamebook';
      const base = `gdd-${slugifyFilename(result.one_sheet?.title ?? 'document')}`;
      setPdfBusy(true);
      requestStyledPdf(result, style, result.images ?? [])
        .then((res) => {
          if (res.status !== 'success') setError(res.error ?? tr('err.downloadGdd'));
          else downloadBase64Pdf(res.pdf_base64, `${base}-${gddFormat}.pdf`);
        })
        .catch(() => setError(tr('err.downloadGdd')))
        .finally(() => setPdfBusy(false));
      return;
    }
    try {
      const base = `gdd-${slugifyFilename(result.one_sheet?.title ?? 'document')}`;
      if (gddFormat === 'json') {
        downloadBlob(
          new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' }),
          `${base}.json`,
        );
      } else if (gddFormat === 'txt') {
        downloadBlob(new Blob([gddToText(result)], { type: 'text/plain' }), `${base}.txt`);
      } else if (gddFormat === 'pdf') {
        void downloadGddPdf(result, `${base}.pdf`).catch(() =>
          setError(tr('err.downloadGdd')),
        );
        return;
      } else {
        downloadBlob(new Blob([gddToMarkdown(result)], { type: 'text/markdown' }), `${base}.md`);
      }
    } catch {
      setError(tr('err.downloadGdd'));
    }
  };

  const downloadImg = (img: GeneratedImage, i: number) => {
    void downloadImage(img.image_url, `${img.asset_type}-${i + 1}`, imgFormat);
  };

  return (
    <>
      <Suspense fallback={<p className="text-xs text-slate-500 mb-8">{t('common.loadingExamples')}</p>}>
        <ExamplesRow onLoad={loadDemo} />
      </Suspense>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        {/* Formulaire */}
      <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl h-fit space-y-4">
        <div className="flex justify-between items-center">
          <h2 className="text-xl font-bold text-slate-200">{t('formpage.title')}</h2>
          <div className="flex items-center gap-2">
            {hasKey && <span className="text-xs text-emerald-400">{t('common.personalKeyActive')}</span>}
            <button
              onClick={() => setKeyOpen(true)}
              className="bg-slate-950 text-slate-300 border border-slate-700 hover:border-blue-500 px-2 py-1 rounded-lg text-xs font-semibold transition"
            >
              {t('common.apiKey')}
            </button>
          </div>
        </div>

        <div>
          <label className={labelCls}>{t('form.docType')}</label>
          <select
            className={inputCls}
            value={docType}
            onChange={(e) => setDocType(e.target.value as DocType)}
          >
            <option value="one_sheet">One-Sheet</option>
            <option value="ten_pager">Ten-Pager</option>
            <option value="full_gdd">Full GDD</option>
          </select>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className={labelCls}>{t('form.genre')}</label>
            <select className={inputCls} value={fields.genre ?? 'action'} onChange={set('genre')}>
              {GENRES.map((o) => (
                <option key={o.v} value={o.v}>
                  {tx(t, o.l)}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className={labelCls}>{t('form.engine')}</label>
            <select className={inputCls} value={fields.engine ?? 'Godot 4'} onChange={set('engine')}>
              {ENGINES.map((o) => (
                <option key={o.v} value={o.v}>
                  {tx(t, o.l)}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div>
          <label className={labelCls}>{t('form.titleField')}</label>
          <input className={inputCls} value={fields.title ?? ''} onChange={set('title')} />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className={labelCls}>{t('form.platform')}</label>
            <input className={inputCls} value={fields.platform ?? ''} onChange={set('platform')} />
          </div>
          <div>
            <label className={labelCls}>{t('form.audience')}</label>
            <input className={inputCls} value={fields.audience ?? ''} onChange={set('audience')} />
          </div>
        </div>
        <div>
          <div className="flex justify-between items-center mb-1">
            <label className="text-xs text-slate-400">Pitch</label>
            <DictationButton
              onText={(t) =>
                setFields((p) => ({ ...p, pitch: p.pitch ? `${p.pitch} ${t}` : t }))
              }
            />
          </div>
          <input className={inputCls} value={fields.pitch ?? ''} onChange={set('pitch')} />
        </div>
        <div>
          <label className={labelCls}>USP</label>
          <input className={inputCls} value={fields.usp ?? ''} onChange={set('usp')} />
        </div>

        {docType !== 'one_sheet' && (
          <div className="space-y-4 pt-2 border-t border-slate-800">
            <h3 className="text-sm font-bold text-slate-300 pt-2">{t('form.rule3c')}</h3>
            <div>
              <label className={labelCls}>{t('form.camera')}</label>
              <select className={inputCls} value={fields.camera ?? ''} onChange={set('camera')}>
                {CAMERAS.map((o) => (
                  <option key={o.v} value={o.v}>
                    {tx(t, o.l)}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className={labelCls}>{t('form.character')}</label>
              <input className={inputCls} value={fields.character ?? ''} onChange={set('character')} />
            </div>
            <div>
              <label className={labelCls}>{t('form.controls')}</label>
              <input className={inputCls} value={fields.controls ?? ''} onChange={set('controls')} />
            </div>
            <div>
              <label className={labelCls}>Core Loop</label>
              <textarea
                rows={3}
                className={inputCls}
                value={fields.core_loop ?? ''}
                onChange={set('core_loop')}
              />
            </div>
            <div>
              <label className={labelCls}>{t('form.menuFlow')}</label>
              <textarea
                rows={3}
                className={inputCls}
                value={fields.menu_flow ?? ''}
                onChange={set('menu_flow')}
              />
            </div>
          </div>
        )}

        {docType === 'full_gdd' && (
          <div className="space-y-4 pt-2 border-t border-slate-800">
            <h3 className="text-sm font-bold text-slate-300 pt-2">Full GDD</h3>
            <div>
              <label className={labelCls}>Lore</label>
              <AutoTextarea
                value={fields.lore ?? ''}
                onChange={(v) => setFields((p) => ({ ...p, lore: v }))}
              />
            </div>
            <div>
              <label className={labelCls}>Level Design</label>
              <AutoTextarea
                value={fields.level_design ?? ''}
                onChange={(v) => setFields((p) => ({ ...p, level_design: v }))}
              />
            </div>
            <div>
              <label className={labelCls}>Features</label>
              <div className="space-y-1 text-sm text-slate-200">
                {FEATURES.map((f) => (
                  <label key={f.v} className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      className="accent-blue-600"
                      checked={features.includes(f.v)}
                      onChange={() => toggleFeature(f.v)}
                    />
                    {tx(t, f.l)}
                  </label>
                ))}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className={labelCls}>{t('form.aiType')}</label>
                <select className={inputCls} value={fields.ai_type ?? ''} onChange={set('ai_type')}>
                  {AI_TYPES.map((o) => (
                    <option key={o.v} value={o.v}>
                      {tx(t, o.l)}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className={labelCls}>{t('form.physics')}</label>
                <select
                  className={inputCls}
                  value={fields.physics_engine ?? ''}
                  onChange={set('physics_engine')}
                >
                  {PHYSICS.map((o) => (
                    <option key={o.v} value={o.v}>
                      {tx(t, o.l)}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </div>
        )}

        <div className="space-y-2 pt-2 border-t border-slate-800">
          <h3 className="text-sm font-bold text-slate-300 pt-2">{t('form.visualGen')}</h3>
          {visuals.map((r) => (
            <div key={r.asset_type} className="flex flex-wrap items-center gap-3 text-sm text-slate-200">
              <label className="flex items-center gap-2 cursor-pointer min-w-40">
                <input
                  type="checkbox"
                  className="accent-blue-600"
                  checked={r.enabled}
                  onChange={() => toggleVisual(r.asset_type)}
                />
                {tx(t, r.label)}
              </label>
              {r.enabled && (
                <>
                  <select
                    aria-label={t('form.qtyAria', { label: tx(t, r.label) })}
                    className="bg-slate-950 border border-slate-800 rounded-lg p-1 text-sm text-slate-200"
                    value={r.count}
                    onChange={(e) => setVisualCount(r.asset_type, parseInt(e.target.value, 10))}
                  >
                    {[1, 2, 3, 4, 5].map((n) => (
                      <option key={n} value={n}>
                        {t(n > 1 ? 'form.imgMany' : 'form.imgOne', { n })}
                      </option>
                    ))}
                  </select>
                  <select
                    aria-label={t('form.styleAria', { label: tx(t, r.label) })}
                    className="bg-slate-950 border border-slate-800 rounded-lg p-1 text-sm text-slate-200"
                    value={r.style}
                    onChange={(e) => setVisualStyle(r.asset_type, e.target.value)}
                  >
                    {STYLES.map((s) => (
                      <option key={s.v} value={s.v}>
                        {tx(t, s.l)}
                      </option>
                    ))}
                  </select>
                </>
              )}
            </div>
          ))}
          <p className="text-xs text-slate-500">{t('form.perImage')}</p>
        </div>

        <button
          onClick={handleSubmit}
          disabled={loading}
          className="w-full bg-blue-600 hover:bg-blue-500 disabled:bg-slate-800 text-white font-bold py-3 px-4 rounded-lg transition"
        >
          {loading ? t('common.generating') : t('form.submit')}
        </button>
        <p className="text-xs text-slate-500">
          {t('common.estimatedCost')}{' '}
          <span className="font-mono text-slate-400">
            {formatCost(
              estimateRun(
                docType,
                visuals.filter((r) => r.enabled).reduce((n, r) => n + r.count, 0),
                false,
              ),
            )}
          </span>{' '}
          · {t('common.session')} <span className="font-mono text-slate-400">{formatCost(spend)}</span>
        </p>

        {error && (
          <p className="text-xs text-red-400 bg-red-950/40 border border-red-500/30 rounded-lg p-3 break-words whitespace-pre-line">
            {translateError(error)}
          </p>
        )}
      </div>

      {/* Résultat */}
      <div className="space-y-6">
        {loading && (
          <GenerationProgress
            key={runId}
            stages={[{ label: t('stage.docVisuals'), state: 'active' }]}
          />
        )}
        <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl">
          <div className="flex flex-wrap justify-between items-center gap-2 mb-2">
            <h2 className="text-lg font-bold text-blue-400">{t('form.resultTitle')}</h2>
            {result && (
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
                  onClick={() => void handleSubmit()}
                  disabled={loading}
                  className="bg-slate-950 text-slate-300 border border-slate-700 hover:border-blue-500 disabled:opacity-50 text-xs font-semibold py-1 px-3 rounded-lg transition"
                >
                  {t('common.regenerate')}
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
          {result ? (
            <div className="space-y-3 text-sm text-slate-300">
              <p className="text-xs text-slate-500">
                {t('common.format')} <span className="font-mono text-slate-400">{result.document_type}</span>
              </p>
              <p>
                <strong className="text-white">{t('common.title')}</strong> {result.one_sheet?.title}
              </p>
              <p>
                <strong className="text-white">{t('common.summary')}</strong> {result.one_sheet?.story_summary}
              </p>
              {result.one_sheet?.usps && result.one_sheet.usps.length > 0 && (
                <ul className="list-disc list-inside space-y-1 text-slate-400">
                  {result.one_sheet.usps.map((u, i) => (
                    <li key={i}>{u}</li>
                  ))}
                </ul>
              )}
              {result.ten_pager && (
                <p className="text-xs text-slate-500">
                  3C : {result.ten_pager.camera ?? '?'} · {result.ten_pager.character ?? '?'} ·{' '}
                  {result.ten_pager.controls ?? '?'}
                </p>
              )}
              {result.full_gdd && (result.full_gdd.features?.length ?? 0) > 0 && (
                <p className="text-xs text-slate-500">
                  {t('form.featuresLine', { list: result.full_gdd.features?.join(', ') ?? '' })}
                </p>
              )}
              <FallbackBadge status={result.status} message={t('form.fallbackShort')} />
            </div>
          ) : (
            <p className="text-xs text-slate-500 italic">
              {loading ? t('common.generating') : t('common.waiting')}
            </p>
          )}
        </div>

        <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl">
          <div className="flex flex-wrap justify-between items-center gap-2 mb-2">
            <h2 className="text-lg font-bold text-purple-400">{t('form.visualsTitle')}</h2>
            {result && result.images && result.images.length > 0 && (
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
          {result && result.images && result.images.length > 0 ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {result.images.map((img, i) => (
                <div key={i} className="space-y-1">
                  <div className="flex justify-between items-center">
                    <p className="text-xs font-mono text-purple-400">{img.asset_type}</p>
                    <div className="flex items-center gap-2">
                      {img.asset_type === 'sprite' && (
                        <CutoutPanel imageUrl={img.image_url} fileBase={`${img.asset_type}-${i + 1}`} />
                      )}
                      <button
                        onClick={() => regenImage(i)}
                        disabled={regenImgBusy[i] || loading}
                        className="bg-slate-950 text-slate-300 border border-slate-700 hover:border-blue-500 disabled:opacity-50 text-xs font-semibold py-1 px-3 rounded-lg transition"
                      >
                        {regenImgBusy[i] ? '…' : t('common.regenerate')}
                      </button>
                      <button
                        onClick={() => downloadImg(img, i)}
                        className="bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold py-1 px-3 rounded-lg transition"
                      >
                        {t('common.download')}
                      </button>
                    </div>
                  </div>
                  <img
                    src={img.image_url}
                    alt={`Generated ${img.asset_type}`}
                    className="w-full rounded-lg border border-slate-800 bg-slate-950"
                  />
                  <FallbackBadge status={img.status} message={t('assets.fallback')} />
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-slate-500 italic">
              {loading ? t('common.generating') : t('common.waiting')}
            </p>
          )}
        </div>
        <MusicCard />
      </div>
      {keyOpen && <APIKeyModal onClose={() => setKeyOpen(false)} />}
      </div>
      <div className="mt-8">
        <HistoryPanel page="form" onRestore={restoreHistory} />
      </div>
    </>
  );
}
