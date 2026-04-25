export function formatNumber(value: number): string {
  return new Intl.NumberFormat('zh-CN').format(value)
}

export function formatCompact(value: number): string {
  return new Intl.NumberFormat('zh-CN', {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(value)
}

export function formatUsd(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: value < 1 ? 4 : 2,
    maximumFractionDigits: value < 1 ? 4 : 2,
  }).format(value)
}

export function formatPercent(value: number, digits = 1): string {
  return `${(value * 100).toFixed(digits)}%`
}

export function formatLatency(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `${Math.round(value)} ms`
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date)
}

export function statusTone(status: string): 'good' | 'warn' | 'bad' | 'muted' {
  const lowered = status.toLowerCase()
  if (['healthy', 'ok', 'healthy_catalog'].includes(lowered)) return 'good'
  if (['warning', 'degraded', 'critical', 'saturated'].includes(lowered)) return 'warn'
  if (['down', 'error'].includes(lowered)) return 'bad'
  return 'muted'
}
