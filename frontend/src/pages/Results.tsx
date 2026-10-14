import { FlaskConical, Terminal } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from '../api'

type Metrics = { harm_weighted_recall: number; entity_recall?: number; strict_recall: number; char_leakage: number; precision: number; over_redaction: number; token_f1: number | null; recall: Record<string, number | null> }
type E1Row = Metrics & { config: string }
type Review = { queued: number; calls_with_harmful_miss: number; harmful_miss_calls_caught: number | null; leakage_removed_by_review: number | null }
type Triage = { accuracy: number; high_risk_recall: number; high_risk_recall_exact_ci?: [number, number] }
type ReviewQ = Review & { recall_after_review: number; recall_after_review_ci: [number, number] }
type GlinerReview = { n_calls: number; rules: ReviewQ; 'with GLiNER': ReviewQ; paired: { diff: number; ci: [number, number]; p: number } }
type HeldOutBlock = {
  n_calls: number; n_spans: number; ci: [number, number]; entity_ci?: [number, number]; review: Review; triage: Triage
  misses: { call: string; type: string; text: string }[]; gliner_review?: GlinerReview
} & Record<string, unknown>
type E6Row = { kind: string; frame: string; reps: number; detected: number; held: number; exposure: Record<string, number> }
type AnnexD = { threshold: Record<string, number>; harm: string; controls: string; motivation: string; p_attempt: Record<string, Record<string, number>> }
type E2Row = { variant: string; perplexity: number; pii_perplexity: number; pii_oov: number; digit_shape_preserved: number }
type TaskRow = { variant: string; synthetic_accuracy: number; synthetic_high_recall: number; 'held-out_accuracy': number; 'held-out_high_recall': number }
type E3Row = { condition: string; reidentified: number; ci: [number, number]; true_client_in_candidates: number; median_candidates: number; direct_id_leak: number }
type Results = {
  e1?: {
    n_calls: number; ablation: Record<'clean' | 'noisy', E1Row[]>
    ci: Record<'clean' | 'noisy', Record<string, [number, number]>>
    seeds: Record<'clean' | 'noisy', { values: number[]; mean: number; sd: number }>
    review: Record<'clean' | 'noisy', Review>; triage: Record<'clean' | 'noisy', Triage>
    gliner: Partial<Record<'clean' | 'noisy', Record<string, Metrics | number>>>
    ood: HeldOutBlock; independent?: HeldOutBlock
  }
  e2?: {
    n_train: number; n_test: number; model: string; variants: E2Row[]; task?: { model: string; rows: TaskRow[] }
    dp?: { cap: number; delta: number; n_clients: number; rows: { text: string; epsilon: number | null; perplexity: number }[] }
  }
  e3?: { n_clients: number; k: number; conditions: Record<'clean' | 'noisy', E3Row[]>; k_anonymity: Record<'clean' | 'noisy', { calls_below_k: number; median_k: number; gated: number }> }
  e4?: {
    n_calls: number; n_utterances: number; voices: string[]; asr_model: string; wer: number; spans_total: number; spans_dropped_by_asr: number
    detectors: Record<string, Metrics>; audio?: { recoverable_before_bleep: number; recoverable_after_bleep: number; audio_bleeped: number }
  }
  e5?: Record<string, number>
  e6?: { n_train: number; candidates: number; max_exposure: number; releases: string[]; rows: E6Row[] }
  e7?: {
    source: string; parts: E7Part[]
    heldout?: { clips: number; words: number; judge?: string; before: E7Judged; after: E7Judged } | null
    bank_dev?: HeldOutBlock; bank_test2?: HeldOutBlock & { 'round 5 vs round 4'?: Paired }
  }
  e8?: {
    n_calls: number; dev_calls: number; test_calls: number; n_best: number; asr_model: string; n_train_calls: number; lm: string
    oracle_wer: number; green_vs_raw: Paired
    rows: { release: string; lambda: number; wer: number; ci: [number, number]; wer_reduction_vs_whisper?: Paired }[]
  }
}
type Paired = { diff: number; ci: [number, number]; p: number }
type E7Part = { part: number; label: string; clips: number; words: number; detections_per_1000_words: number; words_redacted_at_green: number; held_for_review: number; triaged_high: number }
type E7Judged = { detections_per_1000_words: number; words_redacted_at_green: number; judged?: number; correct?: number; precision?: number; precision_ci?: [number, number] }
const pts = (d: Paired) => `${d.diff >= 0 ? '+' : ''}${(d.diff * 100).toFixed(1)} points (${(d.ci[0] * 100).toFixed(1)} to ${(d.ci[1] * 100).toFixed(1)})`

const ci = (v?: [number, number]) => (v ? `${pct(v[0])}–${pct(v[1])}` : '—')

function MetricTable({ rows }: { rows: [string, Metrics][] }) {
  return (
    <div className="max-w-full overflow-x-auto"><table className="table table-xs tabular-nums">
      <thead><tr><th>Detector</th><th>Recall (harm-wtd)</th><th>Entity recall</th><th>Strict recall</th><th>Char leakage</th><th>Precision</th><th>Token F1</th><th>Over-redaction</th></tr></thead>
      <tbody>{rows.map(([name, x]) => (
        <tr key={name}><td>{name}</td><td>{pct(x.harm_weighted_recall)}</td><td>{x.entity_recall == null ? '—' : pct(x.entity_recall)}</td><td>{pct(x.strict_recall)}</td><td>{pct(x.char_leakage)}</td><td>{pct(x.precision)}</td><td>{x.token_f1 == null ? '—' : pct(x.token_f1)}</td><td>{pct(x.over_redaction)}</td></tr>
      ))}</tbody>
    </table></div>
  )
}

function Panel({ title, question, children }: { title: string; question: string; children: React.ReactNode }) {
  return (
    <section className="card card-border min-w-0 border-base-300 bg-base-100">
      <div className="card-body min-w-0 gap-2 p-4">
        <h2 className="card-title text-base">{title}</h2>
        <p className="text-sm text-base-content/70">{question}</p>
        {children}
      </div>
    </section>
  )
}

// Validated with the dataviz palette checker (light surface): blue, orange.
const SERIES = ['#2a78d6', '#eb6834']
const pct = (v: number) => `${(v * 100).toFixed(1)}%`

/** Horizontal bars, one group per label, one bar per series; every value is printed. */
function Bars({ labels, series, fmt, max }: { labels: string[]; series: { name: string; data: number[] }[]; fmt: (v: number) => string; max?: number }) {
  const top = max ?? Math.max(...series.flatMap((s) => s.data))
  return (
    <div className="flex flex-col gap-2 text-xs">
      {series.length > 1 && (
        <div className="flex flex-wrap gap-3">
          {series.map((s, j) => (
            <span key={s.name} className="inline-flex items-center gap-1">
              <span className="size-2.5 rounded-sm" style={{ background: SERIES[j] }} />{s.name}
            </span>
          ))}
        </div>
      )}
      {labels.map((label, i) => (
        <div key={label} className="grid grid-cols-[minmax(0,40%)_1fr] items-center gap-2">
          <span>{label}</span>
          <div className="flex flex-col gap-0.5">
            {series.map((s, j) => (
              <div key={s.name} className="flex items-center gap-1.5">
                <div className="h-2.5 flex-1">
                  <div className="h-full rounded-r-sm" style={{ width: `${(s.data[i] / top) * 100}%`, background: SERIES[j] }} />
                </div>
                <span className="w-12 text-right tabular-nums text-base-content/70">{fmt(s.data[i])}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

function Figure({ title, question, children, table }: { title: string; question: string; children: React.ReactNode; table: React.ReactNode }) {
  return (
    <Panel title={title} question={question}>
      {children}
      <details className="text-sm">
        <summary className="cursor-pointer text-xs text-base-content/70">Show as table</summary>
        <div className="mt-2">{table}</div>
      </details>
    </Panel>
  )
}

function HeldOut({ title, question, o }: { title: string; question: string; o: HeldOutBlock }) {
  const g = o.gliner_review
  return (
    <Panel title={title} question={`${question} 95% CI of the full detector: ${ci(o.ci)} (harm-weighted), ${ci(o.entity_ci)} (entity). ${o.triage.high_risk_recall_exact_ci?.[0] == null ? 'No high-risk call in this set, so triage is not tested.' : `Triage high-risk recall ${pct(o.triage.high_risk_recall)}, exact CI ${ci(o.triage.high_risk_recall_exact_ci)}.`}`}>
      <MetricTable rows={(['presidio only', 'round-4 detector (first score)', 'round-4 detector', 'our full detector', 'GLiNER-PII alone', 'full + GLiNER'] as const)
        .filter((k) => o[k]).map((k) => [k, o[k] as Metrics])} />
      {g && (
        <div className="max-w-full overflow-x-auto"><table className="table table-xs tabular-nums">
          <thead><tr><th>Review queue</th><th>Calls held</th><th>Recall of what reaches GREEN unreviewed</th></tr></thead>
          <tbody>{(['rules', 'with GLiNER'] as const).map((k) => (
            <tr key={k}><td>{k === 'rules' ? '3 rule signals' : '+ GLiNER as a review signal'}</td><td>{pct(g[k].queued)}</td><td>{pct(g[k].recall_after_review)} ({ci(g[k].recall_after_review_ci)})</td></tr>
          ))}</tbody>
        </table></div>
      )}
      <details className="text-sm">
        <summary className="cursor-pointer text-xs text-base-content/70">Every miss ({o.misses.length})</summary>
        <ul className="mt-2 flex flex-col gap-1 text-xs">{o.misses.map((m, i) => <li key={i}><code className="font-mono">{m.type}</code> “{m.text}” ({m.call})</li>)}</ul>
      </details>
    </Panel>
  )
}

/** PDPC Guide to Basic Anonymisation, Annex D: risk = (1/k) × P(attempt) must stay under the harm threshold. */
function AnnexDPanel({ a, k, insider }: { a: AnnexD; k: number; insider?: number }) {
  const [controls, setControls] = useState(a.controls)
  const [motivation, setMotivation] = useState(a.motivation)
  const thr = a.threshold[a.harm]
  const p = a.p_attempt[controls][motivation]
  const need = Math.ceil(+(p / thr).toFixed(6))
  return (
    <Panel title="PDPC Annex D · What k do the bank's controls require?" question={`Risk = (1/k) × P(attempt) must stay at or below ${thr} (${a.harm} potential harm). Stronger controls lower an insider's P(attempt), so the gate needs a smaller k.`}>
      <div className="flex flex-wrap gap-3 text-sm">
        <label className="flex items-center gap-2">Mitigating controls
          <select className="select select-sm w-32" value={controls} onChange={(e) => setControls(e.target.value)}>
            {Object.keys(a.p_attempt).map((c) => <option key={c}>{c}</option>)}
          </select>
        </label>
        <label className="flex items-center gap-2">Attacker motivation
          <select className="select select-sm w-32" value={motivation} onChange={(e) => setMotivation(e.target.value)}>
            {Object.keys(a.p_attempt[controls]).map((m) => <option key={m}>{m}</option>)}
          </select>
        </label>
      </div>
      <div className="stats stats-vertical border border-base-300 sm:stats-horizontal">
        <div className="stat"><div className="stat-title">P(attempt)</div><div className="stat-value text-xl tabular-nums">{p}</div></div>
        <div className="stat"><div className="stat-title">Required k</div><div className="stat-value text-xl tabular-nums">{need}</div>
          <div className={need <= k ? 'stat-desc text-success' : 'stat-desc text-error'}>{need <= k ? `the export gate's k = ${k} meets it` : `the export gate's k = ${k} is too small`}</div></div>
        {insider != null && <div className="stat"><div className="stat-title">Measured insider risk</div><div className="stat-value text-xl tabular-nums">{pct(insider * p)}</div>
          <div className="stat-desc">{pct(insider)} linkage (E3, with the gate) × P(attempt); our reading of the guide</div></div>}
      </div>
    </Panel>
  )
}

export default function Results() {
  const [r, setR] = useState<Results | null>(null)
  const [annex, setAnnex] = useState<{ a: AnnexD; k: number } | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api<Results>('/api/results').then(setR).catch((e) => setError(e.message))
    api<{ release: { k: number; annex_d?: AnnexD } }>('/api/taxonomy')
      .then((t) => t.release.annex_d && setAnnex({ a: t.release.annex_d, k: t.release.k })).catch(() => {})
  }, [])

  if (error) return <div role="alert" className="alert alert-soft alert-error text-sm">{error}</div>
  if (!r) return <div className="grid gap-4 xl:grid-cols-2"><div className="skeleton h-80" /><div className="skeleton h-80" /></div>
  if (!r.e1 && !r.e2 && !r.e3) {
    return (
      <div role="status" className="alert alert-soft max-w-2xl">
        <FlaskConical size={18} aria-hidden="true" />
        <div>
          <h2 className="font-semibold">No experiment results on this server yet</h2>
          <p className="text-sm">Generate them once (about 5 minutes on a laptop CPU), then reload:</p>
          <code className="mt-1 inline-flex items-center gap-1 font-mono text-xs"><Terminal size={12} aria-hidden="true" />cd backend && .venv/bin/python -m experiments.run</code>
        </div>
      </div>
    )
  }

  const full = (m: 'clean' | 'noisy') => r.e1?.ablation[m].find((x) => x.config.includes('full'))
  const policy = r.e3?.conditions.noisy.find((x) => x.condition === 'GREEN policy')
  const raw = r.e2?.variants.find((v) => v.variant.startsWith('raw'))
  const green = r.e2?.variants.find((v) => v.variant === 'GREEN policy')
  const blackout = r.e2?.variants.find((v) => v.variant === 'suppress all')

  return (
    <div className="flex flex-col gap-4">
      <div className="stats stats-vertical w-full border border-base-300 bg-base-100 md:stats-horizontal">
        <div className="stat">
          <div className="stat-title">Harm-weighted recall, ASR text</div>
          <div className="stat-value text-2xl tabular-nums">{full('noisy') ? pct(full('noisy')!.harm_weighted_recall) : '—'}</div>
          <div className="stat-desc">95% CI {ci(r.e1?.ci?.noisy?.['+ propagate (full)'])}; clean {full('clean') ? pct(full('clean')!.harm_weighted_recall) : '—'}; {r.e1?.independent ? `independent held-out ${pct((r.e1.independent['our full detector'] as Metrics).harm_weighted_recall)}` : `24-call dev set ${r.e1?.ood ? pct((r.e1.ood['our full detector'] as Metrics).harm_weighted_recall) : '—'} (tuned against)`}</div>
        </div>
        <div className="stat">
          <div className="stat-title">Model trained on GREEN, tested on real calls</div>
          <div className="stat-value text-2xl tabular-nums">{green?.perplexity ?? '—'}</div>
          <div className="stat-desc">Perplexity; {raw?.perplexity ?? '—'} if trained on raw, {blackout?.perplexity ?? '—'} if PII is blacked out</div>
        </div>
        <div className="stat">
          <div className="stat-title">Clients re-identified from GREEN</div>
          <div className="stat-value text-2xl tabular-nums">{policy ? pct(policy.reidentified) : '—'}</div>
          <div className="stat-desc">95% CI {ci(policy?.ci)}; linkage attack with a {r.e3?.n_clients ?? '—'}-client side table</div>
        </div>
      </div>

      <div className="grid gap-4 2xl:grid-cols-2">
        {r.e1 && (
          <Figure title="E1 · What each detection layer adds" question={`Harm-weighted recall over ${r.e1.n_calls} calls. A missed OTP weighs 10× a missed town name.`}
            table={
              <div className="max-w-full overflow-x-auto"><table className="table table-xs tabular-nums">
                <thead><tr><th>Layers</th><th>Corpus</th><th>Recall (harm-wtd)</th><th>Char leakage</th><th>Precision</th><th>Over-redaction</th></tr></thead>
                <tbody>{(['clean', 'noisy'] as const).flatMap((m) => r.e1!.ablation[m].map((x) => (
                  <tr key={m + x.config}><td>{x.config}</td><td>{m === 'noisy' ? 'ASR' : 'clean'}</td><td>{pct(x.harm_weighted_recall)}</td><td>{pct(x.char_leakage)}</td><td>{pct(x.precision)}</td><td>{pct(x.over_redaction)}</td></tr>
                )))}</tbody>
              </table></div>
            }>
            <Bars labels={r.e1.ablation.clean.map((x) => x.config)} fmt={pct} max={1}
              series={[
                { name: 'Clean transcripts', data: r.e1.ablation.clean.map((x) => x.harm_weighted_recall) },
                { name: 'ASR output', data: r.e1.ablation.noisy.map((x) => x.harm_weighted_recall) },
              ]} />
          </Figure>
        )}

        {r.e2 && (
          <Figure title="E2 · Does training on the GREEN release transfer to real calls?" question={`Word-bigram model trained on ${r.e2.n_train} released calls, scored on ${r.e2.n_test} held-out unredacted calls. Lower is better; blacking out PII leaves the model unable to predict real call text.`}
            table={
              <div className="max-w-full overflow-x-auto"><table className="table table-xs tabular-nums">
                <thead><tr><th>Training corpus</th><th>Test perplexity</th><th>PII-token perplexity</th><th>PII-token OOV</th><th>Digit shape preserved</th></tr></thead>
                <tbody>{r.e2.variants.map((v) => <tr key={v.variant}><td>{v.variant}</td><td>{v.perplexity}</td><td>{v.pii_perplexity}</td><td>{pct(v.pii_oov)}</td><td>{pct(v.digit_shape_preserved)}</td></tr>)}</tbody>
              </table></div>
            }>
            <Bars labels={r.e2.variants.map((v) => v.variant)} fmt={(v) => v.toFixed(0)}
              series={[{ name: 'Test perplexity', data: r.e2.variants.map((v) => v.perplexity) }]} />
          </Figure>
        )}

        {r.e2?.task && (
          <Panel title="E2 · A downstream task: learning the high-risk triage from each release" question={`${r.e2.task.model}. Trained on each release, tested on unredacted synthetic calls and on the 24-call hand-written development set. The last row is the rule-based triage the service runs at ingest.`}>
            <div className="max-w-full overflow-x-auto"><table className="table table-xs tabular-nums">
              <thead><tr><th>Training corpus</th><th>Synthetic accuracy</th><th>Synthetic high-risk recall</th><th>Dev-set accuracy</th><th>Dev-set high-risk recall</th></tr></thead>
              <tbody>{r.e2.task.rows.map((x) => <tr key={x.variant}><td>{x.variant}</td><td>{pct(x.synthetic_accuracy)}</td><td>{pct(x.synthetic_high_recall)}</td><td>{pct(x['held-out_accuracy'])}</td><td>{pct(x['held-out_high_recall'])}</td></tr>)}</tbody>
            </table></div>
          </Panel>
        )}

        {r.e3 && (
          <Figure title="E3 · Can an adversary link a transcript back to a client?" question="Share of calls re-identified uniquely using name, branch, employer, occupation and nationality.
            The adversary knows our generalization scheme."
            table={
              <div className="max-w-full overflow-x-auto"><table className="table table-xs tabular-nums">
                <thead><tr><th>Release</th><th>Corpus</th><th>Re-identified</th><th>True client in candidates</th><th>Median candidates</th><th>Direct-ID leak</th></tr></thead>
                <tbody>{(['clean', 'noisy'] as const).flatMap((m) => r.e3!.conditions[m].map((x) => (
                  <tr key={m + x.condition}><td>{x.condition}</td><td>{m === 'noisy' ? 'ASR' : 'clean'}</td><td>{pct(x.reidentified)}</td><td>{pct(x.true_client_in_candidates)}</td><td>{x.median_candidates}</td><td>{pct(x.direct_id_leak)}</td></tr>
                )))}</tbody>
              </table></div>
            }>
            <Bars labels={r.e3.conditions.clean.map((x) => x.condition)} fmt={pct} max={1}
              series={[
                { name: 'Clean transcripts', data: r.e3.conditions.clean.map((x) => x.reidentified) },
                { name: 'ASR output', data: r.e3.conditions.noisy.map((x) => x.reidentified) },
              ]} />
          </Figure>
        )}

        {r.e1?.independent && (
          <HeldOut title="E1 · Independent held-out calls" o={r.e1.independent}
            question={`${r.e1.independent.n_calls} calls (${r.e1.independent.n_spans} spans) written outside the team, hashed before scoring.`} />
        )}
        {r.e1?.ood && (
          <HeldOut title="E1 · Development set (24 hand-written calls)" o={r.e1.ood}
            question={`${r.e1.ood.n_calls} calls (${r.e1.ood.n_spans} spans) the team wrote after the first detector. Later rounds fixed gaps found here, so these numbers are tuned, not held out.`} />
        )}

        {r.e8 && (
          <Panel title="E8 · The task itself: adapting the speech recogniser on each release" question={`${r.e8.asr_model} gives its ${r.e8.n_best} best guesses for each utterance of the ${r.e8.n_calls} E4 calls; an ${r.e8.lm} LM trained on ${r.e8.n_train_calls} other calls, in each released form, re-ranks them. LM weight chosen on ${r.e8.dev_calls} calls; word error rate on the other ${r.e8.test_calls}. Lower is better; perfect re-ranking would reach ${pct(r.e8.oracle_wer)}. GREEN (real detector) against raw, paired by call: ${pts(r.e8.green_vs_raw)} of word accuracy.`}>
            <div className="max-w-full overflow-x-auto"><table className="table table-xs tabular-nums">
              <thead><tr><th>LM trained on</th><th>LM weight</th><th>Word error rate</th><th>95% CI</th><th>Fewer errors than Whisper alone</th></tr></thead>
              <tbody>{r.e8.rows.map((x) => (
                <tr key={x.release}><td>{x.release}</td><td>{x.lambda}</td><td>{pct(x.wer)}</td><td>{ci(x.ci)}</td>
                  <td>{x.wer_reduction_vs_whisper ? `${pts(x.wer_reduction_vs_whisper)}, p = ${x.wer_reduction_vs_whisper.p.toFixed(3)}` : '—'}</td></tr>
              ))}</tbody>
            </table></div>
          </Panel>
        )}

        {r.e7?.bank_test2 && (
          <HeldOut title="E7 · Real bank calls the team did not write (held out)" o={r.e7.bank_test2}
            question={`${r.e7.bank_test2.n_calls} role-played bank calls from the NSC Part 6 training split (${r.e7.bank_test2.n_spans} spans), labelled by hand after the round-5 fixes were final, frozen by hash and scored once.${r.e7.bank_test2['round 5 vs round 4'] ? ` Round 5 against round 4: ${pts(r.e7.bank_test2['round 5 vs round 4'])}.` : ''}`} />
        )}
        {r.e7?.bank_dev && (
          <HeldOut title="E7 · Real bank calls, development batch" o={r.e7.bank_dev}
            question={`${r.e7.bank_dev.n_calls} more labelled calls (${r.e7.bank_dev.n_spans} spans). Scored once by the round-4 detector while unseen, then used to design the round-5 fixes, so the current rows are tuned against.`} />
        )}
        {r.e7 && (
          <Panel title="E7 · Real Singapore speech: what the pipeline does to real conversation" question={`Reference transcripts from ${r.e7.source}, no PII labels: these columns show behaviour, not recall.`}>
            <div className="max-w-full overflow-x-auto"><table className="table table-xs tabular-nums">
              <thead><tr><th>NSC part</th><th>Clips</th><th>Detections / 1,000 words</th><th>Words rewritten at GREEN</th><th>Held for review</th><th>Triaged high risk</th></tr></thead>
              <tbody>{r.e7.parts.map((x) => (
                <tr key={x.part}><td>{x.part}. {x.label}</td><td>{x.clips.toLocaleString('en')}</td><td>{x.detections_per_1000_words}</td><td>{pct(x.words_redacted_at_green)}</td><td>{pct(x.held_for_review)}</td><td>{pct(x.triaged_high)}</td></tr>
              ))}</tbody>
            </table></div>
            {r.e7.heldout && (
              <div className="max-w-full overflow-x-auto"><table className="table table-xs tabular-nums">
                <caption className="text-left text-xs text-base-content/70">
                  {r.e7.heldout.clips.toLocaleString('en')} held-out clips frozen before the round-4 false-alarm fixes; detections judged blind{r.e7.heldout.judge ? ` by ${r.e7.heldout.judge}` : ''}.
                </caption>
                <thead><tr><th>Detector</th><th>Detections / 1,000 words</th><th>Words rewritten at GREEN</th><th>Precision (judged)</th></tr></thead>
                <tbody>{(['before', 'after'] as const).map((k) => {
                  const x = r.e7!.heldout![k]
                  return <tr key={k}><td>{k === 'before' ? 'Before the fixes' : 'After'}</td><td>{x.detections_per_1000_words}</td><td>{pct(x.words_redacted_at_green)}</td>
                    <td>{x.precision == null ? '—' : `${x.correct}/${x.judged} = ${pct(x.precision)} (${ci(x.precision_ci)})`}</td></tr>
                })}</tbody>
              </table></div>
            )}
          </Panel>
        )}

        {r.e6 && (
          <Panel title="E6 · Does a model trained on the release memorise planted identifiers?" question={`Canaries planted in ${r.e6.n_train} training calls. Exposure in bits: about 1 is chance, ${r.e6.max_exposure} means the model ranks the planted secret first of ${r.e6.candidates}. "Missed" canaries are formats the detector does not know.`}>
            <div className="max-w-full overflow-x-auto"><table className="table table-xs tabular-nums">
              <thead><tr><th>Canary</th><th>Repeats</th><th>Detected</th><th>Held for review</th>{r.e6.releases.map((n) => <th key={n}>{n}</th>)}</tr></thead>
              <tbody>{r.e6.rows.map((x) => (
                <tr key={`${x.kind}${x.frame}${x.reps}`}><td>{x.kind}, {x.frame}</td><td>{x.reps}</td><td>{pct(x.detected)}</td><td>{pct(x.held)}</td>
                  {r.e6!.releases.map((n) => <td key={n}>{x.exposure[n].toFixed(1)}</td>)}</tr>
              ))}</tbody>
            </table></div>
          </Panel>
        )}

        {r.e2?.dp && (
          <Panel title="E2-DP · Where differential privacy would sit" question={`User-level DP bigram: each of ${r.e2.dp.n_clients} clients contributes at most ${r.e2.dp.cap} words and ${r.e2.dp.cap} bigrams, then Laplace noise (δ = ${r.e2.dp.delta}). ε = ∞ is the cap without noise. Compare raw ${raw?.perplexity ?? '—'} and GREEN ${green?.perplexity ?? '—'}.`}>
            <div className="max-w-full overflow-x-auto"><table className="table table-xs tabular-nums">
              <thead><tr><th>Training text</th><th>ε</th><th>Test perplexity</th></tr></thead>
              <tbody>{r.e2.dp.rows.map((x) => <tr key={x.text + x.epsilon}><td>{x.text}</td><td>{x.epsilon ?? '∞'}</td><td>{x.perplexity}</td></tr>)}</tbody>
            </table></div>
          </Panel>
        )}

        {annex && r.e3 && (
          <AnnexDPanel a={annex.a} k={annex.k}
            insider={r.e3.conditions.clean.find((x) => x.condition.startsWith('GREEN + k-gate vs'))?.reidentified} />
        )}

        {r.e1 && (
          <Panel title="E1 · Baseline, seeds, review queue and triage" question="A local zero-shot PII model on the same calls; the detector on four more random corpora; whether held calls are the leaky ones; whether triage matches the ground truth.">
            {(['clean', 'noisy'] as const).filter((m) => r.e1!.gliner?.[m]).map((m) => (
              <div key={m}>
                <h3 className="text-xs font-medium">GLiNER-PII vs ours, {m === 'noisy' ? 'ASR' : 'clean'} ({r.e1!.gliner[m]!.n_calls as number} calls)</h3>
                <MetricTable rows={Object.entries(r.e1!.gliner[m]!).filter(([k]) => k !== 'n_calls') as [string, Metrics][]} />
              </div>
            ))}
            <div className="max-w-full overflow-x-auto"><table className="table table-xs tabular-nums">
              <thead><tr><th>Corpus</th><th>Recall over 5 seeds</th><th>Queued for review</th><th>Harmful-miss calls queued</th><th>Leakage removed by review</th><th>Triage accuracy</th></tr></thead>
              <tbody>
                {(['clean', 'noisy'] as const).map((m) => (
                  <tr key={m}><td>{m === 'noisy' ? 'ASR' : 'clean'}</td><td>{pct(r.e1!.seeds[m].mean)} ± {pct(r.e1!.seeds[m].sd)}</td><td>{pct(r.e1!.review[m].queued)}</td>
                    <td>{r.e1!.review[m].harmful_miss_calls_caught == null ? '—' : pct(r.e1!.review[m].harmful_miss_calls_caught!)}</td>
                    <td>{r.e1!.review[m].leakage_removed_by_review == null ? '—' : pct(r.e1!.review[m].leakage_removed_by_review!)}</td><td>{pct(r.e1!.triage[m].accuracy)}</td></tr>
                ))}
                <tr><td>dev set</td><td>—</td><td>{pct(r.e1.ood.review.queued)}</td>
                  <td>{r.e1.ood.review.harmful_miss_calls_caught == null ? '—' : pct(r.e1.ood.review.harmful_miss_calls_caught)}</td>
                  <td>{r.e1.ood.review.leakage_removed_by_review == null ? '—' : pct(r.e1.ood.review.leakage_removed_by_review)}</td><td>{pct(r.e1.ood.triage.accuracy)}</td></tr>
              </tbody>
            </table></div>
          </Panel>
        )}

        {r.e4 && (
          <Panel title="E4 · Real ASR errors: Singapore-English TTS → Whisper" question={`${r.e4.n_calls} calls (${r.e4.n_utterances} utterances) spoken by ${r.e4.voices.join(' and ')}, transcribed by ${r.e4.asr_model}. Word error rate ${pct(r.e4.wer)}; ${r.e4.spans_dropped_by_asr} of ${r.e4.spans_total} PII spans vanished in transcription.`}>
            <MetricTable rows={Object.entries(r.e4.detectors)} />
            {r.e4.audio && (
              <p className="text-sm">
                Audio redaction: bleeping detected words by Whisper's word timestamps leaves {pct(r.e4.audio.recoverable_after_bleep)} of PII values
                recoverable by re-transcription (from {pct(r.e4.audio.recoverable_before_bleep)}), bleeping {pct(r.e4.audio.audio_bleeped)} of the audio.
              </p>
            )}
          </Panel>
        )}

        {r.e5 && (
          <Panel title="E5 · What it costs" question="Per-call latency on a laptop CPU. CP-ABE pairings happen once per user and access policy; a page view is AES.">
            <div className="max-w-full overflow-x-auto"><table className="table table-xs tabular-nums">
              <tbody>{Object.entries(r.e5).filter(([k]) => k !== 'n_calls').map(([k, v]) => <tr key={k}><td>{k.replaceAll('_', ' ')}</td><td>{v} ms</td></tr>)}</tbody>
            </table></div>
          </Panel>
        )}
      </div>
    </div>
  )
}
