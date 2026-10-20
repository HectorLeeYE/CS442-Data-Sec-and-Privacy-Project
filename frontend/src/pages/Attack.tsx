import { Crosshair, Lock, LockOpen, ShieldAlert, ShieldCheck, ShieldOff } from 'lucide-react'
import { useState } from 'react'
import { api, ApiError, TIERS, type AttackAssets, type AttackResult } from '../api'
import TierBadge from '../components/TierBadge'

const NONE: AttackAssets = {
  database: false, user_key: null, keys_volume: false, ka_volume: false,
  app_secret: false, ka_secret: false, ka_access: false,
}

const PRESETS: { label: string; assets: Partial<AttackAssets> }[] = [
  { label: 'Stolen database', assets: { database: true } },
  { label: 'Database + data scientist\'s key', assets: { database: true, user_key: 'datasci' } },
  { label: 'Rogue agent', assets: { database: true, user_key: 'priya' } },
  { label: 'Stolen backup of every volume', assets: { database: true, keys_volume: true, ka_volume: true } },
  { label: 'Root on the app server', assets: { database: true, keys_volume: true, app_secret: true, ka_secret: true, ka_access: true } },
  { label: 'Everything', assets: { database: true, user_key: 'compliance', keys_volume: true, ka_volume: true, app_secret: true, ka_secret: true, ka_access: true } },
]

const STOLEN: { group: string; items: { key: keyof AttackAssets; label: string; hint: string }[] }[] = [
  {
    group: 'Files',
    items: [
      { key: 'database', label: 'Database file (/data)', hint: 'Every encrypted copy, wrapped data key and policy' },
      { key: 'keys_volume', label: 'Server key volume (/keys)', hint: 'server.json: the receipt-signing key, sealed under APP_SECRET' },
      { key: 'ka_volume', label: 'Key-authority volume (/ka)', hint: 'authority.json: ABE master key and tree-head key, sealed under KA_SECRET' },
    ],
  },
  {
    group: 'Secrets',
    items: [
      { key: 'app_secret', label: 'APP_SECRET', hint: 'Opens server.json and the triage reasons' },
      { key: 'ka_secret', label: 'KA_SECRET', hint: 'Opens authority.json and signs clearance assertions' },
    ],
  },
  {
    group: 'Access',
    items: [{ key: 'ka_access', label: 'Network access to the key authority', hint: 'Can ask it for keys, if it can forge an assertion it accepts' }],
  },
]

const VICTIMS = [
  { username: 'datasci', label: 'Alex Chua, data science (GREEN)' },
  { username: 'priya', label: 'Priya Nair, call agent (AMBER)' },
  { username: 'daniel', label: 'Daniel Koh, call agent (AMBER)' },
  { username: 'compliance', label: 'Rachel Ong, compliance (RED)' },
]

const FILE_STATUS: Record<string, string> = {
  'not stolen': 'Not stolen',
  absent: 'Not on this host (the authority runs in its own container)',
  sealed: 'Stolen, but sealed: the secret is wrong',
  opened: 'Opened',
}

function verdict(r: AttackResult) {
  const n = (k: 'RED' | 'AMBER' | 'GREEN' | 'reasons') => Object.values(r.calls ?? {}).filter((c) => c[k]).length
  if (n('RED') || r.authority_keys === 'opened' || r.ka_request === 'issued')
    return { cls: 'alert-error', Icon: ShieldOff, title: 'Full breach', text: 'The attacker reads calls in full, or can mint a key that does.' }
  if (n('AMBER') || n('reasons') || r.receipt_key === 'opened')
    return { cls: 'alert-warning', Icon: ShieldAlert, title: 'Partial breach', text: 'Some identifiable data or a signing key is exposed, but no RED copy.' }
  if (n('GREEN'))
    return { cls: 'alert-info', Icon: ShieldCheck, title: 'De-identified data only', text: 'Only GREEN copies opened: the training release, with identifiers already replaced.' }
  return { cls: 'alert-success', Icon: ShieldCheck, title: 'Attack failed', text: 'Nothing the attacker holds opens anything.' }
}

const Opened = ({ ok }: { ok?: boolean }) =>
  ok === undefined ? <span className="text-base-content/40">—</span>
    : ok ? <LockOpen size={15} className="text-error" aria-label="opened" />
      : <Lock size={15} className="text-base-content/40" aria-label="refused" />

export default function Attack() {
  const [assets, setAssets] = useState<AttackAssets>({ ...NONE, database: true })
  const [result, setResult] = useState<AttackResult | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = () => {
    setRunning(true)
    setError(null)
    api<AttackResult>('/api/attack', { method: 'POST', body: JSON.stringify(assets) })
      .then(setResult)
      .catch((e) => setError(e instanceof ApiError ? e.message : 'The simulation failed'))
      .finally(() => setRunning(false))
  }

  const calls = result?.calls ? Object.entries(result.calls) : []
  const v = result && verdict(result)

  return (
    <div className="grid gap-4 xl:grid-cols-[22rem_minmax(0,1fr)]">
      <section className="card h-fit border border-base-300 bg-base-100">
        <div className="card-body gap-4 p-4">
          <div>
            <h2 className="font-semibold">What the attacker has</h2>
            <p className="text-xs text-base-content/70">Every decryption runs for real on the stored calls. A secret the attacker lacks is replaced by a random guess. Only what opened comes back, never the text.</p>
          </div>
          <div className="flex flex-wrap gap-1">
            {PRESETS.map((p) => (
              <button key={p.label} className="btn btn-xs" onClick={() => setAssets({ ...NONE, ...p.assets })}>{p.label}</button>
            ))}
          </div>
          {STOLEN.map(({ group, items }) => (
            <fieldset key={group} className="fieldset gap-2 p-0">
              <legend className="fieldset-legend">{group}</legend>
              {items.map(({ key, label, hint }) => (
                <label key={key} className="flex cursor-pointer items-start gap-2">
                  <input type="checkbox" className="checkbox checkbox-sm mt-0.5" checked={Boolean(assets[key])}
                    onChange={(e) => setAssets({ ...assets, [key]: e.target.checked })} />
                  <span>
                    <span className="block text-sm">{label}</span>
                    <span className="block text-xs text-base-content/60">{hint}</span>
                  </span>
                </label>
              ))}
              {group === 'Files' && (
                <label className="flex flex-col gap-1">
                  <span className="text-sm">A user's ABE key</span>
                  <select className="select select-sm w-full" value={assets.user_key ?? ''}
                    onChange={(e) => setAssets({ ...assets, user_key: e.target.value || null })}>
                    <option value="">None</option>
                    {VICTIMS.map((u) => <option key={u.username} value={u.username}>{u.label}</option>)}
                  </select>
                </label>
              )}
            </fieldset>
          ))}
          <button className="btn btn-primary" onClick={run} disabled={running}>
            {running ? <span className="loading loading-spinner loading-sm" /> : <Crosshair size={16} aria-hidden="true" />}
            {running ? 'Attacking…' : 'Run attack'}
          </button>
          <p className="text-xs text-base-content/60">Each run is written to the disclosure log. Keys the key authority mints for it appear in its issued-key log.</p>
        </div>
      </section>

      <div className="flex min-w-0 flex-col gap-4">
        {error && <div role="alert" className="alert alert-soft alert-error text-sm">{error}</div>}
        {!result && !error && (
          <div className="rounded-box border border-dashed border-base-300 bg-base-100 p-8 text-center text-sm text-base-content/60">
            Pick what the attacker holds, then run the attack.
          </div>
        )}
        {result && v && (
          <>
            <div role="status" className={`alert ${v.cls}`}>
              <v.Icon size={20} aria-hidden="true" />
              <div>
                <h2 className="font-semibold">{v.title}</h2>
                <p className="text-sm">{v.text}</p>
              </div>
            </div>

            {result.calls && (
              <div className="stats stats-vertical w-full border border-base-300 bg-base-100 sm:stats-horizontal">
                {TIERS.map((t) => (
                  <div key={t} className="stat">
                    <div className="stat-title flex items-center gap-1"><TierBadge tier={t} /> copies opened</div>
                    <div className="stat-value text-2xl tabular-nums">{calls.filter(([, c]) => c[t]).length} / {calls.filter(([, c]) => t in c).length}</div>
                  </div>
                ))}
                <div className="stat">
                  <div className="stat-title">Triage reasons read</div>
                  <div className="stat-value text-2xl tabular-nums">{calls.filter(([, c]) => c.reasons).length} / {calls.length}</div>
                </div>
              </div>
            )}

            <section className="rounded-box border border-base-300 bg-base-100 p-4 text-sm">
              <h3 className="mb-2 font-semibold">Keys</h3>
              <dl className="grid gap-x-4 gap-y-1 sm:grid-cols-[14rem_1fr]">
                <dt className="text-base-content/70">ABE keys in hand</dt>
                <dd>{result.keys.length ? result.keys.join('; ') : 'None'}</dd>
                <dt className="text-base-content/70">Receipt-signing key</dt>
                <dd className={result.receipt_key === 'opened' ? 'text-error' : undefined}>
                  {FILE_STATUS[result.receipt_key]}{result.receipt_key === 'opened' && ': can forge receipts and export manifests'}
                </dd>
                <dt className="text-base-content/70">ABE master + tree-head key</dt>
                <dd className={result.authority_keys === 'opened' ? 'text-error' : undefined}>
                  {FILE_STATUS[result.authority_keys]}{result.authority_keys === 'opened' && ': can mint any key and sign a rewritten audit log'}
                </dd>
                <dt className="text-base-content/70">Key request to the authority</dt>
                <dd className={result.ka_request === 'issued' ? 'text-error' : undefined}>
                  {result.ka_request === 'not attempted' ? 'Not attempted' : result.ka_request === 'issued' ? 'Issued a key for every attribute (logged by the authority)' : result.ka_request}
                </dd>
              </dl>
            </section>

            {result.calls ? (
              <section className="min-w-0 rounded-box border border-base-300 bg-base-100">
                <div className="max-w-full overflow-x-auto">
                  <table className="table table-sm">
                    <thead>
                      <tr><th>Call</th><th>Risk</th><th>Review</th>{TIERS.map((t) => <th key={t}><TierBadge tier={t} /></th>)}<th>Triage reason</th></tr>
                    </thead>
                    <tbody>
                      {calls.map(([id, c]) => (
                        <tr key={id}>
                          <td className="font-mono text-xs">{id}</td>
                          <td className="text-xs">{c.risk}</td>
                          <td className="text-xs">{c.review === 'pending' ? 'held' : c.review}</td>
                          {TIERS.map((t) => <td key={t}><Opened ok={c[t]} /></td>)}
                          <td><Opened ok={c.reasons} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            ) : (
              <p className="text-sm text-base-content/60">No database stolen, so there are no transcripts to try.</p>
            )}
          </>
        )}
      </div>
    </div>
  )
}
