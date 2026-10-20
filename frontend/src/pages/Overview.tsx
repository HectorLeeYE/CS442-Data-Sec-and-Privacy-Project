import { ArrowRight, Check, Database, FileLock2, FlaskConical, Hourglass, KeyRound, ListChecks, Mic, Radio, ScanSearch, ScrollText, Split, Target as TargetIcon, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, ApiError, type Overview as OverviewData, type Target, type Task } from '../api'
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

const pct = (v: number) => `${(v * 100).toFixed(1)}%`

function Recogniser({ label, wer, note, primary }: { label: string; wer: number; note: string; primary?: boolean }) {
  return (
    <div className={`min-w-0 flex-1 rounded-box border p-3 ${primary ? 'border-primary' : 'border-base-300'}`}>
      <div className="text-xs text-base-content/70">{label}</div>
      <div className="text-2xl font-semibold tabular-nums">{pct(wer)} <span className="text-xs font-normal text-base-content/60">word error rate</span></div>
      <div className="text-xs text-base-content/70">{note}</div>
    </div>
  )
}

function TaskResult({ t }: { t: Task }) {
  const deploy = t.new_wer < t.old_wer && t.new_wer <= t.raw_wer + 0.01
  return (
    <div className="flex flex-col gap-3 border-t border-base-300 pt-3">
      <h3 className="text-sm font-semibold">The analysis, run: old recogniser against new</h3>
      <div className="flex flex-col gap-2 md:flex-row">
        <Recogniser label="Old: the in-house recogniser today" wer={t.old_wer}
          note={`Stand-in: ${t.asr_model} alone, on ${t.test_calls} test calls of Singapore-English speech`} />
        <Recogniser label="New: adapted on the GREEN release" wer={t.new_wer} primary
          note={`Its language model trained on ${t.n_train_calls} de-identified calls; ${((t.old_wer - t.new_wer) * 100).toFixed(1)} points fewer errors`} />
        <Recogniser label="Adapted on raw transcripts (not releasable)" wer={t.raw_wer}
          note="The upper bound: what the bank would get if data science could read the calls in full" />
      </div>
      <div className="overflow-x-auto">
        <table className="table table-sm">
          <caption className="pb-1 text-left text-xs font-medium text-base-content/70">Inspect: where the old recogniser fails (share of words it gets wrong), and what adapting fixes</caption>
          <thead><tr><th>Kind of word</th><th className="text-right">Words</th><th className="text-right">Old</th><th className="text-right">New (GREEN)</th><th className="text-right">Raw-trained</th></tr></thead>
          <tbody>
            {t.breakdown.map((b) => (
              <tr key={b.category}>
                <td>{b.category}</td>
                <td className="text-right tabular-nums">{b.words.toLocaleString()}</td>
                <td className="text-right tabular-nums">{pct(b.old_missed)}</td>
                <td className="text-right font-medium tabular-nums">{pct(b.new_missed)}</td>
                <td className="text-right tabular-nums text-base-content/60">{pct(b.raw_missed)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-base-content/70">
        Adapting fixes everyday banking English and Mandarin or Malay phrases. Singlish particles defeat both: the right spelling is
        not among the recogniser&apos;s guesses, so fixing them needs acoustic fine-tuning, not text. The GREEN release matches raw
        transcripts everywhere except names and numbers, the very words it replaces with fakes.
      </p>
      {t.examples.length > 0 && (
        <div className="overflow-x-auto">
          <table className="table table-sm">
            <caption className="pb-1 text-left text-xs font-medium text-base-content/70">Utterances the new recogniser gets right (only ones with no personal data are shown)</caption>
            <thead><tr><th>Said</th><th>Old</th><th>New</th></tr></thead>
            <tbody>
              {t.examples.map((x) => (
                <tr key={x.reference}><td>{x.reference}</td><td className="text-base-content/70">{x.old}</td><td>{x.new}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div role="status" className={`alert alert-soft text-sm ${deploy ? 'alert-success' : 'alert-warning'}`}>
        <span>
          <strong>Decision: {deploy ? 'deploy the new recogniser, trained on GREEN' : 'do not deploy yet'}.</strong>{' '}
          It beats the old one by {((t.old_wer - t.new_wer) * 100).toFixed(1)} points and stays {((t.new_wer - t.raw_wer) * 100).toFixed(1)} points
          from raw (target U8: within 1). The bank gets most of the gain without data science reading a single real identifier.
        </span>
      </div>
      <h3 className="text-sm font-semibold">How the new recogniser is kept private</h3>
      <ul className="list-disc space-y-1 pl-5 text-sm">
        <li><strong>It only ever sees GREEN.</strong> The training pipeline is the <code>model</code> account at GREEN clearance; its CP-ABE key cannot open a RED or AMBER copy, even with the database in hand.</li>
        <li><strong>Identifiers are replaced, not blacked out.</strong> NRIC, account and card numbers become checksum-valid fakes of the same shape; names become pseudonyms from a pool that shares no word with real names; places and employers become a region or a sector. The fakes are why GREEN keeps most of the gain.</li>
        <li><strong>Credentials never reach it.</strong> OTPs, PINs, CVVs and security answers are removed at ingest and exist in no copy, RED included.</li>
        <li><strong>Doubtful calls are held back.</strong> A call with an unanswered credential question or a stray long number is held for review and stays encrypted to RED until compliance releases it.</li>
        <li><strong>Rare combinations are suppressed.</strong> The training export passes a k-anonymity gate (k = 5): a call whose combination of quasi-identifiers (region, sector and so on) fewer than 5 calls share loses them.</li>
        <li><strong>What it was trained on is provable.</strong> The export carries an Ed25519-signed manifest, and every release is hashed into the Merkle disclosure log.</li>
        {t.canary && (
          <li><strong>Memorisation was tested.</strong> A fake NRIC planted 20 times is memorised by a model trained on raw text ({t.canary.raw} of {t.canary.max} bits of exposure) and not by one trained on GREEN ({t.canary.green} bits), E6.</li>
        )}
      </ul>
      <p className="text-xs text-base-content/60">
        Not done: differentially private training (at this data size its noise destroys the model, E2), and erasing a client
        does not untrain a model already trained; the next release retrains without them.
      </p>
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
          The analysis: <strong>where does it fail, and does adapting it on recorded client calls cut those errors enough to
          deploy it?</strong> Data scientists inspect the transcripts and errors, clean and transform them into a training set,
          adapt the model and measure word error rate (E8). They hold the lowest
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
        {data?.task && <TaskResult t={data.task} />}
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
        <p className="text-xs text-base-content/60">FastAPI and React; CP-ABE over BLS12-381; 41 automated tests run in CI.</p>
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
          <li><a className="link" href="#/calls">Calls</a>: sign in as <code>compliance</code>, <code>priya</code> (agent) or <code>datasci</code> and open the same call. Each sees only the tiers their clearance reads and only the tools their job needs: compliance reviews and reads the log, the agent takes calls, data science exports the training set.</li>
          <li>Open a low-risk call as compliance: break-glass asks for a reason, and the access lands in the <a className="link" href="#/audit">disclosure log</a>.</li>
          <li><a className="link" href="#/attack">Simulate attack</a>: steal the database, a key or a backup, and see what opens.</li>
          <li><a className="link" href="#/dashboard">Results dashboard</a>: what is caught, what each tier sees, what still leaks.</li>
        </ol>
        <a href="#/live" className="btn btn-sm btn-primary self-start"><Radio size={14} aria-hidden="true" /> Start the live demo</a>
      </Section>
    </div>
  )
}
