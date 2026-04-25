import { Monitor, Moon, Sun } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import {
  applyThemePreference,
  effectiveTheme,
  readThemePreference,
  saveThemePreference,
  systemPrefersDark,
  type ThemePreference,
} from '../lib/theme'

function nextPreference(preference: ThemePreference, currentEffective: 'light' | 'dark'): ThemePreference {
  if (preference === 'system') return currentEffective === 'dark' ? 'light' : 'dark'
  if (preference === 'light') return 'dark'
  return 'system'
}

export function ThemeToggle() {
  const [preference, setPreference] = useState<ThemePreference>(() => readThemePreference())
  const [systemDark, setSystemDark] = useState(() => systemPrefersDark())

  useEffect(() => {
    applyThemePreference(preference)
  }, [preference, systemDark])

  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => setSystemDark(media.matches)
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [])

  const currentEffective = effectiveTheme(preference)
  const Icon = preference === 'system' ? Monitor : currentEffective === 'dark' ? Moon : Sun
  const label = useMemo(() => {
    if (preference === 'system') return `跟随系统 · ${systemDark ? '夜间' : '日间'}`
    return preference === 'dark' ? '夜间模式' : '日间模式'
  }, [preference, systemDark])

  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={() => {
        const next = nextPreference(preference, currentEffective)
        saveThemePreference(next)
        setPreference(next)
      }}
      title="切换主题：跟随系统 / 日间 / 夜间"
      aria-label={`当前主题：${label}`}
    >
      <Icon size={16} />
      <span>{label}</span>
    </button>
  )
}
