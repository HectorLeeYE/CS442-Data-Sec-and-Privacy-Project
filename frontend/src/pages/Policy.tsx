import { useEffect, useState } from 'react'
import { api, CLASS_CODE, TIERS, type Tier } from '../api'
import TierBadge from '../components/TierBadge'

type Taxonomy = {
  tiers: Tier[]
  tier_roles: Record<Tier, string>
  classes: Record<string, { harm: number; description: string; actions: Record<Tier, string> }>
  types: Record<string, { class: string; description: string; actions?: Partial<Record<Tier, string>> }>
  matrix: Record<string, Record<Tier, string>>
}

const ACTION_CLS: Record<string, string> = {
  keep: 'badge badge-sm badge-ghost',
  surrogate: 'badge badge-sm badge-soft badge-info',
  pseudonym: 'badge badge-sm badge-soft badge-info',
  mask_last4: 'badge badge-sm badge-soft badge-warning',
  generalize: 'badge badge-sm badge-soft badge-warning',
  suppress: 'badge badge-sm badge-soft badge-error',
}

export default function Policy() {
  const [t, setT] = useState<Taxonomy | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api<Taxonomy>('/api/taxonomy').then(setT).catch((e) => setError(e.message))
  }, [])

  if (error) return <div role="alert" className="alert alert-soft alert-error text-sm">{error}</div>
  if (!t) return <div className="skeleton h-96 w-full" />

  return (
    <div className="flex flex-col gap-4">
      <p className="max-w-3xl text-sm text-base-content/70">
        This matrix is read from <code className="font-mono">backend/taxonomy.yaml</code> at startup, so it is exactly what the
        redactor applies. Per-type overrides are marked with a dot. Actions left to right preserve less utility:
        keep, surrogate, mask, pseudonym, generalize, suppress.
      </p>
      <div className="grid gap-3 md:grid-cols-3">
        {TIERS.map((tier) => (
          <div key={tier} className="rounded-box border border-base-300 bg-base-100 p-3 text-sm">
            <TierBadge tier={tier} />
            <p className="mt-1">{t.tier_roles[tier]}</p>
          </div>
        ))}
      </div>
      <section className="min-w-0 rounded-box border border-base-300 bg-base-100">
        <div className="max-w-full overflow-x-auto">
          <table className="table table-sm">
            <thead>
              <tr><th>Entity type</th><th>Description</th>{TIERS.map((tier) => <th key={tier}><TierBadge tier={tier} /></th>)}</tr>
            </thead>
            {Object.entries(t.classes).map(([cls, c]) => (
              <tbody key={cls}>
                <tr className="bg-base-200">
                  <th colSpan={2 + TIERS.length} className="font-normal">
                    <span className="font-mono font-medium">{CLASS_CODE[cls]} · {cls}</span>
                    <span className="ml-2 text-xs text-base-content/70">harm weight {c.harm} — {c.description}</span>
                  </th>
                </tr>
                {Object.entries(t.types).filter(([, ty]) => ty.class === cls).map(([name, ty]) => (
                  <tr key={name}>
                    <td className="font-mono text-xs">{name}</td>
                    <td className="text-xs">{ty.description}</td>
                    {TIERS.map((tier) => (
                      <td key={tier}>
                        <span className={ACTION_CLS[t.matrix[name][tier]]}>
                          {t.matrix[name][tier]}
                          {ty.actions?.[tier] && <span aria-label="per-type override">•</span>}
                        </span>
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            ))}
          </table>
        </div>
      </section>
    </div>
  )
}
