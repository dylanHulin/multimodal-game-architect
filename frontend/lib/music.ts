/* Concept music (Meta MusicGen hosted on Replicate; BYOK via X-Replicate-Key). */

import { replicateHeaders } from './apiKey';
import { apiPost } from './api';

export interface MusicResult {
  status: string;
  audio_base64: string;
  sample_rate: number;
  duration_sec: number;
  prompt_used: string;
  error?: string | null;
}

export interface Mp3Result {
  status: string;
  audio_base64: string;
  error?: string | null;
}

export const MUSIC_STYLES = [
  'epic orchestral loop',
  'heroic adventure loop',
  'boss battle loop',
  '8-bit chiptune loop',
  'retro arcade loop',
  'synthwave loop',
  'cyberpunk electronic loop',
  'dark ambient loop',
  'horror tension drone',
  'mysterious dungeon loop',
  'cozy village loop',
  'medieval tavern loop',
  'tribal percussion loop',
  'dreamy piano loop',
  'acoustic folk loop',
  'epic rock loop',
];

export const MUSIC_DURATIONS = [5, 10, 15];

export function requestMusic(
  prompt: string,
  style: string,
  durationSec: number,
): Promise<MusicResult> {
  return apiPost<MusicResult>(
    '/api/v1/generate-music',
    { prompt, style, duration_sec: durationSec },
    replicateHeaders(),
  );
}

export function requestMp3(audioBase64: string): Promise<Mp3Result> {
  return apiPost<Mp3Result>('/api/v1/music-to-mp3', { audio_base64: audioBase64 });
}

export function wavDataUrl(b64: string): string {
  return `data:audio/wav;base64,${b64}`;
}

export function mp3DataUrl(b64: string): string {
  return `data:audio/mpeg;base64,${b64}`;
}

export function downloadDataUrl(dataUrl: string, filename: string): void {
  const a = document.createElement('a');
  a.href = dataUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
}
