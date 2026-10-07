import { Bot, Headset, Lock, Siren, UserRound } from 'lucide-react'
import { useState } from 'react'
import { CLASS_CODE, type Entity, type Piece, type Tier, type Utterance } from '../api'

// Full class strings, never built dynamically, so Tailwind sees them.
const CHIP: Record<string, string> = {
  AUTH_SECRET: 'rounded-sm px-0.5 font-mono text-[0.85em] ring-1 ring-inset focus-visible:outline-2 focus-visible:outline-primary bg-error/15 text-base-content ring-error/40',
  FINANCIAL_ID: 'rounded-sm px-0.5 font-mono text-[0.85em] ring-1 ring-inset focus-visible:outline-2 focus-visible:outline-primary bg-warning/25 text-base-content ring-warning/60',
  DIRECT_ID: 'rounded-sm px-0.5 font-mono text-[0.85em] ring-1 ring-inset focus-visible:outline-2 focus-visible:outline-primary bg-info/15 text-base-content ring-info/40',
  QUASI_ID: 'rounded-sm px-0.5 font-mono text-[0.85em] ring-1 ring-inset focus-visible:outline-2 focus-visible:outline-primary bg-base-300 text-base-content ring-base-content/20',
  SENSITIVE_ATTR: 'rounded-sm px-0.5 font-mono text-[0.85em] ring-1 ring-inset focus-visible:outline-2 focus-visible:outline-primary bg-secondary/15 text-base-content ring-secondary/40',
}

const ACTION_TEXT: Record<string, string> = {
  keep: 'shown unchanged at this clearance',
  surrogate: 'replaced with a realistic fake of the same shape',
  pseudonym: 'replaced with a placeholder, stable within this call',
  mask_last4: 'all but the last 4 digits masked',
  generalize: 'replaced with a coarser value',
  suppress: 'removed',
}

function Chip({ text, e }: { text: string; e: Entity }) {
  return (
    <span className="tooltip tooltip-bottom">
      <span className="tooltip-content max-w-64 text-left text-xs leading-snug">
        <span className="block font-mono font-medium">{e.class} · {e.type}</span>
        <span className="block">Found by: {e.layer} layer{e.layer !== 'propagate' && `, score ${e.score}`}</span>
        <span className="block">Action: {e.action} — {ACTION_TEXT[e.action] ?? e.action}</span>
      </span>
      <mark
        tabIndex={0}
        aria-label={`${text}. ${e.type}, ${e.action}, found by ${e.layer}`}
        className={CHIP[e.class]}
      >
        {text}
        <sup className="ml-0.5 font-mono text-[0.6rem] font-medium text-base-content/60">{CLASS_CODE[e.class]}</sup>
      </mark>
    </span>
  )
}

export function Line({ u }: { u: Utterance }) {
  const Icon = u.speaker === 'agent' ? Headset : UserRound
  return (
    <p className="text-sm leading-relaxed">
      <span className="mr-1.5 inline-flex items-center gap-1 align-middle text-xs font-medium text-base-content/60">
        <Icon size={12} aria-hidden="true" />
        {u.speaker === 'agent' ? 'Agent' : 'Client'}
      </span>
      {u.pieces.map((p: Piece, i) => (p.entity ? <Chip key={i} text={p.text} e={p.entity} /> : <span key={i}>{p.text}</span>))}
    </p>
  )
}

export function Locked({ tier, reason, onTry }: { tier: Tier; reason: string; onTry?: () => void }) {
  return (
    <div role="status" className="flex flex-col items-start gap-2 rounded-box border border-dashed border-base-300 p-4 text-sm">
      <span className="inline-flex items-center gap-2 font-medium"><Lock size={14} aria-hidden="true" /> {tier} view withheld</span>
      <span className="text-base-content/70">{reason}</span>
      {onTry && (
        <button className="btn btn-xs" onClick={onTry}>
          Request it anyway (the denial is logged)
        </button>
      )}
    </div>
  )
}

/** A RED user opening a low-risk call: the reason is logged with the release. */
export function BreakGlass({ id, reason, min, onOpen }: { id: string; reason: string; min: number; onOpen: (why: string) => void }) {
  const [why, setWhy] = useState('')
  const ok = why.trim().length >= min
  return (
    <form
      className="flex flex-col gap-2 rounded-box border border-dashed border-base-300 p-3 text-sm"
      onSubmit={(e) => { e.preventDefault(); if (ok) onOpen(why.trim()) }}
    >
      <span className="inline-flex items-center gap-2 font-medium"><Siren size={14} aria-hidden="true" /> Break-glass access</span>
      <span className="text-base-content/70">{reason}</span>
      <fieldset className="fieldset min-w-0 py-0">
        <label className="label whitespace-normal" htmlFor={id}>Business reason (logged, at least {min} characters)</label>
        <textarea id={id} aria-label="Break-glass business reason" className="textarea textarea-sm h-16 w-full" value={why} onChange={(e) => setWhy(e.target.value)} />
      </fieldset>
      <button className="btn btn-xs self-start" disabled={!ok}>Open with this reason</button>
    </form>
  )
}

export const SourceLabel = ({ source }: { source: string }) => (
  <span className="badge badge-sm badge-ghost">
    {source === 'asr' ? <Bot size={12} aria-hidden="true" /> : <UserRound size={12} aria-hidden="true" />}
    {source === 'asr' ? 'Raw ASR output' : source === 'manual' ? 'Pasted' : 'Human transcriber'}
  </span>
)
