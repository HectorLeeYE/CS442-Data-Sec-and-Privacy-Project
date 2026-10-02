import { CircleCheck, CircleX, Eye, FileInput, Link2, RefreshCw, ShieldOff } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { api, ApiError, TIER_RANK, type AuditEntry, type Chain, type User } from '../api'
import TierBadge from '../components/TierBadge'

const ACTION = {
  view: { label: 'Released', Icon: Eye, cls: 'badge badge-sm badge-ghost' },
  deny: { label: 'Denied', Icon: ShieldOff, cls: 'badge badge-sm badge-soft badge-error' },
  ingest: { label: 'Ingested', Icon: FileInput, cls: 'badge badge-sm badge-ghost' },
} as const

export default function Audit({ user }: { user: User }) {
  const [data, setData] = useState<{ entries: AuditEntry[]; chain: Chain } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<'all' | AuditEntry['action']>('all')
  const allowed = TIER_RANK[user.tier] >= TIER_RANK.RED

  const load = useCallback(() => {
    setError(null)
    api<{ entries: AuditEntry[]; chain: Chain }>('/api/audit')
      .then(setData)
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Could not load the log'))
  }, [])

  useEffect(() => {
    if (allowed) load()
  }, [allowed, load])

  if (!allowed) {
    return (
      <div role="status" className="alert alert-soft max-w-2xl">
        <ShieldOff size={18} aria-hidden="true" />
        <div>
          <h2 className="font-semibold">The disclosure log is RED-only</h2>
          <p className="text-sm">It records who received which call at which clearance. You hold {user.tier}; sign in as compliance to inspect it.</p>
        </div>
      </div>
    )
  }

  const rows = data?.entries.filter((e) => filter === 'all' || e.action === filter) ?? []
  const counts = data ? {
    view: data.entries.filter((e) => e.action === 'view').length,
    deny: data.entries.filter((e) => e.action === 'deny').length,
  } : null

  return (
    <div className="flex flex-col gap-4">
      <div className="stats stats-vertical w-full border border-base-300 bg-base-100 md:stats-horizontal">
        <div className="stat">
          <div className="stat-figure">
            {!data ? <span className="loading loading-spinner loading-sm" /> : data.chain.ok
              ? <CircleCheck className="text-success" aria-hidden="true" /> : <CircleX className="text-error" aria-hidden="true" />}
          </div>
          <div className="stat-title">Hash chain</div>
          <div className="stat-value text-2xl">{!data ? '…' : data.chain.ok ? 'Intact' : 'Broken'}</div>
          <div className="stat-desc">
            {!data ? 'Verifying' : data.chain.ok
              ? `${data.chain.checked} entries re-hashed from genesis`
              : `Entry #${data.chain.broken_at} does not match its predecessor`}
          </div>
        </div>
        <div className="stat">
          <div className="stat-title">Releases</div>
          <div className="stat-value text-2xl tabular-nums">{counts?.view ?? '…'}</div>
          <div className="stat-desc">Each with a SHA-256 of the exact text released</div>
        </div>
        <div className="stat">
          <div className="stat-title">Denied requests</div>
          <div className="stat-value text-2xl tabular-nums">{counts?.deny ?? '…'}</div>
          <div className="stat-desc">Above-clearance or other-agent requests</div>
        </div>
      </div>

      {error && <div role="alert" className="alert alert-soft alert-error text-sm">{error}</div>}
      {data && !data.chain.ok && (
        <div role="alert" className="alert alert-error text-sm">
          <CircleX size={16} aria-hidden="true" />
          The log was altered after the fact. Entries from #{data.chain.broken_at} onward cannot be trusted as a record of what was disclosed.
        </div>
      )}

      <section className="min-w-0 rounded-box border border-base-300 bg-base-100">
        <div className="flex flex-wrap items-center gap-2 border-b border-base-300 p-3">
          <div role="tablist" aria-label="Filter by action" className="tabs tabs-box tabs-xs">
            {(['all', 'view', 'deny', 'ingest'] as const).map((f) => (
              <button key={f} role="tab" aria-selected={filter === f} className={filter === f ? 'tab tab-active' : 'tab'} onClick={() => setFilter(f)}>
                {f === 'all' ? 'All' : ACTION[f].label}
              </button>
            ))}
          </div>
          <button className="btn btn-sm ml-auto" onClick={load}>
            <RefreshCw size={14} aria-hidden="true" /> Re-verify chain
          </button>
        </div>
        <div className="max-w-full overflow-x-auto">
          <table className="table table-sm">
            <thead>
              <tr><th>#</th><th>Time (UTC)</th><th>User</th><th>Event</th><th>Call</th><th>View</th><th>Released digest</th><th>Entry hash</th></tr>
            </thead>
            <tbody className="tabular-nums">
              {!data && [0, 1, 2].map((i) => <tr key={i}><td colSpan={8}><div className="skeleton h-5 w-full" /></td></tr>)}
              {data && rows.length === 0 && <tr><td colSpan={8} className="text-sm text-base-content/60">No {filter === 'all' ? '' : ACTION[filter].label.toLowerCase()} entries yet. Open a call to create one.</td></tr>}
              {rows.map((e) => {
                const a = ACTION[e.action]
                return (
                  <tr key={e.seq}>
                    <td className="font-mono text-xs">{e.seq}</td>
                    <td className="whitespace-nowrap font-mono text-xs">{e.ts.replace('T', ' ').replace('+00:00', '')}</td>
                    <td className="whitespace-nowrap"><span className="mr-1 font-mono text-xs">{e.username}</span><TierBadge tier={e.user_tier} /></td>
                    <td><span className={a.cls}><a.Icon size={12} aria-hidden="true" />{a.label}</span></td>
                    <td className="font-mono text-xs">{e.call_id ?? '—'}</td>
                    <td>{e.view_tier ? <TierBadge tier={e.view_tier} /> : '—'}</td>
                    <td className="font-mono text-xs">{e.digest ? `${e.digest.slice(0, 10)}…` : '—'}</td>
                    <td className="font-mono text-xs">
                      <span className="tooltip tooltip-left" data-tip={`prev ${e.prev.slice(0, 10)}…`}>
                        <span tabIndex={0} className="inline-flex items-center gap-1"><Link2 size={11} aria-hidden="true" />{e.hash.slice(0, 10)}…</span>
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
