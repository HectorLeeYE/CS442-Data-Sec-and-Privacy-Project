import { ChevronDown, ScrollText } from 'lucide-react'
import { Fragment, useState } from 'react'
import { formatTimestamp } from '../lib/format.ts'
import type { AuditEntry } from '../lib/types.ts'
import DecisionBadge from './DecisionBadge.tsx'
import EmptyState from './EmptyState.tsx'

export interface AuditFilters {
  action: string
  decision: string
}

interface AuditTableProps {
  entries: AuditEntry[]
  total: number
  filters: AuditFilters
  onFiltersChange: (filters: AuditFilters) => void
  loading: boolean
}

const ACTIONS = ['', 'login', 'logout', 'query', 'attributes_change']
const DECISIONS = ['', 'granted', 'denied']

function detailCounts(entry: AuditEntry): string {
  const granted = entry.detail?.granted
  const denied = entry.detail?.denied
  if (typeof granted === 'number' && typeof denied === 'number') {
    return `${granted} decrypted / ${denied} refused`
  }
  return '—'
}

/**
 * The audit trail: every sign-in, query, and attribute change with the attribute set
 * the decision was made with. Administrator-only, guarded by role.
 */
export default function AuditTable({
  entries,
  total,
  filters,
  onFiltersChange,
  loading,
}: AuditTableProps) {
  const [expanded, setExpanded] = useState<number | null>(null)

  return (
    <section className="flex min-w-0 flex-col gap-3" aria-labelledby="audit-heading">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex items-center gap-2">
          <ScrollText size={16} aria-hidden="true" className="text-primary" />
          <h3 id="audit-heading" className="text-sm font-semibold">
            Audit trail
          </h3>
          <span className="badge badge-sm badge-outline">{total} entries</span>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <div className="flex flex-col gap-1">
            <label className="label font-mono text-[0.6875rem]" htmlFor="audit-action">
              Action
            </label>
            <select
              id="audit-action"
              className="select select-sm w-40"
              value={filters.action}
              onChange={(event) => onFiltersChange({ ...filters, action: event.target.value })}
            >
              {ACTIONS.map((action) => (
                <option key={action || 'all'} value={action}>
                  {action || 'all actions'}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label className="label font-mono text-[0.6875rem]" htmlFor="audit-decision">
              Decision
            </label>
            <select
              id="audit-decision"
              className="select select-sm w-36"
              value={filters.decision}
              onChange={(event) => onFiltersChange({ ...filters, decision: event.target.value })}
            >
              {DECISIONS.map((decision) => (
                <option key={decision || 'all'} value={decision}>
                  {decision || 'all decisions'}
                </option>
              ))}
            </select>
          </div>
          {loading ? (
            <span className="loading loading-spinner loading-sm text-primary"></span>
          ) : null}
        </div>
      </div>

      {entries.length === 0 ? (
        <EmptyState
          title="No audit entries match"
          description="Widen the action or decision filter, or run a query on the Query tab to create an entry."
          icon={<ScrollText size={28} />}
        />
      ) : (
        <div className="max-w-full min-w-0 overflow-x-auto rounded-box border border-base-300 bg-base-100">
          <table className="table table-sm table-zebra">
            <caption className="sr-only">Audit entries, newest first.</caption>
            <thead>
              <tr>
                <th scope="col">When</th>
                <th scope="col">Actor</th>
                <th scope="col">Action</th>
                <th scope="col">Dataset</th>
                <th scope="col">Decision</th>
                <th scope="col">Effect</th>
                <th scope="col">
                  <span className="sr-only">Detail</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => {
                const isOpen = expanded === entry.id
                return (
                  <Fragment key={entry.id}>
                    <tr className="hover:bg-base-300">
                      <td className="font-mono text-xs whitespace-nowrap tabular-nums">
                        {formatTimestamp(entry.created_at)}
                      </td>
                      <td className="text-xs">{entry.actor_email}</td>
                      <td>
                        <span className="badge badge-sm badge-neutral font-mono">
                          {entry.action}
                        </span>
                      </td>
                      <td className="font-mono text-xs">{entry.dataset_slug ?? '—'}</td>
                      <td>
                        <DecisionBadge granted={entry.decision === 'granted'} />
                      </td>
                      <td className="text-xs">{detailCounts(entry)}</td>
                      <td>
                        <button
                          type="button"
                          className="btn btn-ghost btn-xs"
                          aria-expanded={isOpen}
                          onClick={() => setExpanded(isOpen ? null : entry.id)}
                        >
                          <ChevronDown
                            size={14}
                            aria-hidden="true"
                            className={isOpen ? 'rotate-180' : undefined}
                          />
                          {isOpen ? 'Hide' : 'Show'}
                        </button>
                      </td>
                    </tr>
                    {isOpen ? (
                      <tr>
                        <td colSpan={7} className="bg-base-200">
                          <div className="flex flex-col gap-2 p-2 text-xs">
                            <p className="text-base-content/80">{entry.reason}</p>
                            {entry.policy ? (
                              <code className="overflow-x-auto font-mono text-xs">
                                {entry.policy}
                              </code>
                            ) : null}
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="font-mono text-[0.6875rem] uppercase tracking-wide text-base-content/60">
                                attribute set at decision time
                              </span>
                              {entry.actor_attributes.map((attribute) => (
                                <span
                                  key={attribute}
                                  className="badge badge-sm badge-outline font-mono"
                                >
                                  {attribute}
                                </span>
                              ))}
                            </div>
                            <pre className="max-w-full overflow-x-auto rounded-field border border-base-300 bg-base-100 p-2 font-mono text-[0.6875rem]">
                              {JSON.stringify(entry.detail, null, 2)}
                            </pre>
                          </div>
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
