import type { AdminConfig, AdminConfigResponse, DashboardResponse } from '../types'

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


async function parseApiError(response: Response): Promise<string> {
  try {
    const payload = await response.json()
    if (typeof payload?.detail === 'string') return payload.detail
    if (Array.isArray(payload?.detail)) return payload.detail.map((item: { msg?: string }) => item.msg ?? JSON.stringify(item)).join('；')
    if (typeof payload?.message === 'string') return payload.message
  } catch {
    // ignore non-json error body
  }
  return `请求失败: ${response.status}`
}

function adminHeaders(token: string): HeadersInit {
  return {
    Accept: 'application/json',
    Authorization: `Bearer ${token}`,
  }
}

export async function fetchAdminConfig(token: string): Promise<AdminConfigResponse> {
  const response = await fetch(buildApiUrl('/api/admin/config'), {
    headers: adminHeaders(token),
  })

  if (!response.ok) {
    throw new Error(await parseApiError(response))
  }

  return response.json()
}

export async function updateAdminConfig(token: string, config: AdminConfig): Promise<AdminConfigResponse> {
  const response = await fetch(buildApiUrl('/api/admin/config'), {
    method: 'PUT',
    headers: {
      ...adminHeaders(token),
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(config),
  })

  if (!response.ok) {
    throw new Error(await parseApiError(response))
  }

  return response.json()
}
