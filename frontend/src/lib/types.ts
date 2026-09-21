/**
 * Types mirroring the FastAPI schemas in `backend/app/schemas.py`.
 *
 * Keeping them hand-written (rather than generated) keeps the demo readable:
 * the CP-ABE concepts - attribute set, ciphertext policy, decision, policy trace -
 * are visible in the type names.
 */

export type UserStatus = 'active' | 'pending' | 'disabled'
export type DecisionName = 'granted' | 'denied'
export type FieldClassification =
  | 'direct_identifier'
  | 'quasi_identifier'
  | 'sensitive'
  | 'non_sensitive'
export type AnonymizationRule =
  | 'none'
  | 'suppress'
  | 'mask'
  | 'hash'
  | 'generalize'
  | 'perturb'
export type QueryOperator = 'eq' | 'in' | 'gte' | 'lte' | 'contains'
export type PolicyNodeType = 'and' | 'or' | 'not' | 'attribute'

export interface UserProfile {
  id: number
  email: string
  full_name: string
  status: UserStatus
  roles: string[]
  /** The attribute set: what a CP-ABE key generation step would consume. */
  attributes: string[]
  created_at: string
  last_login_at: string | null
}

export interface TokenResponse {
  access_token: string
  token_type: 'bearer'
  expires_in: number
  crypto_backend: string
  user: UserProfile
}

export interface MeResponse {
  user: UserProfile
  claims: Record<string, unknown>
  crypto_backend: string
}

export interface AttributeDefinition {
  attribute: string
  category: string
  value: string
  category_label: string
  label: string
  description: string
  sensitive: boolean
}

export interface AttributeCategoryGroup {
  category: string
  category_label: string
  attributes: AttributeDefinition[]
}

export interface AttributeCatalogResponse {
  categories: AttributeCategoryGroup[]
  total: number
}

export interface PolicyCatalogEntry {
  policy: string
  canonical_policy: string
  description: string
  policy_hash: string
  referenced_attributes: string[]
  record_count: number
}

export interface PolicySummary {
  policy: string
  canonical_policy: string
  description: string
  record_count: number
}

export interface DemoAccount {
  email: string
  password: string
  label: string
  status: UserStatus
  note: string
  roles: string[]
  attributes: string[]
}

export interface DemoAccountsResponse {
  accounts: DemoAccount[]
  notice: string
}

export interface DatasetField {
  name: string
  label: string
  data_type: string
  classification: FieldClassification
  anonymization_rule: AnonymizationRule
  description: string
  is_queryable: boolean
  is_selectable: boolean
}

export interface DatasetSummary {
  id: number
  slug: string
  name: string
  description: string
  domain: string
  record_count: number
  field_count: number
  policies: PolicySummary[]
  /** Decryptable with the caller's attribute set. */
  granted_count: number
  denied_count: number
  unlocking_attributes: string[]
}

export interface DatasetDetail extends DatasetSummary {
  fields: DatasetField[]
}

export interface DatasetListResponse {
  datasets: DatasetSummary[]
  crypto_backend: string
}

export interface QueryFilter {
  field: string
  op: QueryOperator
  value: unknown
}

export interface QueryRequest {
  dataset_id: number
  filters?: QueryFilter[]
  fields?: string[]
  limit?: number
  offset?: number
}

export interface LeafTrace {
  attribute: string
  satisfied: boolean
  negated: boolean
}

export interface PolicyTreeNode {
  type: PolicyNodeType
  attribute: string | null
  satisfied: boolean
  negated: boolean
  children: PolicyTreeNode[]
}

export interface Decision {
  granted: boolean
  reason: string
  policy: string
  leaf_trace: LeafTrace[]
  matched_attributes: string[]
  missing_attributes: string[]
}

export interface CiphertextInfo {
  backend: string
  algorithm: string
  encrypted: boolean
  policy_hash: string
  preview: string
}

export interface QueryRow {
  record_key: string
  values: Record<string, unknown>
  policy: string
  decision: Decision
  policy_tree: PolicyTreeNode
  ciphertext: CiphertextInfo
}

export interface DeniedPolicyGroup {
  policy: string
  count: number
  reason: string
  missing_attributes: string[]
}

export interface DeniedSummary {
  count: number
  by_policy: DeniedPolicyGroup[]
  unlocking_attributes: string[]
}

export interface QueryTotals {
  scanned: number
  granted: number
  denied: number
  matched: number
}

export interface QueryResponse {
  dataset_id: number
  dataset_slug: string
  dataset_name: string
  crypto_backend: string
  encrypted: boolean
  rows: QueryRow[]
  denied: DeniedSummary
  totals: QueryTotals
  limit: number
  offset: number
  took_ms: number
  audit_id: number
  notice: string
}

export interface AuditEntry {
  id: number
  created_at: string
  action: string
  decision: DecisionName
  actor_email: string
  actor_attributes: string[]
  dataset_slug: string | null
  record_key: string | null
  policy: string | null
  reason: string
  detail: Record<string, unknown>
}

export interface AuditListResponse {
  entries: AuditEntry[]
  total: number
  limit: number
  offset: number
}

export interface DatasetAccessPreview {
  dataset_slug: string
  dataset_name: string
  granted_count: number
  denied_count: number
}

export interface AdminUser {
  id: number
  email: string
  full_name: string
  status: UserStatus
  roles: string[]
  attributes: string[]
  created_at: string
  last_login_at: string | null
  access_preview: DatasetAccessPreview[]
}

export interface AdminUserListResponse {
  users: AdminUser[]
  assignable_attributes: string[]
  assignable_roles: string[]
}

export interface AdminUserUpdate {
  status?: UserStatus
  roles?: string[]
  attributes?: string[]
  note?: string
}

export interface HealthResponse {
  status: 'ok'
  version: string
  environment: string
  crypto_backend: string
  encrypted: boolean
  database: string
  using_dev_jwt_secret: boolean
}
