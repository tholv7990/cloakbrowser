/**
 * Minimal i18n: a flat key→string dictionary per language + a `useT` hook driven
 * by the persisted language preference. Placeholders use {name} interpolation.
 * English and Vietnamese are the version-1 languages.
 */
import { useCallback } from 'react';
import { useUiStore, type Language } from '@/app/uiStore';
import { en } from './en';
import { vi } from './vi';

export type TranslationKey = keyof typeof en;

const DICTS: Record<Language, Record<TranslationKey, string>> = { en, vi };

function interpolate(template: string, vars?: Record<string, string | number>): string {
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (_, key: string) =>
    key in vars ? String(vars[key]) : `{${key}}`,
  );
}

export function useT(): (key: TranslationKey, vars?: Record<string, string | number>) => string {
  const language = useUiStore((state) => state.language);
  return useCallback(
    (key, vars) => interpolate(DICTS[language][key] ?? en[key] ?? key, vars),
    [language],
  );
}

export const LANGUAGES: { value: Language; label: string }[] = [
  { value: 'en', label: 'EN' },
  { value: 'vi', label: 'VI' },
];
