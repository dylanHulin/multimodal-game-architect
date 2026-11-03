/* Voice dictation: record the microphone, encode mono 16-bit PCM WAV at 16 kHz
(all client-side, no dependency), and send it to Muse Voice Transcribe. */

import { apiPost } from './api';
import { tr } from './i18n';

export interface TranscribeResult {
  status: string;
  transcript: string;
  turns: { turn_id: number; start_ms: number; end_ms: number; transcript: string }[];
  duration_ms: number;
  error?: string | null;
}

const SAMPLE_RATE = 16000;

function getAudioContext(): typeof AudioContext | null {
  if (typeof window === 'undefined') return null;
  const w = window as unknown as { AudioContext?: typeof AudioContext; webkitAudioContext?: typeof AudioContext };
  return w.AudioContext ?? w.webkitAudioContext ?? null;
}

function encodeWav(pcm: Float32Array): Blob {
  const buffer = new ArrayBuffer(44 + pcm.length * 2);
  const v = new DataView(buffer);
  const writeAscii = (offset: number, s: string) => {
    for (let i = 0; i < s.length; i++) v.setUint8(offset + i, s.charCodeAt(i));
  };
  writeAscii(0, 'RIFF');
  v.setUint32(4, 36 + pcm.length * 2, true);
  writeAscii(8, 'WAVE');
  writeAscii(12, 'fmt ');
  v.setUint32(16, 16, true);
  v.setUint16(20, 1, true);
  v.setUint16(22, 1, true);
  v.setUint32(24, SAMPLE_RATE, true);
  v.setUint32(28, SAMPLE_RATE * 2, true);
  v.setUint16(32, 2, true);
  v.setUint16(34, 16, true);
  writeAscii(36, 'data');
  v.setUint32(40, pcm.length * 2, true);
  for (let i = 0; i < pcm.length; i++) {
    const s = Math.max(-1, Math.min(1, pcm[i]));
    v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([buffer], { type: 'audio/wav' });
}

async function resampleTo16kMono(blob: Blob): Promise<Float32Array> {
  const AC = getAudioContext();
  if (!AC) throw new Error(tr('voice.noWebAudio'));
  const raw = await blob.arrayBuffer();
  const actx = new AC();
  try {
    let decoded: AudioBuffer;
    try {
      decoded = await actx.decodeAudioData(raw);
    } catch {
      throw new Error(tr('voice.unreadable'));
    }
    if (!decoded.duration || decoded.duration < 0.3) {
      throw new Error(tr('voice.tooShort'));
    }
    const offline = new OfflineAudioContext(1, Math.ceil(decoded.duration * SAMPLE_RATE), SAMPLE_RATE);
    const src = offline.createBufferSource();
    src.buffer = decoded;
    src.connect(offline.destination);
    src.start();
    const rendered = await offline.startRendering();
    return rendered.getChannelData(0);
  } finally {
    await actx.close().catch(() => undefined);
  }
}

export interface DictationSession {
  stop: () => Promise<Blob>;
  cancel: () => void;
}

export async function startDictation(maxSeconds: number, onAutoStop: () => void): Promise<DictationSession> {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error(tr('voice.noMic'));
  }
  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (err) {
    const name = err instanceof DOMException ? err.name : '';
    if (name === 'NotAllowedError' || name === 'SecurityError') {
      throw new Error(tr('voice.micDenied'));
    }
    throw new Error(tr('voice.noDevice'));
  }
  const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'];
  const mimeType = candidates.find((m) => window.MediaRecorder?.isTypeSupported(m));
  let recorder: MediaRecorder;
  try {
    recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
  } catch {
    stream.getTracks().forEach((t) => t.stop());
    throw new Error(tr('voice.recImpossible'));
  }
  const chunks: BlobPart[] = [];
  recorder.ondataavailable = (e) => {
    if (e.data.size > 0) chunks.push(e.data);
  };
  const done = new Promise<Blob>((resolve) => {
    recorder.onstop = () => resolve(new Blob(chunks, { type: recorder.mimeType || 'audio/webm' }));
  });
  recorder.start();
  const timer = window.setTimeout(() => {
    if (recorder.state !== 'inactive') {
      recorder.stop();
      onAutoStop();
    }
  }, maxSeconds * 1000);
  const finish = async (): Promise<Blob> => {
    window.clearTimeout(timer);
    if (recorder.state !== 'inactive') recorder.stop();
    const blob = await done;
    stream.getTracks().forEach((t) => t.stop());
    return blob;
  };
  return {
    stop: async () => encodeWav(await resampleTo16kMono(await finish())),
    cancel: () => {
      window.clearTimeout(timer);
      if (recorder.state !== 'inactive') recorder.stop();
      stream.getTracks().forEach((t) => t.stop());
    },
  };
}

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',', 2)[1] ?? '');
    reader.onerror = () => reject(new Error('read'));
    reader.readAsDataURL(blob);
  });
}

export async function transcribeWav(wav: Blob): Promise<TranscribeResult> {
  const audio_base64 = await blobToBase64(wav);
  if (!audio_base64) throw new Error(tr('voice.empty'));
  return apiPost<TranscribeResult>('/api/v1/transcribe', { audio_base64 });
}
