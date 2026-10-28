import { Bird, FlaskConical, Info, LockKeyhole, Mic, ScanSearch, ShieldCheck, Terminal, TriangleAlert } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, type Tier } from '../api'
import TierBadge from '../components/TierBadge'

// Read-only view of the experiment outputs (GET /api/results, i.e. backend/experiments/out/e*.json).
// Nothing here touches ingest, redaction or the encrypted store.

type Metrics = { harm_weighted_recall: number; entity_recall?: number; precision: number; over_redaction: number; recall: Record<string, number | null> }
type Gate = { queued: number; recall_after_review: number }
type Results = {
  e1?: {
    ablation: Record<'clean' | 'noisy', (Metrics & { config: string })[]>
    ood: Record<string, unknown> & { gliner_review?: { rules: Gate; 'with GLiNER': Gate } }
    tier_actions?: Record<'clean' | 'noisy', Record<Tier, Record<string, number>>>
  }
  e2?: { variants: { variant: string; perplexity: number }[]; dp?: { n_clients: number; cap: number; rows: { text: string; epsilon: number | null; perplexity: number }[] } }
  e3?: { conditions: Record<'clean' | 'noisy', { condition: string; reidentified: number }[]> }
  e6?: { candidates: number; max_exposure: number; releases: string[]; rows: { kind: string; frame: string; reps: number; detected: number; held: number; exposure: Record<string, number> }[] }
  e7?: {
    heldout?: { clips: number; before: Judged; after: Judged; judge?: string } | null
    bank_test2?: Record<string, unknown> & { n_calls: number; n_spans: number; ci: [number, number]; gliner_review?: { rules: Gate } }
  }
  e8?: { test_calls: number; oracle_wer: number; rows: { release: string; wer: number }[] }
}
type Judged = { detections_per_1000_words: number; words_redacted_at_green: number; precision?: number; judged?: number }

// Data-series colours: the dataviz reference palette, light slots in fixed order (series colours are data, not theme).
const SERIES = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300']
const FULL = '+ propagate (full)'
const pct = (v: number) => `${(v * 100).toFixed(1)}%`
const num = (v: number, d = 1) => v.toLocaleString('en', { maximumFractionDigits: d, minimumFractionDigits: d })

type Series = { name: string; values: (number | null)[] }

/** Horizontal bars on one shared scale; every value is printed beside its bar. */
function Bars({ labels, series, fmt, max, label }: { labels: string[]; series: Series[]; fmt: (v: number) => string; max?: number; label: string }) {
  const top = max ?? Math.max(...series.flatMap((s) => s.values.filter((v): v is number => v != null)))
  return (
    <div role="figure" className="flex flex-col gap-2" aria-label={label}>
      {series.length > 1 && <Legend names={series.map((s) => s.name)} />}
      <div className="flex flex-col gap-2 text-xs">
        {labels.map((l, i) => (
          <div key={l} className="grid grid-cols-[minmax(0,38%)_minmax(0,1fr)] items-center gap-3">
            <span className="text-right">{l}</span>
            <div className="flex min-w-0 flex-col gap-0.5">
              {series.map((s, j) => {
                const v = s.values[i]
                if (v == null) return null
                return (
                  <div key={s.name} className="tooltip tooltip-top flex w-full items-center gap-1.5" data-tip={`${series.length > 1 ? `${s.name}: ` : ''}${fmt(v)}`}>
                    <div className="h-2.5 min-w-0 flex-1">
                      <div className="h-full rounded-r-sm" style={{ width: `${Math.max(0.5, (v / top) * 100)}%`, background: SERIES[j] }} />
                    </div>
                    <span className="w-14 shrink-0 text-right tabular-nums text-base-content/70">{fmt(v)}</span>
                  </div>
                )
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function Legend({ names }: { names: string[] }) {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-base-content/70" aria-label="Legend">
      {names.map((n, j) => (
        <li key={n} className="inline-flex items-center gap-1.5">
          <span className="size-2.5 rounded-sm" style={{ background: SERIES[j] }} aria-hidden="true" />
          {n}
        </li>
      ))}
    </ul>
  )
}

function Panel({ title, note, children }: { title: string; note: string; children: React.ReactNode }) {
  return (
    <section className="card card-border min-w-0 border-base-300 bg-base-100">
      <div className="card-body min-w-0 gap-3 p-4">
        <h3 className="card-title text-sm">{title}</h3>
        <p className="flex-none text-xs text-base-content/70">{note}</p>
        {children}
      </div>
    </section>
  )
}

const ACTIONS = [
  ['keep', 'Kept as is'], ['mask_last4', 'Masked to last 4 digits'], ['pseudonym', 'Pseudonym'],
  ['surrogate', 'Realistic fake'], ['generalize', 'Generalised'], ['suppress', 'Suppressed'],
] as const
const TIER_READER: Record<Tier, string> = { RED: 'Compliance', AMBER: 'Call agents', GREEN: 'Data science and the model' }

/** One 100% strip per tier: the share of detected spans each redaction action gets. */
function TierStrips({ counts }: { counts: Record<Tier, Record<string, number>> }) {
  const tiers: Tier[] = ['RED', 'AMBER', 'GREEN']
  return (
    <div className="flex flex-col gap-4">
      <Legend names={ACTIONS.map(([, l]) => l)} />
      {tiers.map((t) => {
        const c = counts[t] ?? {}
        const total = ACTIONS.reduce((n, [a]) => n + (c[a] ?? 0), 0)
        const kept = (c.keep ?? 0) / (total || 1)
        return (
          <div key={t} className="flex flex-col gap-1.5">
            <div className="flex flex-wrap items-baseline gap-2 text-xs">
              <TierBadge tier={t} />
              <span className="font-medium">{TIER_READER[t]}</span>
              <span className="ml-auto tabular-nums text-base-content/70">{pct(kept)} of detected PII shown as is</span>
            </div>
            <div className="flex h-6 w-full gap-0.5" role="img" aria-label={`${t}: ${ACTIONS.filter(([a]) => c[a]).map(([a, l]) => `${l} ${pct(c[a] / total)}`).join(', ')}`}>
              {ACTIONS.map(([a, l], j) => (c[a] ?? 0) > 0 && (
                <div key={a} className="tooltip tooltip-top h-full" style={{ width: `${(c[a] / total) * 100}%` }} data-tip={`${l}: ${pct(c[a] / total)} (${c[a].toLocaleString('en')} spans)`}>
                  <div className="h-full w-full rounded-sm" style={{ background: SERIES[j] }} />
                </div>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

/** Canary exposure: one small line chart per canary, exposure (bits) against how often it was planted. */
function Canaries({ e6 }: { e6: NonNullable<Results['e6']> }) {
  const kinds = [...new Set(e6.rows.map((r) => `${r.kind}|${r.frame}`))]
  const reps = [...new Set(e6.rows.map((r) => r.reps))].sort((a, b) => a - b)
  const W = 240, H = 130, m = { l: 26, r: 10, t: 8, b: 20 }
  const x = (r: number) => m.l + ((reps.indexOf(r) + 0.5) / reps.length) * (W - m.l - m.r)
  const y = (v: number) => m.t + (1 - v / e6.max_exposure) * (H - m.t - m.b)
  const relName: Record<string, string> = { raw: 'Trained on raw', GREEN: 'Trained on GREEN', 'GREEN, held calls withheld': 'GREEN without held calls' }
  const shortName: Record<string, string> = { raw: 'Raw', GREEN: 'GREEN', 'GREEN, held calls withheld': 'GREEN, held out' }
  return (
    <div className="flex flex-col gap-3">
      <Legend names={e6.releases.map((r) => relName[r] ?? r)} />
      <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,13rem),1fr))] gap-4">
        {kinds.map((k) => {
          const [kind, frame] = k.split('|')
          const rows = e6.rows.filter((r) => r.kind === kind && r.frame === frame)
          const name = `${kind === 'NRIC' ? 'NRIC' : 'Phone number'}, ${frame === 'caught' ? 'detector catches it' : 'detector misses it'}`
          return (
            <div key={k} role="figure" className="flex min-w-0 flex-col gap-1" aria-label={name}>
              <div className="flex items-center gap-1.5 text-xs font-medium">
                <span className={frame === 'caught' ? 'badge badge-soft badge-sm' : 'badge badge-soft badge-warning badge-sm'}>
                  {frame === 'caught' ? 'Caught' : 'Missed'}
                </span>
                {kind === 'NRIC' ? 'NRIC' : 'Phone number'}
              </div>
              <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={`${name}: exposure by repeats`} className="text-base-content">
                {[0, 4, 8, 12].map((t) => (
                  <g key={t}>
                    <line x1={m.l} x2={W - m.r} y1={y(t)} y2={y(t)} stroke="currentColor" strokeOpacity={0.12} />
                    <text x={m.l - 6} y={y(t)} dy="0.35em" textAnchor="end" fontSize={10} fill="currentColor" fillOpacity={0.6}>{t}</text>
                  </g>
                ))}
                <line x1={m.l} x2={W - m.r} y1={y(1)} y2={y(1)} stroke="currentColor" strokeOpacity={0.45} strokeDasharray="4 3" />
                {reps.map((r) => (
                  <text key={r} x={x(r)} y={H - 4} textAnchor="middle" fontSize={10} fill="currentColor" fillOpacity={0.6}>×{r}</text>
                ))}
                {e6.releases.map((rel, i) => {
                  const pts = rows.map((r) => [x(r.reps), y(r.exposure[rel])] as const)
                  return (
                    <g key={rel}>
                      <polyline points={pts.map((p) => p.join(',')).join(' ')} fill="none" stroke={SERIES[i]} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
                      {rows.map((r, n) => (
                        <circle key={r.reps} cx={pts[n][0]} cy={pts[n][1]} r={4} fill={SERIES[i]} stroke="var(--color-base-100)" strokeWidth={2}>
                          <title>{`${relName[rel] ?? rel}, planted ×${r.reps}: ${num(r.exposure[rel])} bits`}</title>
                        </circle>
                      ))}
                    </g>
                  )
                })}
              </svg>
            </div>
          )
        })}
      </div>
      <div className="max-w-full overflow-x-auto">
        <table className="table table-xs tabular-nums">
          <caption className="sr-only">Canary exposure in bits</caption>
          <thead><tr><th>Canary</th><th>Repeats</th><th>Detected</th><th>Held</th>{e6.releases.map((r) => <th key={r} className="text-right">{shortName[r] ?? r}</th>)}</tr></thead>
          <tbody>
            {e6.rows.filter((r) => r.reps === Math.max(...reps)).map((r) => (
              <tr key={`${r.kind}${r.frame}`}>
                <td>{r.kind}, {r.frame}</td><td>×{r.reps}</td><td>{pct(r.detected)}</td><td>{pct(r.held)}</td>
                {e6.releases.map((rel) => <td key={rel} className="text-right">{num(r.exposure[rel])} bits</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default function Dashboard() {
  const [r, setR] = useState<Results | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api<Results>('/api/results').then(setR).catch((e) => setError(e.message))
  }, [])

  if (error) {
    return (
      <div role="alert" className="alert alert-soft alert-error max-w-2xl text-sm">
        <TriangleAlert size={16} aria-hidden="true" />
        <span>Could not load the experiment results: {error}. Reload the page, or sign in again if your session expired.</span>
      </div>
    )
  }
  if (!r) {
    return (
      <div className="flex flex-col gap-4" aria-busy="true" aria-label="Loading results">
        <div className="skeleton h-24 w-full" />
        <div className="grid gap-4 xl:grid-cols-2"><div className="skeleton h-72" /><div className="skeleton h-72" /></div>
      </div>
    )
  }
  if (!r.e1 || !r.e2 || !r.e3) {
    return (
      <div role="status" className="alert alert-soft max-w-2xl">
        <FlaskConical size={18} aria-hidden="true" />
        <div>
          <h2 className="font-semibold">No experiment results on this server yet</h2>
          <p className="text-sm">The dashboard reads the experiment outputs. Generate them once, then reload:</p>
          <code className="mt-1 inline-flex items-center gap-1 font-mono text-xs"><Terminal size={12} aria-hidden="true" />cd backend && .venv/bin/python -m experiments.run</code>
        </div>
      </div>
    )
  }

  const { e1, e2, e3, e6 } = r
  const full = (m: 'clean' | 'noisy') => e1.ablation[m].find((x) => x.config === FULL)!
  const dev = e1.ood['our full detector'] as Metrics
  const sets: [string, Metrics][] = [['Clean transcripts', full('clean')], ['ASR-style', full('noisy')], ['Dev set (24 calls)', dev]]
  const layers = e1.ablation.clean.filter((x) => x.config !== 'full minus presidio')
  const classes: [string, string][] = [['DIRECT_ID', 'Direct identifiers'], ['FINANCIAL_ID', 'Financial identifiers'], ['AUTH_SECRET', 'Credentials'],
    ['QUASI_ID', 'Quasi-identifiers'], ['SENSITIVE_ATTR', 'Sensitive attributes']]
  const detectors: [string, string][] = [['presidio only', 'Presidio alone'], ['GLiNER-PII alone', 'GLiNER-PII alone'], ['our full detector', 'Our detector'], ['full + GLiNER', 'Ours + GLiNER']]
  const devDet = detectors.filter(([k]) => e1.ood[k])
  const gr = e1.ood.gliner_review
  const v = (name: string) => e2.variants.find((x) => x.variant === name)?.perplexity
  const green = v('GREEN policy, real detector'), raw = e2.variants.find((x) => x.variant.startsWith('raw'))?.perplexity
  const reid = (m: 'clean' | 'noisy', c: string) => e3.conditions[m].find((x) => x.condition === c)?.reidentified
  const conds = e3.conditions.clean.map((x) => x.condition)
  const relabel = (s: string) => s.replace(' (upper bound, not releasable)', ' (not releasable)')
  const dp = e2.dp?.rows.filter((x) => x.epsilon != null) ?? []
  const bank = r.e7?.bank_test2?.['our full detector'] as Metrics | undefined
  const held = r.e7?.heldout
  const task = r.e8?.rows ?? []
  const taskGreen = task.find((x) => x.release === 'GREEN policy, real detector')

  return (
    <div className="flex max-w-7xl flex-col gap-5">
      <header className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-xl font-semibold tracking-tight">What the redaction catches, what each tier sees, what still leaks</h2>
          <span className="badge badge-ghost badge-sm"><LockKeyhole size={12} aria-hidden="true" />Read-only · experiment outputs</span>
        </div>
        <p className="max-w-3xl text-sm text-base-content/70">
          The full detector finds {pct(full('clean').harm_weighted_recall)} of harm-weighted PII in clean transcripts and {pct(full('noisy').harm_weighted_recall)} in
          ASR-style text. GREEN shows none of it as is, and with the k-anonymity gate {pct(reid('clean', 'GREEN + k-anonymity gate') ?? 0)} of clients can be linked back.
        </p>
        <div role="note" className="alert alert-soft alert-warning text-sm">
          <Info size={16} aria-hidden="true" />
          <span>
            Synthetic numbers overstate real performance. The 24 hand-written calls have been tuned against, so their {pct(dev.harm_weighted_recall)} is not a held-out result.
            {bank ? <> On {r.e7!.bank_test2!.n_calls} real role-played bank calls the team did not write, labelled and frozen before scoring, recall is <strong>{pct(bank.harm_weighted_recall)}</strong>.</> : ' No real-speech result yet.'}
          </span>
        </div>
      </header>

      <div className="stats stats-vertical w-full border border-base-300 bg-base-100 md:stats-horizontal [&_.stat-desc]:whitespace-normal">
        {sets.map(([name, x]) => (
          <div key={name} className="stat">
            <div className="stat-title">Recall · {name}</div>
            <div className="stat-value text-2xl tabular-nums">{pct(x.harm_weighted_recall)}</div>
            <div className="stat-desc">Harm-weighted; entity-level {x.entity_recall == null ? '—' : pct(x.entity_recall)}</div>
          </div>
        ))}
        <div className="stat">
          <div className="stat-title">Re-identified from GREEN</div>
          <div className="stat-value text-2xl tabular-nums">{pct(reid('clean', 'GREEN + k-anonymity gate') ?? 0)}</div>
          <div className="stat-desc">With the k = 5 gate; {pct(reid('clean', 'raw transcript') ?? 0)} from raw text</div>
        </div>
        {bank && (
          <div className="stat">
            <div className="stat-title">Recall · real bank calls</div>
            <div className="stat-value text-2xl tabular-nums">{pct(bank.harm_weighted_recall)}</div>
            <div className="stat-desc">Held out, {r.e7!.bank_test2!.n_spans} labelled spans; {pct(r.e7!.bank_test2!.gliner_review?.rules.recall_after_review ?? 0)} after review</div>
          </div>
        )}
        {taskGreen ? (
          <div className="stat">
            <div className="stat-title">Task: recogniser adapted on GREEN</div>
            <div className="stat-value text-2xl tabular-nums">{pct(taskGreen.wer)}</div>
            <div className="stat-desc">Word error rate; {pct(task.find((x) => x.release.startsWith('Whisper'))?.wer ?? 0)} unadapted, {pct(task.find((x) => x.release.startsWith('raw'))?.wer ?? 0)} adapted on raw</div>
          </div>
        ) : (
          <div className="stat">
            <div className="stat-title">Perplexity, model on GREEN</div>
            <div className="stat-value text-2xl tabular-nums">{green == null ? '—' : num(green)}</div>
            <div className="stat-desc">{raw == null ? '' : `${num(raw)} on raw text`}; lower is better</div>
          </div>
        )}
      </div>

      <h2 className="flex items-center gap-2 text-base font-semibold"><ScanSearch size={18} aria-hidden="true" />Detection: how much sensitive data is found</h2>
      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title="What each detection layer adds" note="Harm-weighted recall as layers are added. A missed OTP weighs ten times a missed town. The spoken-number layer is what rescues ASR text.">
          <Bars label="Recall by detection layer" labels={layers.map((x) => x.config)} fmt={pct} max={1}
            series={(['clean', 'noisy'] as const).map((m) => ({ name: m === 'clean' ? 'Clean transcripts' : 'ASR-style',
              values: layers.map((l) => e1.ablation[m].find((x) => x.config === l.config)?.harm_weighted_recall ?? null) }))} />
        </Panel>
        <Panel title="Recall by kind of data" note="Full detector. Credentials and identifiers are near complete; quasi-identifiers and sensitive attributes on the hand-written calls are the gap.">
          <Bars label="Recall by data class" labels={classes.map(([, l]) => l)} fmt={pct} max={1}
            series={sets.map(([name, x]) => ({ name, values: classes.map(([c]) => x.recall[c]) }))} />
        </Panel>
        <Panel title="Our detector against the baselines" note="On the 24 hand-written calls. Adding GLiNER-PII raises recall but halves precision, so it is not used to redact.">
          <Bars label="Detectors on the dev set" labels={devDet.map(([, l]) => l)} fmt={pct} max={1}
            series={[{ name: 'Harm-weighted recall', values: devDet.map(([k]) => (e1.ood[k] as Metrics).harm_weighted_recall) },
              { name: 'Precision', values: devDet.map(([k]) => (e1.ood[k] as Metrics).precision) }]} />
        </Panel>
        {gr && (
          <Panel title="GLiNER as a review signal instead" note="A held call waits for a RED reviewer before GREEN release. GLiNER lifts recall of what goes out unreviewed, but holds most calls, so it is off by default.">
            <Bars label="Review queue on the dev set" labels={['Rule signals', 'Rules + GLiNER']} fmt={pct} max={1}
              series={[{ name: 'Recall of what goes out unreviewed', values: [gr.rules.recall_after_review, gr['with GLiNER'].recall_after_review] },
                { name: 'Calls held for review', values: [gr.rules.queued, gr['with GLiNER'].queued] }]} />
          </Panel>
        )}
      </div>

      {e1.tier_actions && (
        <>
          <h2 className="flex items-center gap-2 text-base font-semibold"><ShieldCheck size={18} aria-hidden="true" />Anonymisation: what each tier does to the PII it finds</h2>
          <Panel title="Treatment of detected PII by clearance tier" note="Every detected span in 500 ASR-style calls, rendered for each tier. Credentials are suppressed everywhere, RED included.">
            <TierStrips counts={e1.tier_actions.noisy} />
            <div className="max-w-full overflow-x-auto">
              <table className="table table-xs tabular-nums">
                <caption className="sr-only">Detected spans per tier and action</caption>
                <thead><tr><th>Action</th>{(['RED', 'AMBER', 'GREEN'] as Tier[]).map((t) => <th key={t} className="text-right">{t}</th>)}</tr></thead>
                <tbody>
                  {ACTIONS.map(([a, l]) => (
                    <tr key={a}><td>{l}</td>{(['RED', 'AMBER', 'GREEN'] as Tier[]).map((t) => (
                      <td key={t} className="text-right">{(e1.tier_actions!.noisy[t]?.[a] ?? 0).toLocaleString('en')}</td>))}</tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </>
      )}

      {(bank || task.length > 0) && (
        <>
          <h2 className="flex items-center gap-2 text-base font-semibold"><Mic size={18} aria-hidden="true" />Real speech, and the training flow itself</h2>
          <div className="grid gap-4 xl:grid-cols-2">
            {task.length > 0 && (
              <Panel title="Does GREEN still serve the training flow? Adapting the speech recogniser" note={`A language model trained on each release re-ranks Whisper's five best guesses; word error rate on ${r.e8!.test_calls} test calls. Lower is better; a perfect re-ranking would reach ${pct(r.e8!.oracle_wer)}. GREEN keeps most of what raw data gains; blacking out loses more.`}>
                <Bars label="Word error rate by training release" labels={task.map((x) => relabel(x.release))} fmt={pct}
                  series={[{ name: 'Word error rate', values: task.map((x) => x.wer) }]} />
              </Panel>
            )}
            {bank && (
              <Panel title="Synthetic calls against real bank calls" note="Harm-weighted recall. The real calls are role-played NSC Part 6 bank calls nobody on the team wrote, labelled by hand and frozen before scoring. The gap is the honest measure of what synthetic data hides.">
                <Bars label="Recall, synthetic against real" max={1} fmt={pct}
                  labels={['Synthetic, clean', 'Synthetic, ASR-style', 'Real bank calls', 'Real bank calls, after review']}
                  series={[{ name: 'Harm-weighted recall', values: [full('clean').harm_weighted_recall, full('noisy').harm_weighted_recall, bank.harm_weighted_recall,
                    r.e7!.bank_test2!.gliner_review?.rules.recall_after_review ?? null] }]} />
              </Panel>
            )}
            {held?.before.precision != null && held.after.precision != null && (
              <Panel title="False alarms on real conversation, before and after the fixes" note={`${held.clips.toLocaleString('en')} held-out NSC clips frozen before the fixes; 100 detections per detector judged blind${held.judge ? ` by ${held.judge}` : ''}.`}>
                <Bars label="Precision and words rewritten, before and after" labels={['Precision (judged)', 'Words rewritten at GREEN']} fmt={pct} max={1}
                  series={[{ name: 'Before', values: [held.before.precision, held.before.words_redacted_at_green] },
                    { name: 'After', values: [held.after.precision, held.after.words_redacted_at_green] }]} />
              </Panel>
            )}
          </div>
        </>
      )}

      <h2 className="flex items-center gap-2 text-base font-semibold"><Bird size={18} aria-hidden="true" />The GREEN release: what it is still good for, and what it still leaks</h2>
      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title="Does a model trained on the release learn real calls?" note="Bigram language model trained on each release, tested on 100 real (unredacted) calls. Lower is better. Fakes keep most of the value that blacking out destroys.">
          <Bars label="Perplexity by release" labels={e2.variants.map((x) => relabel(x.variant))} fmt={(n) => num(n)}
            series={[{ name: 'Test perplexity', values: e2.variants.map((x) => x.perplexity) }]} />
        </Panel>
        {dp.length > 0 && (
          <Panel title="Differential privacy at this scale" note={`The same model from user-level private counts over ${e2.dp!.n_clients} clients. Even at ε = 8 the noise destroys it; GREEN is about ${green == null ? '—' : num(green, 0)}.`}>
            <Bars label="Perplexity under differential privacy" labels={dp.map((x) => `${relabel(x.text)} · ε = ${x.epsilon}`)} fmt={(n) => num(n, 0)}
              series={[{ name: 'Test perplexity', values: dp.map((x) => x.perplexity) }]} />
          </Panel>
        )}
        <Panel title="Can an attacker link a call back to a client?" note="Linkage attack with a 300-client side table; the insider also holds the bank's transaction log.">
          <Bars label="Re-identification by release" labels={conds} fmt={pct} max={1}
            series={(['clean', 'noisy'] as const).map((m) => ({ name: m === 'clean' ? 'Clean transcripts' : 'ASR-style', values: conds.map((c) => reid(m, c) ?? null) }))} />
        </Panel>
        {e6 && (
          <Panel title="Does the trained model memorise planted identifiers?" note={`Exposure in bits: about 1 (dashed) is chance, ${num(e6.max_exposure)} means the model ranks the planted secret first of ${e6.candidates.toLocaleString('en')}. A secret the detector misses is memorised from GREEN too, unless the review queue holds its calls.`}>
            <Canaries e6={e6} />
          </Panel>
        )}
      </div>
    </div>
  )
}
