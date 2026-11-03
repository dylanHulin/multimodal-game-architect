/* SAM 3.1 cutout: fetch binary masks from the backend, composite locally.

Masks arrive as raw 0/1 bytes (base64) on a small raster; each is scaled up to
the full image on canvas (nearest neighbour) and unioned into an alpha layer.
No imaging dependency needed anywhere in the chain.
*/

import { apiPost } from './api';
import { loadImage } from './download';

export interface CutoutMaskData {
  width: number;
  height: number;
  data_base64: string;
}

export interface CutoutBoxData {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface CutoutResult {
  status: string;
  concept: string;
  image_width: number;
  image_height: number;
  boxes: CutoutBoxData[];
  masks: CutoutMaskData[];
  error?: string | null;
}

export function requestCutout(imageUrl: string, concept: string): Promise<CutoutResult> {
  return apiPost<CutoutResult>('/api/v1/cutout', { image_url: imageUrl, concept });
}

function b64ToBytes(b64: string): Uint8Array {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

export async function compositeCutout(
  imageUrl: string,
  masks: CutoutMaskData[],
  boxes: CutoutBoxData[] = [],
): Promise<string> {
  const img = await loadImage(imageUrl);
  const w = img.naturalWidth;
  const h = img.naturalHeight;
  if (!w || !h || masks.length === 0) throw new Error('cutout');

  const alpha = document.createElement('canvas');
  alpha.width = w;
  alpha.height = h;
  const actx = alpha.getContext('2d');
  if (!actx) throw new Error('canvas');
  // Transparent base: destination-in keys on ALPHA, not luminance, so mask
  // pixels carry binary alpha (255 = keep, 0 = cut).
  actx.globalCompositeOperation = 'lighter';
  actx.imageSmoothingEnabled = false;

  let drawn = 0;
  for (let k = 0; k < masks.length; k++) {
    const m = masks[k];
    const bytes = b64ToBytes(m.data_base64);
    if (bytes.length !== m.width * m.height || m.width <= 0 || m.height <= 0) continue;
    const mc = document.createElement('canvas');
    mc.width = m.width;
    mc.height = m.height;
    const mctx = mc.getContext('2d');
    if (!mctx) continue;
    const data = mctx.createImageData(m.width, m.height);
    for (let i = 0; i < bytes.length; i++) {
      data.data[i * 4] = 255;
      data.data[i * 4 + 1] = 255;
      data.data[i * 4 + 2] = 255;
      data.data[i * 4 + 3] = bytes[i] ? 255 : 0;
    }
    mctx.putImageData(data, 0, 0);
    // The raster spans its detection box, not the frame: paste it at the box
    // rect (full-frame fallback when the box is missing/invalid).
    const b = boxes[k];
    if (b && b.x2 > b.x1 && b.y2 > b.y1) {
      actx.drawImage(mc, b.x1, b.y1, b.x2 - b.x1, b.y2 - b.y1);
    } else {
      actx.drawImage(mc, 0, 0, w, h);
    }
    drawn++;
  }
  if (!drawn) throw new Error('cutout');

  const out = document.createElement('canvas');
  out.width = w;
  out.height = h;
  const octx = out.getContext('2d');
  if (!octx) throw new Error('canvas');
  octx.drawImage(img, 0, 0);
  octx.globalCompositeOperation = 'destination-in';
  octx.drawImage(alpha, 0, 0);
  return out.toDataURL('image/png');
}
