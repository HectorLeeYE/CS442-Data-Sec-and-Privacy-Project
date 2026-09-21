/**
 * Typed API client for the FastAPI backend.
 *
 * In development Vite proxies `/api` to http://127.0.0.1:8000, so the client uses
 * a relative base URL by default. Set VITE_API_BASE_URL to point somewhere else.
 */

import type {
  AdminUser,
  AdminUserListResponse,
  AdminUserUpdate,
  AttributeCatalogResponse,
  AuditListResponse,
  DatasetDetail,
  DatasetListResponse,
  DemoAccountsResponse,
  HealthResponse,
  MeResponse,
  PolicyCatalogEntry,
  QueryRequest,
  QueryResponse,
  TokenResponse,
} from './types'

const BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? '/api'

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

/** FastAPI returns `{detail: string}` for HTTPException and a list for 422s. */
function extractDetail(payload: unknown, fallback: string): string {
  if (payload && typeof payload === 'object' && 'detail' in payload) {
    const detail = (payload as { detail: unknown }).detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      return detail
        .map((item) =>
          item && typeof item === 'object' && 'msg' in item
            ? String((item as { msg: unknown }).msg)
            : String(item),
        )
        .join('; ')
    }
  }
  return fallback
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH'
  body?: unknown
  token?: string | null
  signal?: AbortSignal
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, token, signal } = options
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (token) headers.Authorization = `Bearer ${token}`

  let response: Response
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiError(
      0,
      'Cannot reach the API. Start the backend with: uvicorn app.main:app --port 8000',
    )
  }

  if (response.status === 204) return undefined as T

  const text = await response.text()
  const payload = text ? safeJson(text) : null
  if (!response.ok) {
    throw new ApiError(
      response.status,
      extractDetail(payload, `Request failed with ${response.status} ${response.statusText}.`),
    )
  }
  return payload as T
}

export const api = {
  health: (signal?: AbortSignal) => request<HealthResponse>('/health', { signal }),

  signIn: (email: string, password: string) =>
    request<TokenResponse>('/auth/login', { method: 'POST', body: { email, password } }),

  me: (token: string, signal?: AbortSignal) => request<MeResponse>('/auth/me', { token, signal }),

  signOut: (token: string) => request<void>('/auth/logout', { method: 'POST', token }),

  demoAccounts: (signal?: AbortSignal) =>
    request<DemoAccountsResponse>('/catalog/demo-accounts', { signal }),

  attributeCatalog: (token: string, signal?: AbortSignal) =>
    request<AttributeCatalogResponse>('/catalog/attributes', { token, signal }),

  policyCatalog: (token: string, signal?: AbortSignal) =>
    request<{ policies: PolicyCatalogEntry[] }>('/catalog/policies', { token, signal }),

  datasets: (token: string, signal?: AbortSignal) =>
    request<DatasetListResponse>('/datasets', { token, signal }),

  dataset: (token: string, datasetId: number, signal?: AbortSignal) =>
    request<DatasetDetail>(`/datasets/${datasetId}`, { token, signal }),

  query: (token: string, payload: QueryRequest, signal?: AbortSignal) =>
    request<QueryResponse>('/query', { method: 'POST', body: payload, token, signal }),

  audit: (
    token: string,
    params: { limit?: number; offset?: number; action?: string; decision?: string } = {},
    signal?: AbortSignal,
  ) => {
    const search = new URLSearchParams()
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== '') search.set(key, String(value))
    })
    const suffix = search.toString() ? `?${search.toString()}` : ''
    return request<AuditListResponse>(`/audit${suffix}`, { token, signal })
  },

  adminUsers: (token: string, signal?: AbortSignal) =>
    request<AdminUserListResponse>('/admin/users', { token, signal }),

  adminUpdateUser: (token: string, userId: number, payload: AdminUserUpdate) =>
    request<AdminUser>(`/admin/users/${userId}`, { method: 'PATCH', body: payload, token }),
}
