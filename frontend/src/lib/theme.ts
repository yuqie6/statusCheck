export type ThemePreference = 'system' | 'light' | 'dark'
export type EffectiveTheme = 'light' | 'dark'

export const themePreferenceStorageKey = 'statuscheck_theme_preference'

export function systemPrefersDark(): boolean {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false
}

export function effectiveTheme(preference: ThemePreference): EffectiveTheme {
  if (preference === 'system') return systemPrefersDark() ? 'dark' : 'light'
  return preference
}

export function readThemePreference(): ThemePreference {
  const stored = window.localStorage.getItem(themePreferenceStorageKey)
  return stored === 'light' || stored === 'dark' || stored === 'system' ? stored : 'system'
}

export function applyThemePreference(preference: ThemePreference): void {
  const root = document.documentElement
  if (preference === 'system') {
    root.removeAttribute('data-theme')
  } else {
    root.dataset.theme = preference
  }
  root.dataset.themePreference = preference
}

export function saveThemePreference(preference: ThemePreference): void {
  window.localStorage.setItem(themePreferenceStorageKey, preference)
  applyThemePreference(preference)
}
