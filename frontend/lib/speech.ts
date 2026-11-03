/* Browser speech synthesis for the "listen to the pitch" button.

Meta offers no text-to-speech API (Muse Voice is transcription-only), so
narration runs locally via the Web Speech API: free, instant, keyless.
*/

import { LOCALES, getLangSnapshot } from './i18n';

export function speechAvailable(): boolean {
  return typeof window !== 'undefined' && 'speechSynthesis' in window;
}

export function speakText(text: string, lang?: string, onEnd?: () => void): boolean {
  if (!speechAvailable()) return false;
  const uiLang = getLangSnapshot();
  const locale = lang ?? LOCALES[uiLang];
  try {
    const synth = window.speechSynthesis;
    synth.cancel();
    const utterance = new SpeechSynthesisUtterance(text.slice(0, 1200));
    utterance.lang = locale;
    utterance.onend = () => onEnd?.();
    utterance.onerror = () => onEnd?.();
    const voices = synth.getVoices();
    const match =
      voices.find((v) => v.lang.toLowerCase().startsWith(uiLang)) ??
      voices.find((v) => v.lang.toLowerCase().startsWith('en'));
    if (match) utterance.voice = match;
    synth.speak(utterance);
    return true;
  } catch {
    return false;
  }
}

export function stopSpeaking(): void {
  if (speechAvailable()) {
    try {
      window.speechSynthesis.cancel();
    } catch {
      /* noop */
    }
  }
}
