import { ArrowRight, Check, Database, FileLock2, FlaskConical, Hourglass, KeyRound, ListChecks, Mic, Radio, ScanSearch, ScrollText, Split, Target as TargetIcon, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, ApiError, type Overview as OverviewData, type Target } from '../api'
import TierBadge from '../components/TierBadge'

function Section({ n, title, Icon, children }: { n: number; title: string; Icon: typeof Mic; children: React.ReactNode }) {
  return (
    <section className="card border border-base-300 bg-base-100" aria-labelledby={`req-${n}`}>
      <div className="card-body gap-3 p-4 md:p-5">
        <h2 id={`req-${n}`} className="flex items-center gap-2 text-base font-semibold">
          <span className="grid size-6 flex-none place-items-center rounded-full bg-primary text-xs text-primary-content">{n}</span>
          <Icon size={16} aria-hidden="true" />
          {title}
        </h2>
        {children}
      </div>
    </section>
  )
}

const Step = ({ title, text }: { title: string; text: string }) => (
  <div className="min-w-0 flex-1 rounded-box border border-base-300 p-3">
    <div className="text-sm font-medium">{title}</div>
    <div className="text-xs text-base-content/70">{text}</div>
  </div>
)

const Arrow = () => <ArrowRight size={16} aria-hidden="true" className="hidden flex-none self-center text-base-content/40 md:block" />

function Status({ t }: { t: Target }) {
  if (t.met === null) return <span className="badge badge-sm badge-ghost"><Hourglass size={12} aria-hidden="true" />Pending</span>
  return t.met
    ? <span className="badge badge-sm badge-soft badge-success"><Check size={12} aria-hidden="true" />Met</span>
    : <span className="badge badge-sm badge-soft badge-error"><X size={12} aria-hidden="true" />Not met</span>
}

function Targets({ rows, caption }: { rows: Target[]; caption: string }) {
  return (
    <div className="overflow-x-auto">
      <table className="table table-sm">
        <caption className="pb-1 text-left text-xs font-medium text-base-content/70">{caption}</caption>
        <thead>
          <tr><th>#</th><th>Requirement</th><th>Target</th><th>Result</th><th>Status</th></tr>
        </thead>
        <tbody>
          {rows.map((t, i) => (
            <tr key={i}>
              <td className="font-mono text-xs">{t.id}</td>
              <td className="min-w-56">
                {t.requirement}
                <div className="text-xs text-base-content/60">{t.kind === 'test' ? `Guaranteed by the code; checked by ${t.evidence}` : `Measured: ${t.evidence}`}</div>
              </td>
              <td className="whitespace-nowrap">{t.target}</td>
              <td className="font-mono text-xs">{t.value ?? '—'}</td>
              <td className="whitespace-nowrap"><Status t={t} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const PAGES = [
  { href: '#/live', label: 'Live anonymiser', Icon: Radio, text: 'Type or play a call; detection and all three tier renderings update per utterance.' },
  { href: '#/calls', label: 'Calls', Icon: FileLock2, text: 'Stored calls opened per clearance, break-glass, review hold, signed export, erasure.' },
  { href: '#/audit', label: 'Disclosure log', Icon: ScrollText, text: 'Every release in a Merkle log whose heads the key authority signs; receipts verify offline.' },
  { href: '#/policy', label: 'Redaction policy', Icon: ListChecks, text: 'The class × tier action matrix, loaded by the code from taxonomy.yaml.' },
  { href: '#/dashboard', label: 'Results dashboard', Icon: FlaskConical, text: 'What detection catches, what each tier sees, what still leaks.' },
]

export default function Overview() {
  const [data, setData] = useState<OverviewData | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api<OverviewData>('/api/overview')
      .then(setData)
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Could not load the results'))
  }, [])

  const measured = data?.targets.filter((t) => t.met !== null) ?? []
  const met = measured.filter((t) => t.met).length

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-4">
      <header className="px-1">
        <h2 className="text-xl font-semibold tracking-tight">Anonymising bank call transcripts so the bank can train its speech model on them</h2>
        <p className="mt-1 max-w-3xl text-sm text-base-content/70">
          The project in six steps, in the order of the brief. Each step links to the part of this prototype that shows it.
          All transcripts in the prototype are synthetic.
        </p>
      </header>

      <Section n={1} title="A realistic data analysis task" Icon={Mic}>
        <p className="text-sm">
          A Singapore bank&apos;s speech recogniser performs poorly on Singapore-accented English, Singlish and code-switching.
          To fix it, <strong>data scientists fine-tune it on transcripts of recorded client calls</strong>. They hold the lowest
          clearance, while the transcripts are banking-secrecy data that only compliance may read in full, and only for
          high-risk calls (fraud reports, large overseas transfers).
        </p>
        <div className="flex flex-col gap-2 md:flex-row">
          <Step title="Client call" text="Recorded; names, NRIC, card and account numbers, OTPs spoken aloud" />
          <Arrow />
          <Step title="ASR transcript" text="Raw speech-recognition text: digits as words, Singlish, errors" />
          <Arrow />
          <Step title="Quietline" text="Detect once, triage, render per clearance, encrypt each copy" />
          <Arrow />
          <div className="flex min-w-0 flex-1 flex-col gap-1 rounded-box border border-base-300 p-3 text-xs">
            <span className="flex items-center gap-2"><TierBadge tier="RED" /> Compliance: high-risk calls in full</span>
            <span className="flex items-center gap-2"><TierBadge tier="AMBER" /> Agent: own calls, masked</span>
            <span className="flex items-center gap-2"><TierBadge tier="GREEN" /> Data science: training set</span>
          </div>
        </div>
      </Section>

      <Section n={2} title="Privacy and utility requirements" Icon={TargetIcon}>
        <p className="text-sm">
          Each target was set before it was measured, with a source (regulation, the brief, or a stated team choice).
          Results below are read live from the latest experiment run.
          {data && <> <strong>{met} of {measured.length}</strong> targets are met; the ones that are not are the honest gaps.</>}
        </p>
        {error && <div role="alert" className="alert alert-error alert-soft text-sm">{error}</div>}
        {!data && !error && <span className="loading loading-spinner loading-sm" aria-label="Loading targets" />}
        {data && (
          <>
            <Targets caption="Privacy: what must never leak, and to whom" rows={data.targets.filter((t) => t.group === 'privacy')} />
            <Targets caption="Utility: what each reader must still be able to do" rows={data.targets.filter((t) => t.group === 'utility')} />
          </>
        )}
      </Section>

      <Section n={3} title="A privacy-preserving solution" Icon={Split}>
        <div className="flex flex-col gap-2 md:flex-row">
          <Step title="Detect" text="Six layers: NER, checksum-validated Singapore formats, cue phrases, spoken-number normaliser (English, Mandarin, Malay), dialogue slots, propagation" />
          <Arrow />
          <Step title="Triage and review" text="High-risk calls go to compliance; calls the detector is unsure about are held before GREEN release" />
          <Arrow />
          <Step title="Render per tier" text="Keep, realistic fake, mask, pseudonym, generalise or remove, by data class and clearance" />
          <Arrow />
          <Step title="Encrypt and log" text="One CP-ABE-encrypted copy per tier, master key in a separate authority; Merkle audit log" />
        </div>
        <p className="text-sm text-base-content/70">
          Credentials are removed at ingest and exist in no copy, RED included. The GREEN export passes a k-anonymity gate.
          <a className="link ml-1" href="#/policy">See the policy matrix</a>.
        </p>
      </Section>

      <Section n={4} title="A prototype of the design" Icon={KeyRound}>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {PAGES.map(({ href, label, Icon, text }) => (
            <a key={href} href={href} className="rounded-box border border-base-300 p-3 hover:border-primary focus-visible:outline-2 focus-visible:outline-primary">
              <span className="flex items-center gap-2 text-sm font-medium"><Icon size={14} aria-hidden="true" />{label}</span>
              <span className="text-xs text-base-content/70">{text}</span>
            </a>
          ))}
        </div>
        <p className="text-xs text-base-content/60">FastAPI and React; CP-ABE over BLS12-381; 39 automated tests run in CI.</p>
      </Section>

      <Section n={5} title="Experimental data" Icon={Database}>
        {data && (
          <div className="overflow-x-auto">
            <table className="table table-sm">
              <thead><tr><th>Data</th><th>Size</th><th>Used for</th><th>Source</th></tr></thead>
              <tbody>
                {data.datasets.map((d) => (
                  <tr key={d.name}><td className="font-medium">{d.name}</td><td>{d.size}</td><td>{d.use}</td><td className="text-xs">{d.source}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="text-xs text-base-content/60">
          Test sets were frozen by hash before scoring, and each was scored once. Sets the detector was tuned on are labelled as development sets.
        </p>
      </Section>

      <Section n={6} title="Demo" Icon={ScanSearch}>
        <ol className="list-inside list-decimal space-y-1 text-sm">
          <li><a className="link" href="#/live">Live anonymiser</a>: press <em>Play a call</em> and watch each tier update as the call arrives.</li>
          <li><a className="link" href="#/calls">Calls</a>: sign in as <code>compliance</code>, <code>priya</code> (agent) or <code>datasci</code> and open the same call; each sees only their tier.</li>
          <li>Open a low-risk call as compliance: break-glass asks for a reason, and the access lands in the <a className="link" href="#/audit">disclosure log</a>.</li>
          <li><a className="link" href="#/dashboard">Results dashboard</a>: what is caught, what each tier sees, what still leaks.</li>
        </ol>
        <a href="#/live" className="btn btn-sm btn-primary self-start"><Radio size={14} aria-hidden="true" /> Start the live demo</a>
      </Section>
    </div>
  )
}
