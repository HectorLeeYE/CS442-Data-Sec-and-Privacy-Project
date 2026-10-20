export type Tier = 'GREEN' | 'AMBER' | 'RED'
export const TIERS: Tier[] = ['RED', 'AMBER', 'GREEN']
export const TIER_RANK: Record<Tier, number> = { GREEN: 0, AMBER: 1, RED: 2 }

export type Capability = 'overview' | 'calls' | 'ingest' | 'review' | 'export' | 'audit' | 'policy' | 'live' | 'attack' | 'results'
export type User = {
  username: string; display_name: string; tier: Tier; agent_name: string | null
  role: 'compliance' | 'agent' | 'datasci' | 'admin'; can: Capability[]   // what the role's job needs; the API enforces it
}
export type Entity = { type: string; class: string; action: string; layer: string; score: number }
export type Piece = { text: string; entity?: Entity }
export type Utterance = { speaker: 'agent' | 'client'; text: string; pieces: Piece[] }
export type CallSummary = {
  id: string; scenario: string; source: string; created_at: string; mine: boolean
  risk: 'high' | 'low'; review: 'none' | 'pending' | 'approved'
  risk_reason?: string; review_reasons?: string[] // RED only
}
export type TreeHead = { log: string; size: number; root: string; ts: number; signature: string }
/** Checkable offline: `python -m server.merkle receipt.json log-key.pem` (key from /api/log-key). */
export type Receipt = {
  entry: { seq: number; ts: string; username: string; user_tier: Tier; action: string; call_id: string; view_tier: Tier; digest: string; detail: string | null }
  index: number; inclusion: string[]; tree_head: TreeHead; signature: string
}
export type CallView = {
  call: CallSummary
  tier: Tier
  utterances: Utterance[]
  digest: string
  actions: Record<string, number>
  receipt: Receipt
}
export type AuditAction = 'view' | 'deny' | 'ingest' | 'breakglass' | 'review' | 'erase' | 'export' | 'attack'
export type AuditEntry = {
  seq: number; ts: string; username: string; user_tier: Tier; action: AuditAction
  call_id: string | null; view_tier: Tier | null; digest: string | null; detail: string | null; hash: string
}
export type Chain = { ok: boolean; broken_at: number | null; checked: number; signed_heads?: number; tree_size?: number; reason: string | null }
export type ExportResult = {
  manifest: {
    created: string; requested_by: string; policy_version: string; k: number; n_calls: number; n_gated: number
    withheld_for_review: string[]; per_call: Record<string, { k: number; gated: boolean }>; sha256: string; audit_seq: number
  }
  signature: string
  jsonl: string
}

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

/** 'A: ...' / 'C: ...' lines (or bare lines, read as the client) -> utterances. */
export function parsePasted(text: string): { speaker: 'agent' | 'client'; text: string }[] {
  return text
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)
    .map((l) => {
      const m = l.match(/^(a|agent|c|client|customer)\s*:\s*(.+)$/i)
      const who = m?.[1].toLowerCase() ?? 'c'
      return { speaker: who.startsWith('a') ? 'agent' : 'client', text: m ? m[2] : l }
    })
}

export type Anonymized = {
  detected: Utterance[]
  tiers: Record<Tier, Utterance[]>
  risk: 'high' | 'low'; risk_reason: string; review_reasons: string[]; ms: number
}

export type AttackAssets = {
  database: boolean; user_key: string | null; keys_volume: boolean; ka_volume: boolean
  app_secret: boolean; ka_secret: boolean; ka_access: boolean
}
type KeyFile = 'not stolen' | 'absent' | 'sealed' | 'opened'
export type AttackResult = {
  calls: Record<string, { risk: 'high' | 'low'; review: string; reasons: boolean } & Partial<Record<Tier, boolean>>> | null
  keys: string[]; receipt_key: KeyFile; authority_keys: KeyFile; ka_request: string
}

export type Target = {
  id: string; group: 'privacy' | 'utility'; requirement: string; target: string
  value: string | null; met: boolean | null; evidence: string; kind: 'measured' | 'test'
}
export type Dataset = { name: string; size: string; use: string; source: string }
export type Task = {
  asr_model: string; test_calls: number; n_train_calls: number
  old_wer: number; new_wer: number; raw_wer: number; oracle_wer: number
  breakdown: { category: string; words: number; old_missed: number; new_missed: number; raw_missed: number }[]
  examples: { reference: string; old: string; new: string }[]
  canary?: { raw: number; green: number; max: number }
}
export type Overview = { targets: Target[]; datasets: Dataset[]; task: Task | null }
