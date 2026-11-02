'use client';

import Link from 'next/link';
import GDDForm from '../../components/GDDForm';
import LanguageSwitcher from '../../components/LanguageSwitcher';
import { useT } from '../../lib/useT';

export default function GddFormPage() {
  const { t } = useT();
  return (
    <main className="min-h-screen bg-slate-950 text-slate-100 p-8">
      <div className="max-w-6xl mx-auto">
        <header className="mb-8 border-b border-slate-800 pb-6 flex justify-between items-center">
          <div>
            <h1 className="text-3xl font-extrabold text-blue-500">{t('formpage.title')}</h1>
            <p className="text-slate-400 text-sm mt-1">{t('formpage.subtitle')}</p>
          </div>
          <div className="flex items-center gap-3">
            <LanguageSwitcher />
            <Link
              href="/"
              className="bg-slate-900 text-slate-200 border border-slate-700 hover:border-blue-500 px-3 py-1 rounded-full text-xs font-semibold transition"
            >
              ← Pipeline
            </Link>
          </div>
        </header>
        <GDDForm />
      </div>
    </main>
  );
}
