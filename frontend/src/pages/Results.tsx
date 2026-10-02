import type { ApexOptions } from 'apexcharts'
import { FlaskConical, Terminal } from 'lucide-react'
import { useEffect, useState } from 'react'
import Chart from 'react-apexcharts'
import { api } from '../api'

type E1Row = { config: string; harm_weighted_recall: number; char_leakage: number; precision: number; over_redaction: number; recall: Record<string, number | null> }
type E2Row = { variant: string; perplexity: number; pii_perplexity: number; pii_oov: number; digit_shape_preserved: number }
type E3Row = { condition: string; reidentified: number; true_client_in_candidates: number; median_candidates: number; direct_id_leak: number }
type Results = {
  e1?: { n_calls: number; ablation: Record<'clean' | 'noisy', E1Row[]> }
  e2?: { n_train: number; n_test: number; model: string; variants: E2Row[] }
  e3?: { n_clients: number; conditions: Record<'clean' | 'noisy', E3Row[]> }
}

// Validated with the dataviz palette checker (light surface): blue, orange.
const SERIES = ['#2a78d6', '#eb6834']
const SURFACE = '#fbfcfd'
const pct = (v: number) => `${(v * 100).toFixed(1)}%`
const pctAxis = (v: number) => `${Math.round(v * 100)}%`

function bars(categories: string[], fmt: (v: number) => string, max?: number, axisFmt = fmt): ApexOptions {
  return {
    chart: { type: 'bar', toolbar: { show: false }, fontFamily: 'IBM Plex Sans, sans-serif', animations: { enabled: false } },
    plotOptions: { bar: { horizontal: true, borderRadius: 4, borderRadiusApplication: 'end', barHeight: '70%' } },
    colors: SERIES,
    stroke: { show: true, width: 2, colors: [SURFACE] },
    dataLabels: { enabled: false },
    grid: { borderColor: 'oklch(91% 0.01 250)', strokeDashArray: 3, xaxis: { lines: { show: true } }, yaxis: { lines: { show: false } } },
    xaxis: { categories, min: 0, max, tickAmount: 4, labels: { formatter: (v: string) => axisFmt(Number(v)) } },
    yaxis: { labels: { maxWidth: 220, style: { fontSize: '12px' } } },
    legend: { position: 'top', horizontalAlign: 'left', fontSize: '12px' },
    tooltip: { shared: true, intersect: false, y: { formatter: (v: number) => fmt(v) } },
  }
}

function Figure({ title, question, children, table }: { title: string; question: string; children: React.ReactNode; table: React.ReactNode }) {
  return (
    <section className="card card-border min-w-0 border-base-300 bg-base-100">
      <div className="card-body min-w-0 gap-2 p-4">
        <h2 className="card-title text-base">{title}</h2>
        <p className="text-sm text-base-content/70">{question}</p>
        {children}
        <details className="text-sm">
          <summary className="cursor-pointer text-xs text-base-content/70">Show as table</summary>
          <div className="mt-2">{table}</div>
        </details>
      </div>
    </section>
  )
}

export default function Results() {
  const [r, setR] = useState<Results | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api<Results>('/api/results').then(setR).catch((e) => setError(e.message))
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
          <div className="stat-desc">Full detector; clean transcripts {full('clean') ? pct(full('clean')!.harm_weighted_recall) : '—'}</div>
        </div>
        <div className="stat">
          <div className="stat-title">Model trained on GREEN, tested on real calls</div>
          <div className="stat-value text-2xl tabular-nums">{green?.perplexity ?? '—'}</div>
          <div className="stat-desc">Perplexity; {raw?.perplexity ?? '—'} if trained on raw, {blackout?.perplexity ?? '—'} if PII is blacked out</div>
        </div>
        <div className="stat">
          <div className="stat-title">Clients re-identified from GREEN</div>
          <div className="stat-value text-2xl tabular-nums">{policy ? pct(policy.reidentified) : '—'}</div>
          <div className="stat-desc">Linkage attack with a {r.e3?.n_clients ?? '—'}-client side table</div>
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
            <Chart type="bar" height={320}
              options={bars(r.e1.ablation.clean.map((x) => x.config), pct, 1, pctAxis)}
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
            <Chart type="bar" height={320}
              options={{ ...bars(r.e2.variants.map((v) => v.variant), (v) => v.toFixed(0)), legend: { show: false } }}
              series={[{ name: 'Test perplexity', data: r.e2.variants.map((v) => v.perplexity) }]} />
          </Figure>
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
            <Chart type="bar" height={280}
              options={bars(r.e3.conditions.clean.map((x) => x.condition), pct, 1, pctAxis)}
              series={[
                { name: 'Clean transcripts', data: r.e3.conditions.clean.map((x) => x.reidentified) },
                { name: 'ASR output', data: r.e3.conditions.noisy.map((x) => x.reidentified) },
              ]} />
          </Figure>
        )}
      </div>
    </div>
  )
}
