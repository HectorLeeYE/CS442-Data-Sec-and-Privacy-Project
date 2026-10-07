import { ClipboardPaste, Download, Eraser, Fingerprint, PhoneIncoming, RefreshCw, ShieldCheck, Siren } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError, SCENARIO_LABEL, TIER_RANK, TIERS, type CallSummary, type CallView, type ExportResult, type Tier, type User } from '../api'
import TierBadge from '../components/TierBadge'
import { BreakGlass, Line, Locked, SourceLabel } from '../components/Transcript'

type Column =
  | { state: 'loading' }
  | { state: 'ok'; view: CallView }
  | { state: 'locked'; reason: string; local: boolean }
  | { state: 'breakglass'; reason: string }

const TIER_NOTE: Record<Tier, string> = {
  RED: 'Compliance / risk',
  AMBER: 'Handling agent',
  GREEN: 'Model training corpus',
}
const MIN_REASON = 15

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

/** RED opening a low-risk call that is not theirs: a break-glass access, so ask before fetching. */
function needsBreakGlass(user: User, call: CallSummary | undefined, tier: Tier) {
  return user.tier === 'RED' && call?.risk === 'low' && !call.mine && tier !== 'GREEN'
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
  const [decision, setDecision] = useState<'approve' | 'erase' | null>(null)
  const [reason, setReason] = useState('')
  const [exported, setExported] = useState<ExportResult | null>(null)
  const dialog = useRef<HTMLDialogElement>(null)
  const decisionDialog = useRef<HTMLDialogElement>(null)
  const exportDialog = useRef<HTMLDialogElement>(null)

  const notify = (msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(null), 3500)
  }

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

  const fetchTier = useCallback(async (id: string, tier: Tier, justification?: string) => {
    setColumns((c) => ({ ...c, [tier]: { state: 'loading' } }))
    const q = justification ? `&justification=${encodeURIComponent(justification)}` : ''
    try {
      const view = await api<CallView>(`/api/calls/${id}?tier=${tier}${q}`)
      setColumns((c) => ({ ...c, [tier]: { state: 'ok', view } }))
    } catch (e) {
      const reason = e instanceof ApiError ? e.message : 'Could not load this view'
      const next: Column = e instanceof ApiError && e.status === 428 ? { state: 'breakglass', reason } : { state: 'locked', reason, local: false }
      setColumns((c) => ({ ...c, [tier]: next }))
    }
  }, [])

  const current = calls?.find((c) => c.id === selected)

  useEffect(() => {
    if (!selected || !calls) return
    const call = calls.find((c) => c.id === selected)
    const next: Partial<Record<Tier, Column>> = {}
    for (const t of TIERS) {
      if (TIER_RANK[t] > TIER_RANK[user.tier]) {
        next[t] = { state: 'locked', reason: `Requires ${t} clearance; you hold ${user.tier}.`, local: true }
      } else if (needsBreakGlass(user, call, t)) {
        next[t] = { state: 'breakglass', reason: 'Low-risk call: never referred to compliance. Opening it in full is a break-glass access.' }
      }
    }
    setColumns(next)
    TIERS.filter((t) => !next[t]).forEach((t) => fetchTier(selected, t))
    // re-run only when the selection changes, not when the list refreshes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, user.tier, fetchTier])

  async function create(path: string, body?: object) {
    setBusy(true)
    try {
      const { id } = await api<{ id: string }>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined })
      await loadList()
      setSelected(id)
      notify(`Call ${id} ingested, triaged, detected and encrypted under its access policies.`)
    } catch (e) {
      notify(e instanceof Error ? e.message : 'Ingest failed')
    } finally {
      setBusy(false)
    }
  }

  async function decide() {
    if (!selected || !decision) return
    setBusy(true)
    try {
      await api(`/api/calls/${selected}/${decision}`, { method: 'POST', body: JSON.stringify({ reason }) })
      decisionDialog.current?.close()
      setReason('')
      const list = await loadList()
      if (decision === 'erase') {
        notify(`Call ${selected} erased: its data keys were destroyed.`)
        setSelected(list[0]?.id ?? null)
      } else {
        notify(`Call ${selected} released to GREEN.`)
        fetchTier(selected, 'GREEN')
      }
    } catch (e) {
      notify(e instanceof Error ? e.message : 'Request failed')
    } finally {
      setBusy(false)
    }
  }

  async function runExport() {
    setBusy(true)
    try {
      setExported(await api<ExportResult>('/api/export'))
      exportDialog.current?.showModal()
    } catch (e) {
      notify(e instanceof Error ? e.message : 'Export failed')
    } finally {
      setBusy(false)
    }
  }

  function download() {
    if (!exported) return
    const files: [string, string][] = [
      ['quietline-green.jsonl', exported.jsonl],
      ['quietline-green.manifest.json', JSON.stringify({ manifest: exported.manifest, signature: exported.signature }, null, 1)],
    ]
    for (const [name, body] of files) {
      const a = document.createElement('a')
      a.href = URL.createObjectURL(new Blob([body], { type: 'application/json' }))
      a.download = name
      a.click()
      URL.revokeObjectURL(a.href)
    }
  }

  const canIngest = TIER_RANK[user.tier] >= TIER_RANK.AMBER
  const isRed = user.tier === 'RED'
  const reference = TIERS.map((t) => columns[t]).find((c): c is { state: 'ok'; view: CallView } => c?.state === 'ok')
  const rows = reference?.view.utterances.length ?? 0

  return (
    <div className="grid gap-4 xl:grid-cols-[19rem_minmax(0,1fr)]">
      {/* call list */}
      <section aria-label="Calls" className="min-w-0 rounded-box border border-base-300 bg-base-100">
        <div className="flex flex-wrap items-center gap-2 border-b border-base-300 p-3">
          {canIngest && (
            <>
              <button className="btn btn-sm btn-primary" onClick={() => create('/api/calls/simulate')} disabled={busy}>
                {busy ? <span className="loading loading-spinner loading-xs" /> : <PhoneIncoming size={14} aria-hidden="true" />}
                Take a call
              </button>
              <button className="btn btn-sm" onClick={() => dialog.current?.showModal()} disabled={busy}>
                <ClipboardPaste size={14} aria-hidden="true" /> Paste
              </button>
            </>
          )}
          <button className="btn btn-sm" onClick={runExport} disabled={busy}>
            <Download size={14} aria-hidden="true" /> Training set
          </button>
          <button className="btn btn-sm btn-ghost btn-square ml-auto" aria-label="Refresh call list" onClick={loadList}>
            <RefreshCw size={14} aria-hidden="true" />
          </button>
        </div>
        {!canIngest && <p className="px-3 pt-2 text-xs text-base-content/60">GREEN clearance reads the de-identified corpus and exports the training set; it cannot ingest calls.</p>}
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
                    <div className="mt-0.5 flex flex-wrap gap-1">
                      {c.mine && <span className="badge badge-xs badge-ghost">yours</span>}
                      {c.review === 'pending' && <span className="badge badge-xs badge-soft badge-warning">held for review</span>}
                    </div>
                  </td>
                  <td className="text-xs">
                    {SCENARIO_LABEL[c.scenario] ?? c.scenario}
                    <div className="text-base-content/60">
                      {c.risk === 'high' ? 'High risk' : 'Low risk'} · {c.source === 'asr' ? 'ASR' : c.source === 'manual' ? 'pasted' : 'transcriber'}
                    </div>
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
              {current && (
                <span className={current.risk === 'high' ? 'badge badge-sm badge-soft badge-error' : 'badge badge-sm badge-ghost'}>
                  <Siren size={12} aria-hidden="true" />
                  {current.risk === 'high' ? 'High risk: referred to compliance' : 'Low risk: not referred'}
                </span>
              )}
              {isRed && current && (
                <span className="ml-auto flex flex-wrap gap-2">
                  {current.review === 'pending' && (
                    <button className="btn btn-sm" onClick={() => { setDecision('approve'); decisionDialog.current?.showModal() }}>
                      <ShieldCheck size={14} aria-hidden="true" /> Release to GREEN
                    </button>
                  )}
                  <button className="btn btn-sm btn-ghost" onClick={() => { setDecision('erase'); decisionDialog.current?.showModal() }}>
                    <Eraser size={14} aria-hidden="true" /> Erase
                  </button>
                </span>
              )}
            </header>

            {isRed && current && (current.risk_reason || current.review_reasons?.length) ? (
              <div className="flex flex-col gap-1 border-b border-base-300 px-3 py-2 text-xs text-base-content/70">
                {current.risk_reason && <span>Triage: {current.risk_reason}.</span>}
                {current.review === 'pending' && current.review_reasons && (
                  <span>Held from GREEN for privacy review: {current.review_reasons.join('; ')}.</span>
                )}
              </div>
            ) : null}

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
                    {c?.state === 'breakglass' && (
                      <BreakGlass id={`bg-${t}`} reason={c.reason} min={MIN_REASON} onOpen={(why) => fetchTier(selected, t, why)} />
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
                        Log #{c.view.receipt.seq} · <code className="font-mono">sha256:{c.view.digest.slice(0, 12)}…</code> · signed receipt
                      </span>
                    ) : (
                      <span className="text-base-content/60">Nothing released at {t}.</span>
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
            <p className="label whitespace-normal">Detection and triage run once on ingest; each tier's copy is encrypted under its own access policy. You will be recorded as the handling agent.</p>
          </fieldset>
          <div className="modal-action">
            <button type="button" className="btn btn-sm" onClick={() => dialog.current?.close()}>Cancel</button>
            <button className="btn btn-sm btn-primary">Ingest transcript</button>
          </div>
        </form>
        <form method="dialog" className="modal-backdrop"><button>close</button></form>
      </dialog>

      <dialog ref={decisionDialog} className="modal" aria-labelledby="decision-title">
        <form className="modal-box" onSubmit={(e) => { e.preventDefault(); decide() }}>
          <h3 id="decision-title" className="text-lg font-semibold">
            {decision === 'erase' ? `Erase ${selected}` : `Release ${selected} to GREEN`}
          </h3>
          <p className="py-2 text-sm text-base-content/70">
            {decision === 'erase'
              ? 'Destroys the data keys of every copy of this call (crypto-shredding), then the copies. Cannot be undone.'
              : 'Confirms you read the GREEN rendering and nothing identifying is left. The GREEN copy is re-wrapped so data science can open it.'}
          </p>
          <fieldset className="fieldset">
            <label className="label" htmlFor="decision-reason">Reason (logged, at least {MIN_REASON} characters)</label>
            <textarea id="decision-reason" required minLength={MIN_REASON} className="textarea textarea-sm h-20 w-full"
                      value={reason} onChange={(e) => setReason(e.target.value)} />
          </fieldset>
          <div className="modal-action">
            <button type="button" className="btn btn-sm" onClick={() => decisionDialog.current?.close()}>Cancel</button>
            <button className={decision === 'erase' ? 'btn btn-sm btn-error' : 'btn btn-sm btn-primary'} disabled={busy || reason.trim().length < MIN_REASON}>
              {decision === 'erase' ? 'Erase call' : 'Release to GREEN'}
            </button>
          </div>
        </form>
        <form method="dialog" className="modal-backdrop"><button>close</button></form>
      </dialog>

      <dialog ref={exportDialog} className="modal" aria-labelledby="export-title">
        <div className="modal-box max-w-2xl">
          <h3 id="export-title" className="text-lg font-semibold">GREEN training set</h3>
          {exported && (
            <>
              <p className="py-2 text-sm text-base-content/70">
                {exported.manifest.n_calls} calls, decrypted with your own attribute key. {exported.manifest.n_gated} had a
                quasi-identifier combination shared by fewer than k = {exported.manifest.k} calls and lost those quasi-IDs.
                {exported.manifest.withheld_for_review.length > 0 && ` ${exported.manifest.withheld_for_review.length} held for privacy review ${exported.manifest.withheld_for_review.length === 1 ? 'is' : 'are'} not included.`}
              </p>
              <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
                <dt className="text-base-content/60">SHA-256</dt><dd className="break-all font-mono">{exported.manifest.sha256}</dd>
                <dt className="text-base-content/60">Policy version</dt><dd className="font-mono">{exported.manifest.policy_version}</dd>
                <dt className="text-base-content/60">Logged as</dt><dd className="font-mono">#{exported.manifest.audit_seq}</dd>
                <dt className="text-base-content/60">Signature</dt><dd className="break-all font-mono">{exported.signature.slice(0, 48)}…</dd>
              </dl>
              <p className="pt-2 text-xs text-base-content/60">Verify the manifest offline with the public key at <code className="font-mono">/api/signing-key</code>.</p>
            </>
          )}
          <div className="modal-action">
            <form method="dialog"><button className="btn btn-sm">Close</button></form>
            <button className="btn btn-sm btn-primary" onClick={download}>
              <Download size={14} aria-hidden="true" /> Download JSONL and manifest
            </button>
          </div>
        </div>
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
