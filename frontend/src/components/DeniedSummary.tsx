import { ShieldX } from 'lucide-react'
import type { DeniedSummary as DeniedSummaryType } from '../lib/types.ts'

interface DeniedSummaryProps {
  denied: DeniedSummaryType
  onExplain: (policy: string) => void
}

/**
 * What was refused, why, and which attribute would change the outcome. The values
 * inside the refused ciphertexts are absent by construction - only this summary is
 * available, which is exactly what a CP-ABE deployment can report.
 */
export default function DeniedSummary({ denied, onExplain }: DeniedSummaryProps) {
  if (denied.count === 0) {
    return (
      <div className="alert alert-success" role="status">
        <ShieldX size={16} aria-hidden="true" />
        <span>Every record in scope decrypted with your attribute set.</span>
      </div>
    )
  }

  return (
    <section className="flex flex-col gap-3" aria-labelledby="denied-heading">
      <div className="alert alert-warning" role="status">
        <ShieldX size={16} aria-hidden="true" />
        <span>
          <strong>{denied.count}</strong> record{denied.count === 1 ? '' : 's'} refused by
          policy. No values were returned for them.
        </span>
      </div>

      <h3 id="denied-heading" className="text-sm font-semibold">
        Refusals grouped by ciphertext policy
      </h3>

      <ul className="flex min-w-0 flex-col gap-2">
        {denied.by_policy.map((group) => (
          <li
            key={group.policy}
            className="flex min-w-0 flex-col gap-2 rounded-box border border-base-300 bg-base-100 p-3"
          >
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <span className="badge badge-sm badge-error">{group.count} refused</span>
              <code className="min-w-0 flex-1 overflow-x-auto font-mono text-xs">
                {group.policy}
              </code>
              <button
                type="button"
                className="btn btn-outline btn-xs"
                onClick={() => onExplain(group.policy)}
              >
                Why refused?
              </button>
            </div>
            <p className="text-xs text-base-content/70">{group.reason}</p>
            {group.missing_attributes.length > 0 ? (
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-[0.6875rem] uppercase tracking-wide text-base-content/60">
                  would unlock
                </span>
                {group.missing_attributes.map((attribute) => (
                  <span key={attribute} className="badge badge-sm badge-outline font-mono">
                    {attribute}
                  </span>
                ))}
              </div>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  )
}
