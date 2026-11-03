/* Bound translator for components: re-renders on language change. */

import { useSyncExternalStore } from 'react';
import {
  getLangSnapshot,
  subscribeLang,
  translate,
  type I18nKey,
  type I18nVars,
  type Lang,
} from './i18n';

export function useT(): {
  lang: Lang;
  t: (key: I18nKey, vars?: I18nVars) => string;
} {
  const lang = useSyncExternalStore(subscribeLang, getLangSnapshot, () => 'en' as Lang);
  return { lang, t: (key, vars) => translate(lang, key, vars) };
}
