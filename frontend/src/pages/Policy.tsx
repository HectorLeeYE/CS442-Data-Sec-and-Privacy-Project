import { useEffect, useState } from 'react'
import { api, CLASS_CODE, TIERS, type Tier } from '../api'
import TierBadge from '../components/TierBadge'

type Taxonomy = {
  tiers: Tier[]
  tier_roles: Record<Tier, string>
  classes: Record<string, { harm: number; description: string; harm_rationale: string; regulation: string[]; actions: Record<Tier, string> }>
  types: Record<string, { class: string; description: string; actions?: Partial<Record<Tier, string>> }>
  matrix: Record<string, Record<Tier, string>>
  triage: { overseas_transfer_threshold: number; fraud_cues: string[]; transfer_cues: string[] }
  review: { min_ner_score: number; residual_digits: number }
  release: { k: number }
  retention_days: { high: number; low: number }
  version: string
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
        keep, surrogate, mask, pseudonym, generalize, suppress. Policy version <code className="font-mono">{t.version}</code>.
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
                    <span className="mt-1 block text-xs text-base-content/70">Why this weight: {c.harm_rationale}</span>
                    <span className="mt-1 block text-xs text-base-content/70">Legal basis: {c.regulation.join('; ')}</span>
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
      <section aria-labelledby="ops-title" className="rounded-box border border-base-300 bg-base-100 p-4">
        <h2 id="ops-title" className="font-semibold">Operating policy (same file)</h2>
        <dl className="mt-2 grid gap-x-4 gap-y-2 text-sm md:grid-cols-[14rem_minmax(0,1fr)]">
          <dt className="text-base-content/70">High-risk triage</dt>
          <dd>Fraud cues ({t.triage.fraud_cues.join(', ')}), or an overseas transfer of at least S${t.triage.overseas_transfer_threshold.toLocaleString()}. Only high-risk calls are referred to RED in full; low-risk calls need a break-glass reason.</dd>
          <dt className="text-base-content/70">Held for review before GREEN</dt>
          <dd>An agent request (OTP, PIN, account, pet's name…) with no matching answer found, NER spans below score {t.review.min_ner_score}, or {t.review.residual_digits}+ unclassified digits.</dd>
          <dt className="text-base-content/70">GREEN export gate</dt>
          <dd>k-anonymity with k = {t.release.k}: a call whose quasi-identifier combination is rarer loses its quasi-identifiers.</dd>
          <dt className="text-base-content/70">Retention (PDPA)</dt>
          <dd>High-risk calls {t.retention_days.high} days, low-risk {t.retention_days.low} days, then crypto-shredded.</dd>
        </dl>
      </section>
    </div>
  )
}
