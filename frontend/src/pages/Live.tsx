import { Play, RotateCcw, ScanSearch, Square, Timer } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { api, ApiError, CLASS_CODE, parsePasted, SCENARIO_LABEL, TIERS, type Anonymized, type Tier, type User, type Utterance } from '../api'
import TierBadge from '../components/TierBadge'
import { Line } from '../components/Transcript'

const READER: Record<Tier, string> = { RED: 'Compliance', AMBER: 'Handling agent', GREEN: 'Model training corpus' }
const ACTION_LABEL: Record<string, string> = {
  keep: 'kept', surrogate: 'faked', pseudonym: 'placeholder', mask_last4: 'masked', generalize: 'generalised', suppress: 'removed',
}
const EXAMPLE = [
  'A: Thank you for calling Merlion Bank, may I have your full name?',
  'C: my name is Tan Wei Ming, I stay in Tampines',
  'A: Can you read me the OTP we just sent?',
  'C: the otp is four eight two nine one three',
  'A: Which account do you want to transfer from?',
  'C: account 123-45678-9, I want to send eight thousand dollars to my son in London',
].join('\n')
const STEP_MS = 1400 // one utterance "arrives" this often during playback

type Line_ = { speaker: 'agent' | 'client'; text: string }
type Sample = { scenario: string; utterances: Line_[] }

const count = (utts: Utterance[], key: 'class' | 'action') => {
  const c: Record<string, number> = {}
  for (const u of utts) for (const p of u.pieces) if (p.entity) c[p.entity[key]] = (c[p.entity[key]] ?? 0) + 1
  return c
}

function Pane({ title, sub, tier, utts, mine }: { title: string; sub: string; tier?: Tier; utts: Utterance[]; mine?: boolean }) {
  const actions = Object.entries(count(utts, 'action'))
  return (
    <section className="card border border-base-300 bg-base-100">
      <div className="card-body gap-2 p-4">
        <header className="flex flex-wrap items-center gap-2">
          {tier ? <TierBadge tier={tier} /> : <ScanSearch size={16} aria-hidden="true" />}
          <h2 className="text-sm font-semibold">{title}</h2>
          {mine && <span className="badge badge-sm badge-outline">your clearance</span>}
          <span className="text-xs text-base-content/60">{sub}</span>
        </header>
        {tier && (
          <p className="flex-none text-xs text-base-content/60">
            {actions.length ? actions.map(([a, n]) => `${n} ${ACTION_LABEL[a] ?? a}`).join(' · ') : 'nothing to change'}
          </p>
        )}
        <div className="flex flex-col gap-1.5">
          {utts.map((u, i) => <Line key={i} u={u} />)}
        </div>
      </div>
    </section>
  )
}

export default function Live({ user }: { user: User }) {
  const [input, setInput] = useState(EXAMPLE)
  const [result, setResult] = useState<Anonymized | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [queue, setQueue] = useState<Line_[]>([])
  const [scenario, setScenario] = useState<string | null>(null)
  const seq = useRef(0)
  const utterances = useMemo(() => parsePasted(input), [input])
  const playing = queue.length > 0

  // The whole pipeline (detect, triage, review check, render every tier) reruns shortly after each change.
  useEffect(() => {
    if (!utterances.length) return
    const n = ++seq.current
    const t = setTimeout(() => {
      setBusy(true)
      api<Anonymized>('/api/anonymize', { method: 'POST', body: JSON.stringify({ utterances }) })
        .then((r) => { if (n === seq.current) { setResult(r); setError('') } })
        .catch((e) => { if (n === seq.current) setError(e instanceof ApiError ? e.message : 'Could not reach the server') })
        .finally(() => { if (n === seq.current) setBusy(false) })
    }, 250)
    return () => clearTimeout(t)
  }, [utterances])

  // Playback: append the next utterance as if the speech recogniser had just produced it.
  useEffect(() => {
    if (!queue.length) return
    const t = setTimeout(() => {
      const [next, ...rest] = queue
      setInput((v) => (v ? `${v}\n` : '') + `${next.speaker === 'agent' ? 'A' : 'C'}: ${next.text}`)
      setQueue(rest)
    }, STEP_MS)
    return () => clearTimeout(t)
  }, [queue])

  async function play(style: 'asr' | 'clean') {
    try {
      const s = await api<Sample>(`/api/sample-call?style=${style}`)
      setScenario(s.scenario)
      setInput('')
      setQueue(s.utterances)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not load a sample call')
    }
  }

  const shown = utterances.length ? result : null
  const classes = shown ? Object.entries(count(shown.detected, 'class')) : []

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-4">
      <section className="card border border-base-300 bg-base-100">
        <div className="card-body gap-3 p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <h2 className="text-base font-semibold">Watch a transcript being anonymised</h2>
              <p className="text-sm text-base-content/70">
                Type, paste or play a call. Each change reruns detection and renders every clearance tier.
                Nothing on this page is stored or logged, and it shows all tiers because the text is yours.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              {playing ? (
                <button className="btn btn-sm" onClick={() => setQueue([])}>
                  <Square size={14} aria-hidden="true" /> Stop
                </button>
              ) : (
                <>
                  <button className="btn btn-sm btn-primary" onClick={() => play('asr')}>
                    <Play size={14} aria-hidden="true" /> Play a call (speech-recognition output)
                  </button>
                  <button className="btn btn-sm" onClick={() => play('clean')}>
                    <Play size={14} aria-hidden="true" /> Play a call (written)
                  </button>
                </>
              )}
              <button className="btn btn-sm btn-ghost" disabled={playing} onClick={() => { setScenario(null); setInput(EXAMPLE) }}>
                <RotateCcw size={14} aria-hidden="true" /> Example
              </button>
            </div>
          </div>
          <fieldset className="fieldset min-w-0 py-0">
            <label className="label whitespace-normal" htmlFor="live-input">
              Transcript, one utterance per line, starting “A:” (agent) or “C:” (client)
              {scenario && <span className="badge badge-sm badge-ghost">{SCENARIO_LABEL[scenario] ?? scenario}</span>}
            </label>
            <textarea
              id="live-input"
              className="textarea h-40 w-full font-mono text-sm"
              value={input}
              readOnly={playing}
              onChange={(e) => setInput(e.target.value)}
            />
          </fieldset>
          <div className="flex flex-wrap items-center gap-2 text-xs" aria-live="polite">
            {busy ? <span className="loading loading-spinner loading-xs" aria-label="Anonymising" /> : <Timer size={14} aria-hidden="true" />}
            {shown && <span>{shown.ms} ms on the server</span>}
            {shown && (
              <span className={`badge badge-sm badge-soft ${shown.risk === 'high' ? 'badge-error' : 'badge-ghost'}`} title={shown.risk_reason}>
                {shown.risk === 'high' ? 'High risk: referred to compliance' : 'Low risk'}
              </span>
            )}
            {shown && (
              <span className={`badge badge-sm badge-soft ${shown.review_reasons.length ? 'badge-warning' : 'badge-ghost'}`}
                title={shown.review_reasons.join('; ')}>
                {shown.review_reasons.length ? 'GREEN held for review' : 'No review needed'}
              </span>
            )}
            {classes.map(([c, n]) => (
              <span key={c} className="badge badge-sm badge-outline font-mono">{n} {CLASS_CODE[c] ?? c}</span>
            ))}
          </div>
          {error && <div role="alert" className="alert alert-error alert-soft text-sm">{error}</div>}
        </div>
      </section>

      {shown && (
        <div className="grid gap-4 xl:grid-cols-2">
          <Pane title="Detected" sub="what the six detection layers found; hover a value for the layer" utts={shown.detected} />
          {TIERS.map((t) => (
            <Pane key={t} tier={t} title={READER[t]} sub={`${t} release`} utts={shown.tiers[t]} mine={t === user.tier} />
          ))}
        </div>
      )}
    </div>
  )
}
