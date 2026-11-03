/* Shared download helpers: GDD/code export formats + image conversion. */

import type { jsPDF } from 'jspdf';
import { apiPost } from './api';

export type ImageFormat = 'png' | 'jpg' | 'webp' | 'pdf';
export type GddFormat = 'md' | 'json' | 'txt' | 'pdf' | 'pdf-pro' | 'pdf-gamebook';
export type CodeFormat = 'source' | 'txt' | 'pdf';

const IMAGE_MIMES: Record<Exclude<ImageFormat, 'pdf'>, string> = {
  png: 'image/png',
  jpg: 'image/jpeg',
  webp: 'image/webp',
};

export interface BeatLevelLike {
  level_name: string;
  progression_focus: string;
  mechanics_introduced?: string[];
  enemies_introduced?: string[];
  estimated_play_time?: string;
}

export interface GddDownloadData {
  document_type?: string;
  status?: string;
  one_sheet?: {
    title?: string;
    target_systems?: string[];
    target_age?: string;
    esrb_rating?: string;
    story_summary?: string;
    gameplay_modes?: string[];
    usps?: string[];
    competitive_products?: string[];
  };
  beat_chart?: BeatLevelLike[] | null;
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
}

export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Revoke late: the browser may queue rapid downloads and only read the blob
  // URL seconds after the click; revoking early aborts the queued download.
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

export interface StyledPdfResult {
  status: string;
  pdf_base64: string;
  error?: string | null;
}

function absoluteUrl(url: string): string {
  if (/^(https?:|data:)/.test(url)) return url;
  if (typeof window === 'undefined') return url;
  return new URL(url, window.location.origin).toString();
}

export function requestStyledPdf(
  gdd: unknown,
  style: 'pro' | 'gamebook',
  images: { image_url?: string }[],
): Promise<StyledPdfResult> {
  return apiPost<StyledPdfResult>('/api/v1/gdd-pdf', {
    gdd,
    style,
    images: images
      .filter((i) => i.image_url)
      .slice(0, 3)
      .map((i) => ({ image_url: absoluteUrl(String(i.image_url)) })),
  });
}

export function downloadBase64Pdf(b64: string, filename: string): void {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  downloadBlob(new Blob([bytes.buffer as ArrayBuffer], { type: 'application/pdf' }), filename);
}

export function slugifyFilename(name: string, fallback = 'gdd'): string {
  const slug = name
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return slug || fallback;
}

export function gddToMarkdown(g: GddDownloadData): string {
  const s = g.one_sheet ?? {};
  // Render only the sections of the requested document type (doc ladder:
  // one_sheet < beat_chart / ten_pager < full_gdd). Unknown types render all.
  const docType = g.document_type ?? '';
  const scoped = ['one_sheet', 'ten_pager', 'beat_chart', 'full_gdd'].includes(docType);
  const wantBeat = !scoped || docType === 'beat_chart' || docType === 'full_gdd';
  const wantTen = !scoped || docType === 'ten_pager' || docType === 'full_gdd';
  const wantFull = !scoped || docType === 'full_gdd';
  const lines: string[] = [];
  lines.push(`# ${s.title ?? 'Untitled Game'}`, '');
  if (g.document_type) lines.push(`_Format: ${g.document_type}_`, '');
  lines.push('## One-Sheet', '');
  if (s.story_summary) lines.push(s.story_summary, '');
  const meta: string[] = [];
  if (s.target_systems?.length) meta.push(`- **Systems:** ${s.target_systems.join(', ')}`);
  if (s.target_age) meta.push(`- **Target age:** ${s.target_age}`);
  if (s.esrb_rating) meta.push(`- **ESRB:** ${s.esrb_rating}`);
  if (s.gameplay_modes?.length) meta.push(`- **Modes:** ${s.gameplay_modes.join(', ')}`);
  if (s.competitive_products?.length)
    meta.push(`- **Competitors:** ${s.competitive_products.join(', ')}`);
  if (meta.length) lines.push(...meta, '');
  if (s.usps?.length) {
    lines.push('### USPs', '', ...s.usps.map((u) => `- ${u}`), '');
  }
  const beat = wantBeat ? (g.beat_chart ?? []) : [];
  if (beat.length) {
    lines.push('## Beat Chart', '');
    for (const lvl of beat) {
      lines.push(`### ${lvl.level_name} (${lvl.estimated_play_time ?? '?'})`, '');
      lines.push(lvl.progression_focus, '');
      lines.push(`- Mechanics: ${(lvl.mechanics_introduced ?? []).join(', ') || '—'}`);
      lines.push(`- Enemies: ${(lvl.enemies_introduced ?? []).join(', ') || '—'}`, '');
    }
  }
  if (wantTen && g.ten_pager) {
    const t = g.ten_pager;
    const rows = [
      t.camera && `- **Camera:** ${t.camera}`,
      t.character && `- **Character:** ${t.character}`,
      t.controls && `- **Controls:** ${t.controls}`,
      t.core_loop && `- **Core loop:** ${t.core_loop}`,
      t.menu_flow && `- **Menu flow:** ${t.menu_flow}`,
    ].filter(Boolean) as string[];
    if (rows.length) lines.push('## Ten-Pager (3C)', '', ...rows, '');
  }
  if (wantFull && g.full_gdd) {
    const f = g.full_gdd;
    const has = f.lore || f.level_design || (f.features?.length ?? 0) > 0 || f.ai_type || f.physics_engine;
    if (has) {
      lines.push('## Full GDD', '');
      if (f.lore) lines.push('### Lore', '', f.lore, '');
      if (f.level_design) lines.push('### Level Design', '', f.level_design, '');
      if (f.features?.length) lines.push('### Features', '', ...f.features.map((x) => `- ${x}`), '');
      if (f.ai_type) lines.push(`- **AI:** ${f.ai_type}`);
      if (f.physics_engine) lines.push(`- **Physics:** ${f.physics_engine}`);
      if (f.ai_type || f.physics_engine) lines.push('');
    }
  }
  if (g.visual_style_prompt) lines.push('## Visual style', '', g.visual_style_prompt, '');
  return lines.join('\n');
}

export function gddToText(g: GddDownloadData): string {
  return gddToMarkdown(g)
    .replace(/^#{1,3} /gm, '')
    .replace(/\*\*/g, '')
    .replace(/^_([^_]*)_$/gm, '$1')
    .replace(/^- /gm, '• ');
}

export function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('decode'));
    img.src = src;
  });
}

export function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(new Error('read'));
    reader.readAsDataURL(blob);
  });
}

export async function imageToThumbnail(src: string, maxSide = 192): Promise<string> {
  let url = src;
  if (!url.startsWith('data:')) {
    const res = await fetch(url);
    if (!res.ok) throw new Error('fetch');
    url = await blobToDataUrl(await res.blob());
  }
  const img = await loadImage(url);
  const scale = Math.min(1, maxSide / Math.max(img.naturalWidth, img.naturalHeight));
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(img.naturalWidth * scale));
  canvas.height = Math.max(1, Math.round(img.naturalHeight * scale));
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('canvas');
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL('image/jpeg', 0.7);
}

async function convertImage(src: string, mime: string): Promise<Blob> {
  if (src.startsWith(`data:${mime};base64,`)) {
    const bin = atob(src.split(',', 2)[1]);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new Blob([bytes], { type: mime });
  }
  const img = await loadImage(src);
  const canvas = document.createElement('canvas');
  canvas.width = img.naturalWidth;
  canvas.height = img.naturalHeight;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('canvas');
  if (mime === 'image/jpeg') {
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
  }
  ctx.drawImage(img, 0, 0);
  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, mime, 0.92));
  if (!blob) throw new Error('encode');
  return blob;
}

export async function downloadImage(
  imageUrl: string,
  filenameBase: string,
  format: ImageFormat,
): Promise<void> {
  try {
    let src = imageUrl;
    if (!src.startsWith('data:')) {
      const res = await fetch(src);
      if (!res.ok) throw new Error('fetch');
      src = await blobToDataUrl(await res.blob());
    }
    if (format === 'pdf') {
      await downloadImagePdf(src, filenameBase);
      return;
    }
    const out = await convertImage(src, IMAGE_MIMES[format]);
    downloadBlob(out, `${filenameBase}.${format}`);
  } catch (err) {
    console.warn('downloadImage: conversion failed, opening original', err);
    window.open(imageUrl, '_blank', 'noopener');
  }
}

/* ---------- PDF generation (jsPDF, client-side, lazy-loaded) ---------- */

/* jsPDF base-14 fonts cover latin-1 only: map common punctuation, drop the rest
   (accents like é/è/ç survive, emoji are stripped). */
function pdfSafe(s: string): string {
  return s
    .replace(/[—–]/g, '-')
    .replace(/[‘’]/g, "'")
    .replace(/[“”]/g, '"')
    .replace(/…/g, '...')
    .replace(/•/g, '-')
    .replace(/[^\x00-\xFF]/g, '');
}

function addPageNumbers(doc: InstanceType<typeof jsPDF>, pageW: number, pageH: number, margin: number): void {
  const n = doc.getNumberOfPages();
  doc.setFont('helvetica', 'normal');
  doc.setFontSize(8);
  for (let i = 1; i <= n; i++) {
    doc.setPage(i);
    doc.text(`${i} / ${n}`, pageW - margin, pageH - 8, { align: 'right' });
  }
}

export async function downloadGddPdf(g: GddDownloadData, filename: string): Promise<void> {
  const { jsPDF } = await import('jspdf');
  const doc = new jsPDF({ unit: 'mm', format: 'a4' });
  const pageW = 210;
  const pageH = 297;
  const m = 15;
  const maxW = pageW - m * 2;
  let y = m;

  const write = (text: string, size: number, style: 'normal' | 'bold' | 'italic', indent = 0) => {
    const clean = pdfSafe(text).trim();
    if (!clean) {
      y += 2;
      return;
    }
    doc.setFont('helvetica', style);
    doc.setFontSize(size);
    const lines = doc.splitTextToSize(clean, maxW - indent) as string[];
    const lh = size * 0.45;
    for (const ln of lines) {
      if (y + lh > pageH - m) {
        doc.addPage();
        y = m;
      }
      doc.text(ln, m + indent, y);
      y += lh;
    }
    y += 1.5;
  };

  for (const raw of gddToMarkdown(g).split('\n')) {
    const line = raw.trimEnd();
    if (!line.trim()) {
      y += 1.5;
      continue;
    } else if (line.startsWith('# ')) {
      y += 2;
      write(line.slice(2), 20, 'bold');
    } else if (line.startsWith('## ')) {
      y += 2;
      write(line.slice(3), 15, 'bold');
    } else if (line.startsWith('### ')) {
      y += 1;
      write(line.slice(4), 12, 'bold');
    } else if (line.startsWith('- ')) {
      write(`- ${line.slice(2).replace(/\*\*/g, '')}`, 10, 'normal', 5);
    } else if (/^_.+_$/.test(line.trim())) {
      write(line.trim().slice(1, -1), 10, 'italic');
    } else {
      write(line.replace(/\*\*/g, ''), 10, 'normal');
    }
  }

  addPageNumbers(doc, pageW, pageH, m);
  downloadBlob(doc.output('blob') as Blob, filename);
}

export async function downloadCodePdf(
  sourceFileName: string,
  code: string,
  filename: string,
): Promise<void> {
  const { jsPDF } = await import('jspdf');
  const doc = new jsPDF({ unit: 'mm', format: 'a4' });
  const pageW = 210;
  const pageH = 297;
  const m = 15;
  const maxW = pageW - m * 2;
  let y = m;

  doc.setFont('helvetica', 'bold');
  doc.setFontSize(14);
  doc.text(pdfSafe(sourceFileName), m, y);
  y += 8;
  doc.setFont('courier', 'normal');
  doc.setFontSize(8.5);
  const lh = 4;
  for (const raw of code.replace(/\t/g, '  ').split('\n')) {
    const wrapped = doc.splitTextToSize(pdfSafe(raw) || ' ', maxW) as string[];
    for (const ln of wrapped) {
      if (y + lh > pageH - m) {
        doc.addPage();
        y = m;
      }
      doc.text(ln, m, y);
      y += lh;
    }
  }

  addPageNumbers(doc, pageW, pageH, m);
  downloadBlob(doc.output('blob') as Blob, filename);
}

async function downloadImagePdf(dataUrl: string, filenameBase: string): Promise<void> {
  const { jsPDF } = await import('jspdf');
  const img = await loadImage(dataUrl);
  const landscape = img.naturalWidth >= img.naturalHeight;
  const doc = new jsPDF({
    unit: 'mm',
    format: 'a4',
    orientation: landscape ? 'landscape' : 'portrait',
  });
  const pageW = landscape ? 297 : 210;
  const pageH = landscape ? 210 : 297;
  const m = 10;

  doc.setFont('helvetica', 'normal');
  doc.setFontSize(10);
  doc.text(pdfSafe(filenameBase), m, m);
  const availW = pageW - m * 2;
  const availH = pageH - m * 2 - 8;
  const scale = Math.min(availW / img.naturalWidth, availH / img.naturalHeight);
  const w = Math.max(1, img.naturalWidth * scale);
  const h = Math.max(1, img.naturalHeight * scale);
  const x = (pageW - w) / 2;
  const top = m + 8 + (availH - h) / 2;

  const canvas = document.createElement('canvas');
  canvas.width = img.naturalWidth;
  canvas.height = img.naturalHeight;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('canvas');
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(img, 0, 0);
  doc.addImage(canvas.toDataURL('image/jpeg', 0.92), 'JPEG', x, top, w, h);
  downloadBlob(doc.output('blob') as Blob, `${filenameBase}.pdf`);
}
