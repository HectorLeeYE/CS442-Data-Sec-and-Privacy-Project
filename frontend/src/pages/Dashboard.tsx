import { KeyRound, ScrollText, Search, Users } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import AccessMetrics from '../components/AccessMetrics.tsx'
import AppShell, { type DashboardView } from '../components/AppShell.tsx'
import AttributeChips from '../components/AttributeChips.tsx'
import AuditTable, { type AuditFilters } from '../components/AuditTable.tsx'
import DatasetPicker from '../components/DatasetPicker.tsx'
import DeniedSummary from '../components/DeniedSummary.tsx'
import EmptyState from '../components/EmptyState.tsx'
import FieldInventory from '../components/FieldInventory.tsx'
import QueryBuilder from '../components/QueryBuilder.tsx'
import RecordTable from '../components/RecordTable.tsx'
import UserAttributesManager from '../components/UserAttributesManager.tsx'
import WhyDeniedDialog from '../components/WhyDeniedDialog.tsx'
import { ApiError, api } from '../lib/api.ts'
import { useAuth } from '../lib/auth.ts'
import { formatTimestamp, shortHash } from '../lib/format.ts'
import { useAsync } from '../lib/useAsync.ts'
import type {
  AdminUserUpdate,
  DeniedPolicyGroup,
  QueryFilter,
  QueryResponse,
} from '../lib/types.ts'

const PAGE_SIZE = 25
const API_DOCS_URL: string = import.meta.env.VITE_API_DOCS_URL ?? 'http://127.0.0.1:8000/docs'

/**
 * The dashboard. Four sections share one shell:
 *
 * - **Query console** - run a query; only what your attributes decrypt comes back.
 * - **My key material** - the attribute set, its session claims, and what each
 *   attribute unlocks.
 * - **Audit trail** (admin) - every decision, with the attribute set behind it.
 * - **Accounts** (admin) - re-issue attribute sets and watch access change.
 */
export default function Dashboard() {
  const { token, user, claims, cryptoBackend, hasRole, refresh } = useAuth()
  const isAdmin = hasRole('admin')

  const [view, setView] = useState<DashboardView>('query')
  const [chosenDatasetId, setChosenDatasetId] = useState<number | null>(null)
  const [filters, setFilters] = useState<QueryFilter[]>([])
  const [selectedFields, setSelectedFields] = useState<string[]>([])
  const [result, setResult] = useState<QueryResponse | null>(null)
  const [running, setRunning] = useState(false)
  const [queryError, setQueryError] = useState<string | null>(null)
  const [explainedGroup, setExplainedGroup] = useState<DeniedPolicyGroup | null>(null)
  const [auditFilters, setAuditFilters] = useState<AuditFilters>({ action: '', decision: '' })
  const [updatingUserId, setUpdatingUserId] = useState<number | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [pageSize, setPageSize] = useState<number | null>(null)

  const datasets = useAsync((signal) => api.datasets(token ?? '', signal), [token], Boolean(token))

  // Derived during render rather than in an effect: until the user picks a dataset,
  // the first one in the list is used, and no extra render pass is needed.
  const selectedDatasetId = chosenDatasetId ?? datasets.data?.datasets[0]?.id ?? null

  const detail = useAsync(
    (signal) => api.dataset(token ?? '', selectedDatasetId ?? 0, signal),
    [token, selectedDatasetId],
    Boolean(token) && selectedDatasetId !== null,
  )
  const attributes = useAsync(
    (signal) => api.attributeCatalog(token ?? '', signal),
    [token],
    Boolean(token),
  )
  const policies = useAsync(
    (signal) => api.policyCatalog(token ?? '', signal),
    [token],
    Boolean(token),
  )
  const audit = useAsync(
    (signal) =>
      api.audit(
        token ?? '',
        { limit: 50, action: auditFilters.action, decision: auditFilters.decision },
        signal,
      ),
    [token, auditFilters.action, auditFilters.decision],
    Boolean(token) && isAdmin && view === 'audit',
  )
  const adminUsers = useAsync(
    (signal) => api.adminUsers(token ?? '', signal),
    [token],
    Boolean(token) && isAdmin && view === 'users',
  )

  useEffect(() => {
    if (!notice) return
    const timer = window.setTimeout(() => setNotice(null), 6000)
    return () => window.clearTimeout(timer)
  }, [notice])

  const runQuery = useCallback(async () => {
    if (!token || selectedDatasetId === null) return
    setRunning(true)
    setQueryError(null)
    try {
      const usableFilters = filters.filter((filter) => {
        const value = filter.value
        return Array.isArray(value) ? value.length > 0 : String(value ?? '').trim() !== ''
      })
      const response = await api.query(token, {
        dataset_id: selectedDatasetId,
        filters: usableFilters,
        fields: selectedFields,
        limit: pageSize ?? PAGE_SIZE,
      })
      setResult(response)
    } catch (cause) {
      setResult(null)
      setQueryError(
        cause instanceof ApiError ? cause.message : 'The query could not be completed.',
      )
    } finally {
      setRunning(false)
    }
  }, [token, selectedDatasetId, filters, selectedFields, pageSize])

  const updateUser = useCallback(
    async (userId: number, payload: AdminUserUpdate) => {
      if (!token) return
      setUpdatingUserId(userId)
      try {
        const updated = await api.adminUpdateUser(token, userId, payload)
        setNotice(
          `${updated.email} now holds ${updated.attributes.length} attributes and ${
            updated.roles.join(', ') || 'no roles'
          }.`,
        )
        adminUsers.reload()
        datasets.reload()
        setResult(null)
        if (user && updated.id === user.id) void refresh()
      } catch (cause) {
        setNotice(
          cause instanceof ApiError ? `Update refused: ${cause.message}` : 'Update failed.',
        )
      } finally {
        setUpdatingUserId(null)
      }
    },
    [token, adminUsers, datasets, refresh, user],
  )

  const changeDataset = (datasetId: number) => {
    setChosenDatasetId(datasetId)
    setFilters([])
    setSelectedFields([])
    setResult(null)
    setQueryError(null)
  }

  const columns = result
    ? Object.keys(result.rows[0]?.values ?? {})
    : (detail.data?.fields.filter((field) => field.is_selectable).map((field) => field.name) ?? [])

  return (
    <AppShell activeView={view} onViewChange={setView}>
      {notice ? (
        <div className="toast toast-end z-40">
          <div className="alert alert-info">
            <span className="text-xs">{notice}</span>
            <button type="button" className="btn btn-ghost btn-xs" onClick={() => setNotice(null)}>
              Dismiss
            </button>
          </div>
        </div>
      ) : null}

      {view === 'query' ? (
        <>
          <header className="flex flex-wrap items-end justify-between gap-3">
            <div className="flex items-center gap-2">
              <Search size={18} aria-hidden="true" className="text-secondary" />
              <h1 className="text-lg font-semibold">Query console</h1>
            </div>
            <span className="badge badge-sm badge-outline font-mono">{cryptoBackend}</span>
          </header>

          <div className="card border border-base-300 bg-base-100">
            <div className="card-body min-w-0 gap-4 p-4">
              <DatasetPicker
                datasets={datasets.data?.datasets ?? []}
                value={selectedDatasetId}
                onChange={changeDataset}
                disabled={datasets.loading}
              />
              {datasets.error ? (
                <div className="alert alert-error" role="alert">
                  <span className="text-xs">{datasets.error}</span>
                </div>
              ) : null}
            </div>
          </div>

          {detail.data ? (
            <div className="card border border-base-300 bg-base-100">
              <div className="card-body min-w-0 gap-4 p-4">
                <QueryBuilder
                  fields={detail.data.fields}
                  filters={filters}
                  onFiltersChange={setFilters}
                  selectedFields={selectedFields}
                  onSelectedFieldsChange={setSelectedFields}
                  onRun={() => void runQuery()}
                  onReset={() => {
                    setFilters([])
                    setSelectedFields([])
                    setResult(null)
                    setQueryError(null)
                  }}
                  running={running}
                  disabled={selectedDatasetId === null}
                  pageSize={pageSize}
                  onPageSizeChange={setPageSize}
                />
              </div>
            </div>
          ) : null}

          {queryError ? (
            <div className="alert alert-error" role="alert">
              <span className="text-xs">{queryError}</span>
            </div>
          ) : null}

          {result ? (
            <AccessMetrics
              totals={result.totals}
              cryptoBackend={result.crypto_backend}
              encrypted={result.encrypted}
              tookMs={result.took_ms}
              notice={result.notice}
            />
          ) : null}

          {result ? (
            <section className="flex min-w-0 flex-col gap-3" aria-labelledby="results-heading">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 id="results-heading" className="text-sm font-semibold">
                  Decrypted records ({result.rows.length} shown of {result.totals.matched})
                </h2>
                <span className="font-mono text-[0.6875rem] text-base-content/60">
                  audit entry #{result.audit_id}
                </span>
              </div>
              {result.rows.length === 0 ? (
                <EmptyState
                  title="Nothing matched these filters"
                  description={`${result.totals.granted} records decrypted, but none matched your filters. Clear the filters to list them.`}
                  icon={<Search size={28} />}
                  action={
                    <button
                      type="button"
                      className="btn btn-outline btn-sm"
                      onClick={() => {
                        setFilters([])
                        void runQuery()
                      }}
                    >
                      Clear filters and rerun
                    </button>
                  }
                />
              ) : (
                <RecordTable rows={result.rows} columns={columns} />
              )}
            </section>
          ) : null}

          {result ? (
            <DeniedSummary
              denied={result.denied}
              onExplain={(policy) =>
                setExplainedGroup(
                  result.denied.by_policy.find((group) => group.policy === policy) ?? null,
                )
              }
            />
          ) : null}

          {!result && !running ? (
            <EmptyState
              title="Run a query to see what your attributes can read"
              description="Every record's ciphertext policy is evaluated against your attribute set. Records your set does not satisfy are counted and explained, never returned."
              icon={<Search size={28} />}
              action={
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  onClick={() => void runQuery()}
                  disabled={selectedDatasetId === null}
                >
                  <Search size={14} aria-hidden="true" />
                  Run query
                </button>
              }
            />
          ) : null}

          {detail.data ? (
            <div className="card border border-base-300 bg-base-100">
              <div className="card-body min-w-0 gap-4 p-4">
                <FieldInventory fields={detail.data.fields} />
                <div className="divider text-xs">policies attached to this dataset</div>
                <ul className="flex flex-col gap-2">
                  {detail.data.policies.map((policy) => (
                    <li
                      key={policy.policy}
                      className="flex flex-col gap-1 rounded-field border border-base-300 bg-base-200 p-2"
                    >
                      <code className="overflow-x-auto font-mono text-xs">{policy.policy}</code>
                      <span className="text-xs text-base-content/70">
                        {policy.description} · {policy.record_count} record
                        {policy.record_count === 1 ? '' : 's'}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          ) : null}
        </>
      ) : null}

      {view === 'key' ? (
        <>
          <header className="flex flex-wrap items-end justify-between gap-3">
            <div className="flex items-center gap-2">
              <KeyRound size={18} aria-hidden="true" className="text-secondary" />
              <h1 className="text-lg font-semibold">My key material</h1>
            </div>
            <span className="flex flex-wrap items-center gap-2">
              <a
                className="link link-hover font-mono text-xs"
                href={API_DOCS_URL}
                target="_blank"
                rel="noreferrer"
              >
                Open the interactive API docs
              </a>
              <span className="badge badge-sm badge-outline font-mono">{cryptoBackend}</span>
            </span>
          </header>

          <div className="grid min-w-0 gap-3 lg:grid-cols-2">
            <div className="card border border-base-300 bg-base-100">
              <div className="card-body min-w-0 gap-3 p-4">
                <h2 className="card-title text-base">Effective attribute set</h2>
                <p className="text-xs text-base-content/60">
                  Re-read from the server on every request. In a CP-ABE deployment this is the
                  set the attribute authority issues a key for.
                </p>
                <AttributeChips attributes={user?.attributes ?? []} />
                <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
                  <dt className="font-mono text-[0.6875rem] uppercase tracking-wide text-base-content/60">
                    Roles
                  </dt>
                  <dd className="font-mono">{user?.roles.join(', ') || '—'}</dd>
                  <dt className="font-mono text-[0.6875rem] uppercase tracking-wide text-base-content/60">
                    Account status
                  </dt>
                  <dd className="font-mono">{user?.status}</dd>
                  <dt className="font-mono text-[0.6875rem] uppercase tracking-wide text-base-content/60">
                    Last sign-in
                  </dt>
                  <dd className="font-mono">{formatTimestamp(user?.last_login_at ?? null)}</dd>
                  <dt className="font-mono text-[0.6875rem] uppercase tracking-wide text-base-content/60">
                    Ciphertext backend
                  </dt>
                  <dd className="font-mono">{cryptoBackend}</dd>
                </dl>
              </div>
            </div>

            <div className="card border border-base-300 bg-base-100">
              <div className="card-body min-w-0 gap-3 p-4">
                <h2 className="card-title text-base">Session claims</h2>
                <p className="text-xs text-base-content/60">
                  What the server read from your token. The claims are the set minted at
                  sign-in; the effective set on the left is what policies are tested against
                  right now. An administrator can change one without the other.
                </p>
                <pre className="max-w-full overflow-x-auto rounded-field border border-base-300 bg-base-200 p-2 font-mono text-[0.6875rem]">
                  {JSON.stringify(claims, null, 2)}
                </pre>
              </div>
            </div>
          </div>

          <section className="flex min-w-0 flex-col gap-3" aria-labelledby="access-preview-heading">
            <h2 id="access-preview-heading" className="text-sm font-semibold">
              What your attributes decrypt
            </h2>
            <div className="max-w-full min-w-0 overflow-x-auto rounded-box border border-base-300 bg-base-100">
              <table className="table table-sm">
                <caption className="sr-only">
                  Decryptable and refused record counts per dataset for your attribute set.
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Dataset</th>
                    <th scope="col">Decryptable</th>
                    <th scope="col">Refused</th>
                    <th scope="col">Attributes that would unlock more</th>
                  </tr>
                </thead>
                <tbody>
                  {(datasets.data?.datasets ?? []).map((dataset) => (
                    <tr key={dataset.slug} className="hover:bg-base-300">
                      <td className="font-mono text-xs">{dataset.slug}</td>
                      <td className="tabular-nums">{dataset.granted_count}</td>
                      <td className="tabular-nums">{dataset.denied_count}</td>
                      <td>
                        {dataset.unlocking_attributes.length === 0 ? (
                          <span className="text-xs text-base-content/60">nothing missing</span>
                        ) : (
                          <span className="flex flex-wrap gap-1">
                            {dataset.unlocking_attributes.map((attribute) => (
                              <span
                                key={attribute}
                                className="badge badge-sm badge-outline font-mono"
                              >
                                {attribute}
                              </span>
                            ))}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <div className="grid min-w-0 gap-3 xl:grid-cols-2">
            <div className="card border border-base-300 bg-base-100">
              <div className="card-body min-w-0 gap-3 p-4">
                <h2 className="card-title text-base">
                  Attribute universe ({attributes.data?.total ?? 0})
                </h2>
                <ul className="flex flex-col gap-3">
                  {(attributes.data?.categories ?? []).map((group) => (
                    <li key={group.category} className="flex flex-col gap-1">
                      <span className="font-mono text-[0.6875rem] uppercase tracking-wide text-base-content/60">
                        {group.category_label}
                      </span>
                      <ul className="flex flex-wrap gap-1.5">
                        {group.attributes.map((attribute) => (
                          <li key={attribute.attribute}>
                            <span
                              className={
                                user?.attributes.includes(attribute.attribute)
                                  ? 'badge badge-sm badge-primary font-mono'
                                  : 'badge badge-sm badge-outline font-mono'
                              }
                              title={attribute.description}
                            >
                              {attribute.attribute}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </li>
                  ))}
                </ul>
                <p className="text-xs text-base-content/60">
                  Filled badges are held by your account; outlined ones belong to other
                  accounts or to no account yet.
                </p>
              </div>
            </div>

            <div className="card border border-base-300 bg-base-100">
              <div className="card-body min-w-0 gap-3 p-4">
                <h2 className="card-title text-base">
                  Policy catalog ({policies.data?.policies.length ?? 0})
                </h2>
                <ul className="flex flex-col gap-2">
                  {(policies.data?.policies ?? []).map((policy) => (
                    <li
                      key={policy.policy}
                      className="flex flex-col gap-1 rounded-field border border-base-300 bg-base-200 p-2"
                    >
                      <code className="overflow-x-auto font-mono text-xs">{policy.policy}</code>
                      <span className="text-xs text-base-content/70">{policy.description}</span>
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="badge badge-sm badge-outline">
                          {policy.record_count} records
                        </span>
                        <span className="font-mono text-[0.6875rem] text-base-content/60">
                          hash {shortHash(policy.policy_hash, 16)}
                        </span>
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        </>
      ) : null}
      {view === 'audit' ? (
        <>
          <header className="flex flex-wrap items-end justify-between gap-3">
            <div className="flex items-center gap-2">
              <ScrollText size={18} aria-hidden="true" className="text-secondary" />
              <h1 className="text-lg font-semibold">Audit trail</h1>
            </div>
            <span className="badge badge-sm badge-outline font-mono">role: admin</span>
          </header>

          {audit.error ? (
            <div className="alert alert-error" role="alert">
              <span className="text-xs">{audit.error}</span>
            </div>
          ) : null}

          <AuditTable
            entries={audit.data?.entries ?? []}
            total={audit.data?.total ?? 0}
            filters={auditFilters}
            onFiltersChange={setAuditFilters}
            loading={audit.loading}
          />
        </>
      ) : null}

      {view === 'users' ? (
        <>
          <header className="flex flex-wrap items-end justify-between gap-3">
            <div className="flex items-center gap-2">
              <Users size={18} aria-hidden="true" className="text-secondary" />
              <h1 className="text-lg font-semibold">Accounts</h1>
            </div>
            <span className="badge badge-sm badge-outline font-mono">role: admin</span>
          </header>

          {adminUsers.error ? (
            <div className="alert alert-error" role="alert">
              <span className="text-xs">{adminUsers.error}</span>
            </div>
          ) : null}

          <UserAttributesManager
            users={adminUsers.data?.users ?? []}
            assignableAttributes={adminUsers.data?.assignable_attributes ?? []}
            assignableRoles={adminUsers.data?.assignable_roles ?? []}
            updatingUserId={updatingUserId}
            onUpdate={updateUser}
          />
        </>
      ) : null}

      <WhyDeniedDialog
        group={explainedGroup}
        attributes={user?.attributes ?? []}
        onClose={() => setExplainedGroup(null)}
      />
    </AppShell>
  )
}

