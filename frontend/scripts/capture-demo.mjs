// Captures real demo bundles (GDD + code + images) into public/demo/.
// Usage from frontend/:  node scripts/capture-demo.mjs
// Requires the backend up with Meta keys. Refuses mock/placeholder content:
// a demo bundle must be a genuine generation (status === 'success').
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const API = process.env.API_URL ?? 'http://127.0.0.1:8000';
const OUT = join(dirname(fileURLToPath(import.meta.url)), '..', 'public', 'demo');
mkdirSync(OUT, { recursive: true });

async function post(path, body) {
  const res = await fetch(`${API}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${path} -> ${res.status} ${(await res.text()).slice(0, 200)}`);
  return res.json();
}

const SPECS = [
  {
    id: 'ex1',
    genre: 'Survie / Horreur',
    engine: 'Godot 4',
    docType: 'one_sheet',
    gdd: {
      prompt: 'Un jeu de survie contre des hordes de zombies dans un cimetière brumeux',
      doc_type: 'one_sheet',
      engine: 'Godot 4',
    },
    codePrompt: 'Un jeu de survie contre des hordes de zombies dans un cimetière brumeux',
    visuals: [
      { type: 'sprite', style: 'pixel art' },
      { type: 'concept_art', style: 'pixel art' },
    ],
  },
  {
    id: 'ex2',
    genre: 'Space-opera',
    engine: 'Unity',
    docType: 'ten_pager',
    gdd: {
      doc_type: 'ten_pager',
      genre: 'adventure',
      engine: 'Unity',
      title: 'Starfall Odyssey',
      platform: 'PC',
      audience: '12+',
      pitch: 'Explorez des planètes inconnues, commercez entre stations orbitales et améliorez votre vaisseau.',
      usp: 'Univers persistant avec commerce dynamique entre stations',
      camera: 'third_person',
      character: 'Capitaine Nova',
      controls: 'Manette + clavier',
      core_loop: 'Explorer, commercer, améliorer',
      menu_flow: 'Titre > Carte stellaire > Hangar',
    },
    codePrompt: 'Contrôleur de vaisseau spatial : poussée, rotation et arrimage aux stations',
    visuals: [
      { type: 'concept_art', style: 'watercolor' },
      { type: 'ui_concept', style: 'watercolor' },
    ],
  },
];

function extOf(mime) {
  if (mime.includes('jpeg')) return 'jpg';
  if (mime.includes('webp')) return 'webp';
  return 'png';
}

async function saveImage(imageUrl, base) {
  let bytes;
  let ext;
  if (imageUrl.startsWith('data:')) {
    const [head, b64] = imageUrl.split(',', 2);
    ext = extOf(head);
    bytes = Buffer.from(b64, 'base64');
  } else {
    const res = await fetch(imageUrl);
    if (!res.ok) throw new Error(`image fetch -> ${res.status}`);
    ext = extOf(res.headers.get('content-type') || '');
    bytes = Buffer.from(await res.arrayBuffer());
  }
  if (bytes.length < 1024) throw new Error(`image too small (${bytes.length}B): ${base}`);
  const file = `${base}.${ext}`;
  writeFileSync(join(OUT, file), bytes);
  return { file, bytes: bytes.length };
}

const manifest = [];
for (const spec of SPECS) {
  console.log(`--- ${spec.id} (${spec.genre}) ---`);
  const gdd = await post('/api/v1/generate-gdd', spec.gdd);
  if (gdd.status !== 'success') throw new Error(`${spec.id}: GDD status=${gdd.status}`);
  const code = await post('/api/v1/generate-code', { prompt: spec.codePrompt, engine: spec.engine });
  if (code.status !== 'success') throw new Error(`${spec.id}: code status=${code.status}`);
  const stylePrompt = gdd.visual_style_prompt || spec.codePrompt;
  const images = [];
  for (const [i, v] of spec.visuals.entries()) {
    const a = await post('/api/v1/generate-asset', {
      prompt: stylePrompt,
      asset_type: v.type,
      style: v.style,
    });
    if (a.status !== 'success') throw new Error(`${spec.id}: image ${i} status=${a.status}`);
    const saved = await saveImage(a.image_url, `${spec.id}-${i}`);
    console.log(`image ${i} (${v.type}): ${saved.file} ${saved.bytes}B`);
    images.push({
      asset_type: a.asset_type,
      prompt_used: a.prompt_used,
      file: saved.file,
      status: a.status,
    });
  }
  const bundle = {
    id: spec.id,
    title: gdd.one_sheet?.title ?? spec.id,
    genre: spec.genre,
    engine: spec.engine,
    docType: gdd.document_type,
    gdd,
    code,
    images,
  };
  writeFileSync(join(OUT, `${spec.id}.json`), JSON.stringify(bundle));
  manifest.push({
    id: spec.id,
    title: bundle.title,
    genre: spec.genre,
    docType: bundle.docType,
    engine: spec.engine,
    file: `${spec.id}.json`,
    thumb: `/demo/${images[0].file}`,
  });
  console.log(`${spec.id}: OK (${bundle.title})`);
}
writeFileSync(join(OUT, 'manifest.json'), JSON.stringify(manifest, null, 2));
console.log(`manifest: ${manifest.length} bundles in ${OUT}`);
