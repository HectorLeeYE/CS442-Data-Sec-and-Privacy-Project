import { KeyRound, LogIn, User as UserIcon } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { api, session, type Tier, type User } from '../api'
import TierBadge from '../components/TierBadge'

const DEMO: { username: string; who: string; tier: Tier; sees: string }[] = [
  { username: 'compliance', who: 'Rachel Ong, compliance', tier: 'RED', sees: 'High-risk calls in full, credentials still withheld; low-risk calls only with a logged reason.' },
  { username: 'priya', who: 'Priya Nair, call agent', tier: 'AMBER', sees: 'Own calls with names pseudonymised and accounts masked.' },
  { username: 'daniel', who: 'Daniel Koh, call agent', tier: 'AMBER', sees: 'Same as Priya, for his own calls; not hers.' },
  { username: 'datasci', who: 'Alex Chua, data science', tier: 'GREEN', sees: 'De-identified training text with realistic surrogates; the training-set export.' },
  { username: 'model', who: 'ASR training pipeline', tier: 'GREEN', sees: 'Service account: the model gets GREEN data, not raw.' },
]

export default function SignIn({ onSignedIn }: { onSignedIn: (u: User) => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const res = await api<{ token: string; user: User }>('/api/login', {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      })
      session.set(res.token)
      onSignedIn(res.user)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign-in failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="grid min-h-screen bg-base-200 lg:grid-cols-[1fr_28rem]">
      <section className="flex flex-col justify-center gap-6 p-6 md:p-12">
        <div className="font-mono text-2xl font-medium tracking-tight">
          quiet<span className="rounded-sm bg-base-content px-1 text-base-100">line</span>
        </div>
        <h1 className="max-w-xl text-3xl font-semibold leading-tight md:text-4xl">
          One recorded call. Three people. Three different transcripts.
        </h1>
        <p className="max-w-xl text-base-content/70">
          Compliance must read the call to approve a high-risk transfer. The agent needs it for follow-up. Data
          science needs it to train the transcription model. Each gets only what their clearance allows, and every
          release is logged.
        </p>
        <div className="max-w-full overflow-x-auto">
          <table className="table table-sm max-w-xl bg-base-100">
            <caption className="caption-top pb-2 text-left text-xs text-base-content/60">
              Demo accounts — select one to fill the form. Password for all: <code className="font-mono">demo</code>
            </caption>
            <thead>
              <tr><th>Account</th><th>Clearance</th><th>Sees</th></tr>
            </thead>
            <tbody>
              {DEMO.map((d) => (
                <tr key={d.username}>
                  <td>
                    <button
                      type="button"
                      className="btn btn-xs btn-ghost font-mono"
                      onClick={() => { setUsername(d.username); setPassword('demo') }}
                      aria-label={`Use ${d.who} account`}
                    >
                      {d.username}
                    </button>
                    <div className="text-xs text-base-content/60">{d.who}</div>
                  </td>
                  <td><TierBadge tier={d.tier} /></td>
                  <td className="text-xs">{d.sees}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="flex items-center justify-center border-base-300 bg-base-100 p-6 lg:border-l">
        <form onSubmit={submit} className="w-full max-w-sm">
          <fieldset className="fieldset gap-2">
            <legend className="fieldset-legend text-lg">Sign in</legend>
            <label className="label" htmlFor="username">Username</label>
            <label className="input input-sm validator w-full">
              <UserIcon size={14} aria-hidden="true" />
              <input id="username" required autoComplete="username" value={username}
                     onChange={(e) => setUsername(e.target.value)} placeholder="compliance" />
            </label>
            <p className="validator-hint hidden">Enter your username</p>
            <label className="label" htmlFor="password">Password</label>
            <label className="input input-sm validator w-full">
              <KeyRound size={14} aria-hidden="true" />
              <input id="password" type="password" required autoComplete="current-password" value={password}
                     onChange={(e) => setPassword(e.target.value)} />
            </label>
            <p className="validator-hint hidden">Enter your password</p>
            {error && <div role="alert" className="alert alert-soft alert-error text-sm">{error}</div>}
            <button className="btn btn-sm btn-primary mt-2" disabled={busy}>
              {busy ? <span className="loading loading-spinner loading-xs" /> : <LogIn size={14} aria-hidden="true" />}
              Sign in
            </button>
            <p className="label whitespace-normal text-xs">Your clearance is read from the server on every request, not from this session.</p>
          </fieldset>
        </form>
      </section>
    </main>
  )
}
