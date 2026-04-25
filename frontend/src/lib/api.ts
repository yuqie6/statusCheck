import type { DashboardResponse } from '../types'

const explicitApiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? '').trim()

function buildApiUrl(path: string, query?: Record<string, string>): string {
  if (!explicitApiBaseUrl) {
    const url = new URL(path, window.location.origin)
    if (query) {
      for (const [key, value] of Object.entries(query)) {
        url.searchParams.set(key, value)
      }
    }
    return url.toString()
  }

  const normalizedBase = explicitApiBaseUrl.endsWith('/')
    ? explicitApiBaseUrl
    : `${explicitApiBaseUrl}/`
  const normalizedPath = path.startsWith('/') ? path.slice(1) : path
  const url = new URL(normalizedPath, normalizedBase)
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      url.searchParams.set(key, value)
    }
  }
  return url.toString()
}

export async function fetchDashboard(): Promise<DashboardResponse> {
  const response = await fetch(buildApiUrl('/api/dashboard'), {
    headers: {
      Accept: 'application/json',
    },
  })

  if (!response.ok) {
    throw new Error(`请求失败: ${response.status}`)
  }

  return response.json()
}
