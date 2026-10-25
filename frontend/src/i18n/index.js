// UI strings in Finnish, English and Bengali (the languages a member can pick in F10).
// Story texts are translated by the backend; these files are for the app's own labels.
import en from './en.json'
import fi from './fi.json'
import bn from './bn.json'
import { useMeContext } from '../app/providers/me'

export const LANGUAGES = { en, fi, bn }

/** Look up `key` in `lang`, falling back to English, then to the key itself. */
export function t(lang, key, vars = {}) {
  const text = LANGUAGES[lang]?.[key] ?? en[key] ?? key
  return text.replace(/\{(\w+)\}/g, (_, k) => vars[k] ?? `{${k}}`)
}

/** `const t = useT(); t('nav.home')` in the signed-in member's language. */
export function useT() {
  const { me } = useMeContext()
  const lang = me?.language ?? 'en'
  return (key, vars) => t(lang, key, vars)
}
