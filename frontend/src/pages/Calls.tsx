import { ClipboardPaste, Fingerprint, PhoneIncoming, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError, SCENARIO_LABEL, TIER_RANK, TIERS, type CallSummary, type CallView, type Tier, type User } from '../api'
import TierBadge from '../components/TierBadge'
import { Line, Locked, SourceLabel } from '../components/Transcript'

type Column = { state: 'loading' } | { state: 'ok'; view: CallView } | { state: 'locked'; reason: string; local: boolean }

const TIER_NOTE: Record<Tier, string> = {
  RED: 'Compliance / risk',
  AMBER: 'Handling agent',
  GREEN: 'Model training corpus',
}

function parsePasted(text: string) {
  return text
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)
    .map((l) => {
      const m = l.match(/^(a|agent|c|client|customer)\s*:\s*(.+)$/i)
      const who = m?.[1].toLowerCase() ?? 'c'
      return { speaker: who.startsWith('a') ? 'agent' : 'client', text: m ? m[2] : l }
    })
}

export default function Calls({ user }: { user: User }) {
  const [calls, setCalls] = useState<CallSummary[] | null>(null)
  const [listError, setListError] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [columns, setColumns] = useState<Partial<Record<Tier, Column>>>({})
  const [mobileTier, setMobileTier] = useState<Tier>(user.tier)
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState<string | null>(null)
  const [pasted, setPasted] = useState('')
  const dialog = useRef<HTMLDialogElement>(null)

  const loadList = useCallback(async () => {
    try {
      const list = await api<CallSummary[]>('/api/calls')
      setCalls(list)
      setListError(null)
      return list
    } catch (e) {
      setListError(e instanceof Error ? e.message : 'Could not load calls')
      return []
    }
  }, [])

  useEffect(() => {
    loadList().then((list) => setSelected((s) => s ?? (list.find((c) => c.mine) ?? list[0])?.id ?? null))
  }, [loadList])

  const fetchTier = useCallback(async (id: string, tier: Tier) => {
    setColumns((c) => ({ ...c, [tier]: { state: 'loading' } }))
    try {
      const view = await api<CallView>(`/api/calls/${id}?tier=${tier}`)
      setColumns((c) => ({ ...c, [tier]: { state: 'ok', view } }))
    } catch (e) {
      const reason = e instanceof ApiError ? e.message : 'Could not load this view'
      setColumns((c) => ({ ...c, [tier]: { state: 'locked', reason, local: false } }))
    }
  }, [])

  useEffect(() => {
    if (!selected) return
    const next: Partial<Record<Tier, Column>> = {}
    for (const t of TIERS) {
      if (TIER_RANK[t] > TIER_RANK[user.tier]) {
        next[t] = { state: 'locked', reason: `Requires ${t} clearance; you hold ${user.tier}.`, local: true }
      }
    }
    setColumns(next)
    TIERS.filter((t) => TIER_RANK[t] <= TIER_RANK[user.tier]).forEach((t) => fetchTier(selected, t))
  }, [selected, user.tier, fetchTier])

  async function create(path: string, body?: object) {
    setBusy(true)
    try {
      const { id } = await api<{ id: string }>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined })
      await loadList()
      setSelected(id)
      setToast(`Call ${id} ingested, detected and encrypted at rest.`)
      setTimeout(() => setToast(null), 3500)
    } catch (e) {
      setToast(e instanceof Error ? e.message : 'Ingest failed')
    } finally {
      setBusy(false)
    }
  }

  const canIngest = TIER_RANK[user.tier] >= TIER_RANK.AMBER
  const reference = TIERS.map((t) => columns[t]).find((c): c is { state: 'ok'; view: CallView } => c?.state === 'ok')
  const rows = reference?.view.utterances.length ?? 0
  const current = calls?.find((c) => c.id === selected)

  return (
    <div className="grid gap-4 xl:grid-cols-[18rem_minmax(0,1fr)]">
      {/* call list */}
      <section aria-label="Calls" className="min-w-0 rounded-box border border-base-300 bg-base-100">
        <div className="flex flex-wrap items-center gap-2 border-b border-base-300 p-3">
          {canIngest ? (
            <>
              <button className="btn btn-sm btn-primary" onClick={() => create('/api/calls/simulate')} disabled={busy}>
                {busy ? <span className="loading loading-spinner loading-xs" /> : <PhoneIncoming size={14} aria-hidden="true" />}
                Take a call
              </button>
              <button className="btn btn-sm" onClick={() => dialog.current?.showModal()} disabled={busy}>
                <ClipboardPaste size={14} aria-hidden="true" /> Paste
              </button>
            </>
          ) : (
            <p className="text-xs text-base-content/60">GREEN clearance can read the de-identified corpus but cannot ingest calls.</p>
          )}
          <button className="btn btn-sm btn-ghost btn-square ml-auto" aria-label="Refresh call list" onClick={loadList}>
            <RefreshCw size={14} aria-hidden="true" />
          </button>
        </div>
        {listError && <div role="alert" className="alert alert-soft alert-error m-3 text-sm">{listError}</div>}
        <div className="max-h-[32rem] max-w-full overflow-x-auto overflow-y-auto xl:max-h-[calc(100vh-11rem)]">
          <table className="table table-sm">
            <thead>
              <tr><th>Call</th><th>Type</th></tr>
            </thead>
            <tbody>
              {!calls && [0, 1, 2, 3, 4].map((i) => (
                <tr key={i}><td colSpan={2}><div className="skeleton h-8 w-full" /></td></tr>
              ))}
              {calls?.length === 0 && (
                <tr><td colSpan={2} className="text-sm text-base-content/60">No calls yet. Take a call to create one.</td></tr>
              )}
              {calls?.map((c) => (
                <tr key={c.id} className={c.id === selected ? 'bg-base-200' : 'hover:bg-base-200/60'}>
                  <td>
                    <button className="btn btn-xs btn-ghost font-mono" aria-pressed={c.id === selected} onClick={() => setSelected(c.id)}>
                      {c.id}
                    </button>
                    {c.mine && <span className="badge badge-xs badge-ghost ml-1">yours</span>}
                  </td>
                  <td className="text-xs">
                    {SCENARIO_LABEL[c.scenario] ?? c.scenario}
                    <div className="text-base-content/50">{c.source === 'asr' ? 'ASR' : c.source === 'manual' ? 'pasted' : 'transcriber'}</div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* transcript at each clearance */}
      <section aria-label="Transcript by clearance" className="min-w-0 rounded-box border border-base-300 bg-base-100">
        {!selected ? (
          <p className="p-6 text-sm text-base-content/60">Select a call to see what each clearance receives.</p>
        ) : (
          <>
            <header className="flex flex-wrap items-center gap-2 border-b border-base-300 p-3">
              <h2 className="font-mono text-sm font-medium">{selected}</h2>
              {current && <span className="text-sm">{SCENARIO_LABEL[current.scenario] ?? current.scenario}</span>}
              {current && <SourceLabel source={current.source} />}
              <span className="ml-auto text-xs text-base-content/60">Hover or focus a tag to see why it changed.</span>
            </header>

            <div role="tablist" aria-label="Clearance" className="tabs tabs-box tabs-sm m-3 lg:hidden">
              {TIERS.map((t) => (
                <button key={t} role="tab" aria-selected={mobileTier === t}
                        className={mobileTier === t ? 'tab tab-active' : 'tab'} onClick={() => setMobileTier(t)}>
                  {t}
                </button>
              ))}
            </div>

            {/* column headers */}
            <div className="grid border-b border-base-300 lg:grid-cols-3">
              {TIERS.map((t) => {
                const c = columns[t]
                return (
                  <div key={t} className={mobileTier === t ? 'flex flex-col gap-1 p-3 lg:border-l lg:border-base-300 lg:first:border-l-0' : 'flex flex-col gap-1 p-3 max-lg:hidden lg:border-l lg:border-base-300 lg:first:border-l-0'}>
                    <div className="flex items-center gap-2">
                      <TierBadge tier={t} />
                      <span className="text-xs text-base-content/60">{TIER_NOTE[t]}</span>
                    </div>
                    {c?.state === 'ok' && (
                      <div className="flex flex-wrap gap-1 text-xs tabular-nums text-base-content/70">
                        {Object.entries(c.view.actions).map(([a, n]) => (
                          <span key={a} className="badge badge-xs badge-ghost">{a} {n}</span>
                        ))}
                      </div>
                    )}
                    {c?.state === 'locked' && (
                      <Locked tier={t} reason={c.reason} onTry={c.local ? () => fetchTier(selected, t) : undefined} />
                    )}
                  </div>
                )
              })}
            </div>

            {/* utterance rows, aligned across tiers */}
            <div className="divide-y divide-base-200">
              {!reference && TIERS.some((t) => columns[t]?.state === 'loading') &&
                [0, 1, 2, 3].map((i) => (
                  <div key={i} className="grid gap-3 p-3 lg:grid-cols-3">
                    {TIERS.map((t) => <div key={t} className={mobileTier === t ? 'skeleton h-10' : 'skeleton h-10 max-lg:hidden'} />)}
                  </div>
                ))}
              {Array.from({ length: rows }, (_, i) => (
                <div key={i} className="grid lg:grid-cols-3">
                  {TIERS.map((t) => {
                    const c = columns[t]
                    return (
                      <div key={t} className={mobileTier === t ? 'min-w-0 px-3 py-2 lg:border-l lg:border-base-200 lg:first:border-l-0' : 'min-w-0 px-3 py-2 max-lg:hidden lg:border-l lg:border-base-200 lg:first:border-l-0'}>
                        {c?.state === 'ok' && c.view.utterances[i] && <Line u={c.view.utterances[i]} />}
                        {c?.state === 'loading' && <div className="skeleton h-6 w-full" />}
                      </div>
                    )
                  })}
                </div>
              ))}
            </div>

            {/* release receipts */}
            <footer className="grid border-t border-base-300 lg:grid-cols-3">
              {TIERS.map((t) => {
                const c = columns[t]
                return (
                  <div key={t} className={mobileTier === t ? 'p-3 text-xs lg:border-l lg:border-base-300 lg:first:border-l-0' : 'p-3 text-xs max-lg:hidden lg:border-l lg:border-base-300 lg:first:border-l-0'}>
                    {c?.state === 'ok' ? (
                      <span className="inline-flex flex-wrap items-center gap-1 text-base-content/70">
                        <Fingerprint size={12} aria-hidden="true" />
                        Released · logged as <code className="font-mono">sha256:{c.view.digest.slice(0, 12)}…</code>
                      </span>
                    ) : (
                      <span className="text-base-content/50">Nothing released at {t}.</span>
                    )}
                  </div>
                )
              })}
            </footer>
          </>
        )}
      </section>

      <dialog ref={dialog} className="modal" aria-labelledby="paste-title">
        <form
          className="modal-box"
          onSubmit={(e) => {
            e.preventDefault()
            const utterances = parsePasted(pasted)
            if (!utterances.length) return
            dialog.current?.close()
            setPasted('')
            create('/api/calls', { utterances })
          }}
        >
          <h3 id="paste-title" className="text-lg font-semibold">Paste a transcript</h3>
          <fieldset className="fieldset">
            <label className="label whitespace-normal" htmlFor="paste-text">One utterance per line, prefixed with A: (agent) or C: (client)</label>
            <textarea id="paste-text" required className="textarea textarea-sm h-48 w-full font-mono" value={pasted}
                      onChange={(e) => setPasted(e.target.value)}
                      placeholder={'A: Thank you for calling, may I have your NRIC?\nC: Sure, it is S1234567D and my OTP is 482913.'} />
            <p className="label whitespace-normal">Detection runs once on ingest. You will be recorded as the handling agent.</p>
          </fieldset>
          <div className="modal-action">
            <button type="button" className="btn btn-sm" onClick={() => dialog.current?.close()}>Cancel</button>
            <button className="btn btn-sm btn-primary">Ingest transcript</button>
          </div>
        </form>
        <form method="dialog" className="modal-backdrop"><button>close</button></form>
      </dialog>

      {toast && (
        <div className="toast toast-end">
          <div role="status" className="alert alert-soft text-sm">{toast}</div>
        </div>
      )}
    </div>
  )
}
