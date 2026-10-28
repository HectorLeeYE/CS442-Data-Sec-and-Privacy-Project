import { Mic, Square } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

// The browser's own recogniser (Chrome, Edge, Safari). lib.dom types the events but not the constructor.
type Recogniser = {
  continuous: boolean; interimResults: boolean; lang: string
  onresult: (e: SpeechRecognitionEvent) => void
  onerror: (e: SpeechRecognitionErrorEvent) => void
  onend: () => void
  start(): void; stop(): void; abort(): void
}
const w = window as unknown as Record<string, (new () => Recogniser) | undefined>
const Recognition = w.SpeechRecognition ?? w.webkitSpeechRecognition

type Props = {
  onLine: (line: string) => void              // each finished sentence, as 'A: ...' / 'C: ...'
  onInterim?: (line: string) => void          // the sentence still being spoken ('' when none); without it, shown here
  onRecording?: (on: boolean) => void
  label?: string
  disabled?: boolean
}

/** Record speech and hand each finished sentence back as an 'A: ...' / 'C: ...' line. */
export default function Dictate({ onLine, onInterim, onRecording, label = 'Record', disabled }: Props) {
  const [speaker, setSpeaker] = useState<'A' | 'C'>('C')
  const [on, setOn] = useState(false)
  const [interim, setInterim] = useState('')
  const [error, setError] = useState('')
  const rec = useRef<Recogniser | null>(null)
  const who = useRef(speaker)   // read when a sentence finishes, so switching speaker mid-call takes effect

  useEffect(() => () => { rec.current?.abort(); rec.current = null }, [])

  if (!Recognition) return <span className="text-xs text-base-content/60">Recording needs Chrome, Edge or Safari.</span>

  function start() {
    const r = new Recognition!()
    r.continuous = true
    r.interimResults = true
    r.lang = 'en-SG'
    r.onresult = (e) => {
      let partial = ''
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const t = e.results[i][0].transcript.trim()
        if (e.results[i].isFinal) { if (t) onLine(`${who.current}: ${t}`) } else partial += `${t} `
      }
      partial = partial.trim()
      if (onInterim) onInterim(partial && `${who.current}: ${partial}`)
      else setInterim(partial)
    }
    r.onerror = (e) => {
      if (e.error === 'no-speech' || e.error === 'aborted') return
      setError(e.error === 'not-allowed' ? 'Microphone access was denied.' : `Speech recognition failed: ${e.error}`)
      rec.current = null
    }
    // The recogniser stops itself after a silence; keep going until the user presses Stop.
    r.onend = () => {
      setInterim('')
      onInterim?.('')
      if (rec.current === r) r.start()
      else { setOn(false); onRecording?.(false) }
    }
    rec.current = r
    setError('')
    setOn(true)
    onRecording?.(true)
    r.start()
  }

  function stop() {
    const r = rec.current
    rec.current = null
    r?.stop()   // flushes the sentence in progress, then onend
  }

  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      {on ? (
        <button type="button" className="btn btn-sm btn-error" onClick={stop}>
          <Square size={14} aria-hidden="true" /> Stop recording
        </button>
      ) : (
        <button type="button" className="btn btn-sm" onClick={start} disabled={disabled}>
          <Mic size={14} aria-hidden="true" /> {label}
        </button>
      )}
      <div className="join" role="radiogroup" aria-label="Who is speaking">
        {(['A', 'C'] as const).map((s) => (
          <button key={s} type="button" role="radio" aria-checked={speaker === s}
                  className={`btn btn-xs join-item ${speaker === s ? 'btn-active' : ''}`} onClick={() => { who.current = s; setSpeaker(s) }}>
            {s === 'A' ? 'Agent' : 'Client'} speaking
          </button>
        ))}
      </div>
      {on && <span className="loading loading-ring loading-xs text-error" aria-label="Recording" />}
      {interim && <span className="italic text-base-content/60">{interim}…</span>}
      {error && <span role="alert" className="text-error">{error}</span>}
    </div>
  )
}
