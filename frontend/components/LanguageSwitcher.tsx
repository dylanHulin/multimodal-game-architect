'use client';

import { useEffect } from 'react';
import { LANGS, setLang, type Lang } from '../lib/i18n';
import { useT } from '../lib/useT';

export default function LanguageSwitcher() {
  const { lang, t } = useT();

  // Persisted language applies after hydration: sync <html lang> once mounted.
  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  return (
    <select
      aria-label={t('lang.label')}
      title={t('lang.label')}
      className="bg-slate-900 text-slate-200 border border-slate-700 hover:border-blue-500 rounded-full pl-3 pr-2 py-1 text-xs font-semibold transition"
      value={lang}
      onChange={(e) => setLang(e.target.value as Lang)}
    >
      {LANGS.map((l) => (
        <option key={l.code} value={l.code}>
          {l.label}
        </option>
      ))}
    </select>
  );
}
