import { Database, Filter, ShieldCheck, ShieldX } from 'lucide-react'
import type { CSSProperties, ReactNode } from 'react'
import { percent } from '../lib/format.ts'
import type { QueryTotals } from '../lib/types.ts'

interface AccessMetricsProps {
  totals: QueryTotals
  cryptoBackend: string
  encrypted: boolean
  tookMs: number
  notice: string
}

function MetricCard({
  icon,
  label,
  value,
  hint,
}: {
  icon: ReactNode
  label: string
  value: string | number
  hint: string
}) {
  return (
    <div className="card border border-base-300 bg-base-100">
      <div className="card-body gap-1 p-4">
        <div className="flex items-center gap-2 text-base-content/60">
          <span aria-hidden="true">{icon}</span>
          <span className="font-mono text-[0.6875rem] uppercase tracking-wide">{label}</span>
        </div>
        <p className="text-2xl font-semibold tabular-nums">{value}</p>
        <p className="text-xs text-base-content/60">{hint}</p>
      </div>
    </div>
  )
}

/**
 * What the last query did, stated in the vocabulary of the access decision:
 * every record is tried against its policy, and only what decrypts is filtered.
 */
export default function AccessMetrics({
  totals,
  cryptoBackend,
  encrypted,
  tookMs,
  notice,
}: AccessMetricsProps) {
  const decryptedShare = percent(totals.granted, totals.scanned)
  const denominator = totals.scanned > 0 ? totals.scanned : 1

  return (
    <section className="flex flex-col gap-3" aria-label="Access metrics for the last query">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <MetricCard
          icon={<Database size={16} />}
          label="Records scanned"
          value={totals.scanned}
          hint="Each record's ciphertext policy was evaluated"
        />
        <MetricCard
          icon={<ShieldCheck size={16} />}
          label="Decrypted"
          value={totals.granted}
          hint="Your attribute set satisfied the policy"
        />
        <MetricCard
          icon={<ShieldX size={16} />}
          label="Refused"
          value={totals.denied}
          hint="No values released, only a reason"
        />
        <MetricCard
          icon={<Filter size={16} />}
          label="Matched filters"
          value={totals.matched}
          hint={`out of ${totals.granted} decryptable rows`}
        />
      </div>

      <div className="card border border-base-300 bg-base-100">
        <div className="card-body gap-4 p-4 sm:flex-row sm:items-center">
          <div
            className="radial-progress text-primary"
            style={{ '--value': decryptedShare, '--size': '4.5rem' } as CSSProperties}
            aria-valuenow={decryptedShare}
            role="progressbar"
            aria-label="Share of records your attribute set can decrypt"
          >
            <span className="font-mono text-sm tabular-nums">{decryptedShare}%</span>
          </div>
          <div className="flex min-w-0 flex-1 flex-col gap-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-sm font-medium">
                {totals.granted} of {totals.scanned} records decryptable
              </span>
              <span className="flex items-center gap-2">
                <span
                  className={
                    encrypted
                      ? 'badge badge-sm badge-success'
                      : 'badge badge-sm badge-warning'
                  }
                >
                  {encrypted ? 'real ciphertext' : 'placeholder ciphertext'}
                </span>
                <span className="badge badge-sm badge-outline font-mono">{cryptoBackend}</span>
                <span className="font-mono text-[0.6875rem] tabular-nums text-base-content/60">
                  {tookMs} ms
                </span>
              </span>
            </div>
            <progress
              className="progress progress-primary"
              value={totals.granted}
              max={denominator}
            ></progress>
            <p className="text-xs text-base-content/60">{notice}</p>
          </div>
        </div>
      </div>
    </section>
  )
}
