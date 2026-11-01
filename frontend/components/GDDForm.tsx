'use client';

import { useRef, useState, type ChangeEvent } from 'react';
import {
  downloadBlob,
  downloadGddPdf,
  downloadImage,
  gddToMarkdown,
  gddToText,
  slugifyFilename,
  type GddFormat,
  type ImageFormat,
} from '../lib/download';

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
  { v: '', l: '— Choisir —' },
  { v: 'first_person', l: 'Première personne' },
  { v: 'third_person', l: 'Troisième personne' },
  { v: 'top_down', l: 'Vue du dessus' },
  { v: 'side_view', l: 'Vue de côté' },
  { v: 'isometric', l: 'Isométrique' },
];

const AI_TYPES = [
  { v: '', l: '— Choisir —' },
  { v: 'finite_state_machine', l: 'Machine à états' },
  { v: 'behavior_tree', l: 'Arbre de comportement' },
  { v: 'utility_ai', l: 'IA utilitaire' },
  { v: 'goap', l: 'GOAP' },
];

const PHYSICS = [
  { v: '', l: '— Choisir —' },
  { v: 'builtin', l: 'Moteur intégré' },
  { v: 'physx', l: 'PhysX' },
  { v: 'box2d', l: 'Box2D' },
  { v: 'rapier', l: 'Rapier' },
  { v: 'custom', l: 'Maison' },
];

const FEATURES = [
  { v: 'day_night_cycle', l: 'Cycle jour/nuit' },
  { v: 'multiplayer', l: 'Multijoueur' },
  { v: 'procedural_generation', l: 'Génération procédurale' },
  { v: 'achievements', l: 'Succès' },
  { v: 'cloud_saves', l: 'Sauvegardes cloud' },
  { v: 'mod_support', l: 'Support des mods' },
];

const GENRES = [
  { v: 'action', l: 'Action' },
  { v: 'adventure', l: 'Aventure' },
  { v: 'role-playing-games-rpg', l: 'RPG' },
  { v: 'strategy', l: 'Stratégie' },
  { v: 'shooter', l: 'Shooter' },
  { v: 'simulation', l: 'Simulation' },
  { v: 'platformer', l: 'Plateforme' },
  { v: 'puzzle', l: 'Puzzle' },
  { v: 'racing', l: 'Course' },
  { v: 'sports', l: 'Sport' },
  { v: 'indie', l: 'Indé' },
  { v: 'casual', l: 'Casual' },
];

const ENGINES = [
  { v: 'Godot 4', l: 'Godot 4' },
  { v: 'Unity', l: 'Unity' },
  { v: 'Unreal Engine', l: 'Unreal Engine' },
];

const STYLES = [
  { v: 'pixel art', l: 'Pixel art' },
  { v: 'hand-painted digital art', l: 'Peinture numérique' },
  { v: 'anime style', l: 'Anime / manga' },
  { v: 'watercolor', l: 'Aquarelle' },
  { v: 'dark realistic', l: 'Réaliste sombre' },
  { v: 'cartoon', l: 'Cartoon' },
];

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
  const [docType, setDocType] = useState<DocType>('one_sheet');
  const [fields, setFields] = useState<Record<string, string>>({ genre: 'action', engine: 'Godot 4' });
  const [features, setFeatures] = useState<string[]>([]);
  const [visuals, setVisuals] = useState<VisualRow[]>([
    { asset_type: 'concept_art', label: 'Concept Art', enabled: true, count: 2, style: 'pixel art' },
    { asset_type: 'ui_concept', label: 'UI Concept', enabled: false, count: 1, style: 'pixel art' },
    { asset_type: 'sprite', label: 'Sprite / Modèle', enabled: false, count: 1, style: 'pixel art' },
  ]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<GddResult | null>(null);
  const [gddFormat, setGddFormat] = useState<GddFormat>('md');
  const [imgFormat, setImgFormat] = useState<ImageFormat>('png');

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
    setLoading(true);
    setError(null);
    setResult(null);
    const clean = (v?: string) => (v && v.trim() ? v.trim() : undefined);
    const payload = {
      doc_type: docType,
      genre: fields.genre || undefined,
      engine: fields.engine || undefined,
      title: clean(fields.title),
      platform: clean(fields.platform),
      audience: clean(fields.audience),
      pitch: clean(fields.pitch),
      usp: clean(fields.usp),
      camera: clean(fields.camera),
      character: clean(fields.character),
      controls: clean(fields.controls),
      core_loop: clean(fields.core_loop),
      menu_flow: clean(fields.menu_flow),
      lore: clean(fields.lore),
      level_design: clean(fields.level_design),
      features,
      ai_type: clean(fields.ai_type),
      physics_engine: clean(fields.physics_engine),
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
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const text = await res.text().catch(() => '');
        throw new Error(`generate-gdd failed: ${res.status} ${res.statusText} ${text.slice(0, 300)}`);
      }
      setResult((await res.json()) as GddResult);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown generation error');
    } finally {
      setLoading(false);
    }
  };

  const downloadGdd = () => {
    if (!result) return;
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
          setError('Téléchargement du GDD impossible.'),
        );
        return;
      } else {
        downloadBlob(new Blob([gddToMarkdown(result)], { type: 'text/markdown' }), `${base}.md`);
      }
    } catch {
      setError('Téléchargement du GDD impossible.');
    }
  };

  const downloadImg = (img: GeneratedImage, i: number) => {
    void downloadImage(img.image_url, `${img.asset_type}-${i + 1}`, imgFormat);
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
      {/* Formulaire */}
      <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl h-fit space-y-4">
        <h2 className="text-xl font-bold text-slate-200">Document Rogers</h2>

        <div>
          <label className={labelCls}>Type de GDD</label>
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
            <label className={labelCls}>Genre</label>
            <select className={inputCls} value={fields.genre ?? 'action'} onChange={set('genre')}>
              {GENRES.map((o) => (
                <option key={o.v} value={o.v}>
                  {o.l}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className={labelCls}>Moteur</label>
            <select className={inputCls} value={fields.engine ?? 'Godot 4'} onChange={set('engine')}>
              {ENGINES.map((o) => (
                <option key={o.v} value={o.v}>
                  {o.l}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div>
          <label className={labelCls}>Titre</label>
          <input className={inputCls} value={fields.title ?? ''} onChange={set('title')} />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className={labelCls}>Plateforme</label>
            <input className={inputCls} value={fields.platform ?? ''} onChange={set('platform')} />
          </div>
          <div>
            <label className={labelCls}>Public cible</label>
            <input className={inputCls} value={fields.audience ?? ''} onChange={set('audience')} />
          </div>
        </div>
        <div>
          <label className={labelCls}>Pitch</label>
          <input className={inputCls} value={fields.pitch ?? ''} onChange={set('pitch')} />
        </div>
        <div>
          <label className={labelCls}>USP</label>
          <input className={inputCls} value={fields.usp ?? ''} onChange={set('usp')} />
        </div>

        {docType !== 'one_sheet' && (
          <div className="space-y-4 pt-2 border-t border-slate-800">
            <h3 className="text-sm font-bold text-slate-300 pt-2">Règle des 3C</h3>
            <div>
              <label className={labelCls}>Caméra</label>
              <select className={inputCls} value={fields.camera ?? ''} onChange={set('camera')}>
                {CAMERAS.map((o) => (
                  <option key={o.v} value={o.v}>
                    {o.l}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className={labelCls}>Personnage</label>
              <input className={inputCls} value={fields.character ?? ''} onChange={set('character')} />
            </div>
            <div>
              <label className={labelCls}>Contrôles</label>
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
              <label className={labelCls}>Flow des menus</label>
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
                    {f.l}
                  </label>
                ))}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className={labelCls}>Type d&apos;IA</label>
                <select className={inputCls} value={fields.ai_type ?? ''} onChange={set('ai_type')}>
                  {AI_TYPES.map((o) => (
                    <option key={o.v} value={o.v}>
                      {o.l}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className={labelCls}>Moteur physique</label>
                <select
                  className={inputCls}
                  value={fields.physics_engine ?? ''}
                  onChange={set('physics_engine')}
                >
                  {PHYSICS.map((o) => (
                    <option key={o.v} value={o.v}>
                      {o.l}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </div>
        )}

        <div className="space-y-2 pt-2 border-t border-slate-800">
          <h3 className="text-sm font-bold text-slate-300 pt-2">Génération visuelle</h3>
          {visuals.map((r) => (
            <div key={r.asset_type} className="flex flex-wrap items-center gap-3 text-sm text-slate-200">
              <label className="flex items-center gap-2 cursor-pointer min-w-40">
                <input
                  type="checkbox"
                  className="accent-blue-600"
                  checked={r.enabled}
                  onChange={() => toggleVisual(r.asset_type)}
                />
                {r.label}
              </label>
              {r.enabled && (
                <>
                  <select
                    aria-label={`Quantité ${r.label}`}
                    className="bg-slate-950 border border-slate-800 rounded-lg p-1 text-sm text-slate-200"
                    value={r.count}
                    onChange={(e) => setVisualCount(r.asset_type, parseInt(e.target.value, 10))}
                  >
                    {[1, 2, 3, 4, 5].map((n) => (
                      <option key={n} value={n}>
                        {n} image{n > 1 ? 's' : ''}
                      </option>
                    ))}
                  </select>
                  <select
                    aria-label={`Style ${r.label}`}
                    className="bg-slate-950 border border-slate-800 rounded-lg p-1 text-sm text-slate-200"
                    value={r.style}
                    onChange={(e) => setVisualStyle(r.asset_type, e.target.value)}
                  >
                    {STYLES.map((s) => (
                      <option key={s.v} value={s.v}>
                        {s.l}
                      </option>
                    ))}
                  </select>
                </>
              )}
            </div>
          ))}
          <p className="text-xs text-slate-500">Images réelles facturées ~0,01 $/image.</p>
        </div>

        <button
          onClick={handleSubmit}
          disabled={loading}
          className="w-full bg-blue-600 hover:bg-blue-500 disabled:bg-slate-800 text-white font-bold py-3 px-4 rounded-lg transition"
        >
          {loading ? 'Génération en cours...' : 'Générer le GDD'}
        </button>

        {error && (
          <p className="text-xs text-red-400 bg-red-950/40 border border-red-500/30 rounded-lg p-3 break-words whitespace-pre-line">
            {error}
          </p>
        )}
      </div>

      {/* Résultat */}
      <div className="space-y-6">
        <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl">
          <div className="flex flex-wrap justify-between items-center gap-2 mb-2">
            <h2 className="text-lg font-bold text-blue-400">Document généré</h2>
            {result && (
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
          {result ? (
            <div className="space-y-3 text-sm text-slate-300">
              <p className="text-xs text-slate-500">
                Format : <span className="font-mono text-slate-400">{result.document_type}</span>
              </p>
              <p>
                <strong className="text-white">Titre :</strong> {result.one_sheet?.title}
              </p>
              <p>
                <strong className="text-white">Résumé :</strong> {result.one_sheet?.story_summary}
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
                  Features : {result.full_gdd.features?.join(', ')}
                </p>
              )}
              {result.status && result.status !== 'success' && (
                <p className="text-xs text-amber-400 italic">Contenu de secours (voir logs backend).</p>
              )}
            </div>
          ) : (
            <p className="text-xs text-slate-500 italic">
              {loading ? 'Génération en cours...' : 'En attente de génération...'}
            </p>
          )}
        </div>

        <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl">
          <div className="flex flex-wrap justify-between items-center gap-2 mb-2">
            <h2 className="text-lg font-bold text-purple-400">Visuels générés</h2>
            {result && result.images && result.images.length > 0 && (
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
          {result && result.images && result.images.length > 0 ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {result.images.map((img, i) => (
                <div key={i} className="space-y-1">
                  <div className="flex justify-between items-center">
                    <p className="text-xs font-mono text-purple-400">{img.asset_type}</p>
                    <button
                      onClick={() => downloadImg(img, i)}
                      className="bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold py-1 px-3 rounded-lg transition"
                    >
                      Télécharger
                    </button>
                  </div>
                  <img
                    src={img.image_url}
                    alt={`Generated ${img.asset_type}`}
                    className="w-full rounded-lg border border-slate-800 bg-slate-950"
                  />
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-slate-500 italic">
              {loading ? 'Génération en cours...' : 'En attente de génération...'}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
