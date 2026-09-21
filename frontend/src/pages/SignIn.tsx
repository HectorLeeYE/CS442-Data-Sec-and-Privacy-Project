import { Eye, EyeOff, KeyRound, Lock, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { ApiError, api } from '../lib/api.ts'
import { useAuth } from '../lib/auth.ts'
import { useAsync } from '../lib/useAsync.ts'

/**
 * Sign-in page.
 *
 * Credentials are only half of the story: what comes back is a session that carries
 * an attribute set. The side panel states that model up front, and the sample-account
 * list shows the attribute set each demo account signs in with.
 */
export default function SignIn() {
  const { signIn, status, sessionExpired } = useAuth()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const next = searchParams.get('next') ?? '/dashboard'

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const demo = useAsync((signal) => api.demoAccounts(signal), [])

  if (status === 'authenticated') {
    return <Navigate to={next} replace />
  }

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      await signIn(email.trim().toLowerCase(), password)
      navigate(next, { replace: true })
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : 'Sign-in failed unexpectedly. Check that the API is running on port 8000.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen bg-base-100">
      <div className="mx-auto grid min-h-screen max-w-6xl items-center gap-8 p-4 lg:grid-cols-2 lg:p-10">
        <section className="flex flex-col gap-4">
          <div className="flex items-center gap-2">
            <ShieldCheck size={20} aria-hidden="true" className="text-secondary" />
            <span className="text-sm font-semibold">CP-ABE data anonymization demo</span>
          </div>

          <div className="card border border-base-300 bg-base-200">
            <div className="card-body gap-4 p-5">
              <div className="flex flex-col gap-1">
                <h1 className="card-title text-xl">Sign in to the query console</h1>
                <p className="text-sm text-base-content/70">
                  Query anonymized sample records. Each record carries its own ciphertext
                  policy, so what you can read depends on the attribute set behind your
                  account.
                </p>
              </div>

              {sessionExpired ? (
                <div className="alert alert-warning" role="status">
                  <Lock size={16} aria-hidden="true" />
                  <span className="text-xs">
                    Your previous session ended. Sign in again to continue.
                  </span>
                </div>
              ) : null}

              {error ? (
                <div className="alert alert-error" role="alert">
                  <span className="text-xs">{error}</span>
                </div>
              ) : null}

              <form className="flex flex-col gap-4" onSubmit={submit}>
                <fieldset className="fieldset min-w-0 gap-1">
                  <label className="label" htmlFor="signin-email">
                    Email
                  </label>
                  <input
                    id="signin-email"
                    type="email"
                    className="input input-sm validator w-full"
                    placeholder="dr.okafor@demo.local"
                    autoComplete="username"
                    required
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                  />
                  <p className="validator-hint hidden">Enter the account email address</p>
                </fieldset>

                <fieldset className="fieldset min-w-0 gap-1">
                  <label className="label" htmlFor="signin-password">
                    Password
                  </label>
                  <input
                    id="signin-password"
                    type={showPassword ? 'text' : 'password'}
                    className="input input-sm validator w-full"
                    placeholder="demo1234"
                    autoComplete="current-password"
                    required
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                  />
                  <p className="validator-hint hidden">Enter your password</p>
                  <label className="label cursor-pointer justify-start gap-2">
                    <span className="swap">
                      <input
                        type="checkbox"
                        checked={showPassword}
                        onChange={(event) => setShowPassword(event.target.checked)}
                        aria-label="Show password"
                      />
                      <span className="swap-off">
                        <Eye size={14} aria-hidden="true" />
                      </span>
                      <span className="swap-on">
                        <EyeOff size={14} aria-hidden="true" />
                      </span>
                    </span>
                    <span className="text-xs text-base-content/70">Show password</span>
                  </label>
                </fieldset>

                <button
                  className="btn btn-primary btn-sm w-full"
                  type="submit"
                  disabled={submitting}
                >
                  {submitting ? (
                    <span className="loading loading-spinner loading-xs"></span>
                  ) : (
                    <KeyRound size={14} aria-hidden="true" />
                  )}
                  Sign in
                </button>
              </form>

              <p className="text-xs text-base-content/60">
                Accounts and attribute sets are provisioned by the study administrator, so
                there is no self-service sign-up here. The session is kept in this browser
                for the duration of the demo.
              </p>
            </div>
          </div>
        </section>

        <aside className="hidden flex-col gap-4 lg:flex">
          <div className="card border border-base-300 bg-base-100">
            <div className="card-body gap-3 p-5">
              <h2 className="card-title text-base">How access is decided</h2>
              <ol className="flex flex-col gap-3 text-sm">
                <li className="flex gap-3">
                  <span className="badge badge-sm badge-outline font-mono">1</span>
                  <span>
                    <strong>Roles</strong> guard whole areas: the audit trail and account
                    management need the <code className="font-mono text-xs">admin</code> role.
                  </span>
                </li>
                <li className="flex gap-3">
                  <span className="badge badge-sm badge-outline font-mono">2</span>
                  <span>
                    <strong>Attributes</strong> decide records. Every record's ciphertext
                    policy is tested against your attribute set before any value is read.
                  </span>
                </li>
                <li className="flex gap-3">
                  <span className="badge badge-sm badge-outline font-mono">3</span>
                  <span>
                    <strong>Refusals are explained.</strong> You see the policy, the reason,
                    and which attribute would change the outcome - never the refused values.
                  </span>
                </li>
              </ol>
            </div>
          </div>

          <div className="card border border-base-300 bg-base-100">
            <div className="card-body gap-3 p-5">
              <h2 className="card-title text-base">Sample accounts</h2>
              <p className="text-xs text-base-content/60">
                Sample content for this teaching demo. Selecting one fills the form so you can
                compare two attribute sets side by side.
              </p>

              {demo.loading ? (
                <div className="flex items-center gap-2 text-xs text-base-content/60">
                  <span className="loading loading-spinner loading-xs"></span>
                  Loading sample accounts…
                </div>
              ) : null}

              {demo.error ? (
                <div className="alert alert-warning" role="status">
                  <span className="text-xs">
                    Sample accounts are unavailable. {demo.error}
                  </span>
                </div>
              ) : null}

              <ul className="flex flex-col gap-2">
                {(demo.data?.accounts ?? []).map((account) => (
                  <li key={account.email}>
                    <button
                      type="button"
                      className="w-full rounded-box border border-base-300 bg-base-200 p-2 text-left hover:border-secondary"
                      onClick={() => {
                        setEmail(account.email)
                        setPassword(account.password)
                        setError(null)
                      }}
                    >
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="text-xs font-semibold">{account.label}</span>
                        <span className="badge badge-sm badge-outline font-mono">
                          {account.email}
                        </span>
                        {account.status === 'active' ? null : (
                          <span className="badge badge-sm badge-warning">{account.status}</span>
                        )}
                      </span>
                      <span className="mt-1 block font-mono text-[0.6875rem] text-base-content/70">
                        {account.attributes.join(' · ')}
                      </span>
                      <span className="mt-1 block text-xs text-base-content/60">
                        {account.note}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>

              {demo.data?.notice ? (
                <p className="text-xs text-base-content/60">{demo.data.notice}</p>
              ) : null}
            </div>
          </div>
        </aside>
      </div>
    </div>
  )
}
