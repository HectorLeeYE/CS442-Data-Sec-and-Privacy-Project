export type Tier = 'GREEN' | 'AMBER' | 'RED'
export const TIERS: Tier[] = ['RED', 'AMBER', 'GREEN']
export const TIER_RANK: Record<Tier, number> = { GREEN: 0, AMBER: 1, RED: 2 }

export type User = { username: string; display_name: string; tier: Tier; agent_name: string | null }
export type Entity = { type: string; class: string; action: string; layer: string; score: number }
export type Piece = { text: string; entity?: Entity }
export type Utterance = { speaker: 'agent' | 'client'; text: string; pieces: Piece[] }
export type CallSummary = { id: string; scenario: string; source: string; created_at: string; mine: boolean }
export type CallView = {
  call: Omit<CallSummary, 'mine'>
  tier: Tier
  utterances: Utterance[]
  digest: string
  actions: Record<string, number>
}
export type AuditEntry = {
  seq: number; ts: string; username: string; user_tier: Tier; action: 'view' | 'deny' | 'ingest'
  call_id: string | null; view_tier: Tier | null; digest: string | null; prev: string; hash: string
}
export type Chain = { ok: boolean; broken_at: number | null; checked: number }

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

const TOKEN_KEY = 'quietline.token'

export const session = {
  get: () => sessionStorage.getItem(TOKEN_KEY),
  set: (t: string) => sessionStorage.setItem(TOKEN_KEY, t),
  clear: () => sessionStorage.removeItem(TOKEN_KEY),
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = session.get()
  const res = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    const detail = typeof body.detail === 'string' ? body.detail : res.statusText
    if (res.status === 401) session.clear()
    throw new ApiError(res.status, detail)
  }
  return res.json()
}

export const CLASS_CODE: Record<string, string> = {
  DIRECT_ID: 'DIR',
  FINANCIAL_ID: 'FIN',
  AUTH_SECRET: 'AUTH',
  QUASI_ID: 'QID',
  SENSITIVE_ATTR: 'SEN',
}

export const SCENARIO_LABEL: Record<string, string> = {
  overseas_transfer: 'Overseas transfer',
  card_dispute: 'Card dispute',
  loan_enquiry: 'Loan enquiry',
  fraud_report: 'Fraud report',
  live: 'Pasted transcript',
}
