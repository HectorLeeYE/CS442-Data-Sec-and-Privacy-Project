import { BarChart3, FileLock2, LogOut, Menu, ScrollText, Table2 } from 'lucide-react'
import { lazy, Suspense, useEffect, useState } from 'react'
import { api, session, type User } from './api'
import TierBadge from './components/TierBadge'
import Audit from './pages/Audit'
import Calls from './pages/Calls'
import Policy from './pages/Policy'
import SignIn from './pages/SignIn'

const Results = lazy(() => import('./pages/Results')) // ApexCharts is most of the bundle

const ROUTES = [
  { path: 'calls', label: 'Calls', Icon: FileLock2, Page: Calls },
  { path: 'audit', label: 'Disclosure log', Icon: ScrollText, Page: Audit },
  { path: 'policy', label: 'Redaction policy', Icon: Table2, Page: Policy },
  { path: 'results', label: 'Experiment results', Icon: BarChart3, Page: Results },
] as const

function useHashRoute() {
  const read = () => window.location.hash.replace(/^#\/?/, '') || 'calls'
  const [route, setRoute] = useState(read)
  useEffect(() => {
    const on = () => setRoute(read())
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  return route
}

export default function App() {
  const [user, setUser] = useState<User | null>(null)
  const [checking, setChecking] = useState(Boolean(session.get()))
  const route = useHashRoute()

  useEffect(() => {
    if (!session.get()) return
    api<User>('/api/me')
      .then(setUser)
      .catch(() => session.clear())
      .finally(() => setChecking(false))
  }, [])

  if (checking) {
    return (
      <main className="grid min-h-screen place-items-center bg-base-200">
        <span className="loading loading-spinner loading-md" aria-label="Restoring session" />
      </main>
    )
  }
  if (!user) return <SignIn onSignedIn={setUser} />

  const current = ROUTES.find((r) => route.startsWith(r.path)) ?? ROUTES[0]
  const signOut = () => {
    session.clear()
    setUser(null)
  }

  return (
    <div className="drawer lg:drawer-open">
      <input id="nav-drawer" type="checkbox" className="drawer-toggle" />
      <div className="drawer-content flex min-h-screen min-w-0 flex-col bg-base-200">
        <nav className="navbar min-h-14 border-b border-base-300 bg-base-100 px-3">
          <div className="navbar-start gap-2">
            <label htmlFor="nav-drawer" aria-label="Open navigation" className="btn btn-sm btn-square btn-ghost drawer-button lg:hidden">
              <Menu size={18} aria-hidden="true" />
            </label>
            <h1 className="text-sm font-semibold">{current.label}</h1>
          </div>
          <div className="navbar-end gap-3">
            <div className="hidden text-right text-xs leading-tight sm:block">
              <div className="font-medium">{user.display_name}</div>
              <div className="text-base-content/60">clearance</div>
            </div>
            <TierBadge tier={user.tier} />
            <button className="btn btn-sm btn-ghost" onClick={signOut}>
              <LogOut size={16} aria-hidden="true" />
              <span className="hidden sm:inline">Sign out</span>
            </button>
          </div>
        </nav>
        <main className="min-w-0 flex-1 overflow-x-clip p-3 md:p-5">
          <Suspense fallback={<div className="skeleton h-80 w-full" />}>
            <current.Page user={user} />
          </Suspense>
        </main>
      </div>
      <div className="drawer-side z-20">
        <label htmlFor="nav-drawer" aria-label="Close navigation" className="drawer-overlay" />
        <aside className="flex min-h-full w-60 flex-col border-r border-base-300 bg-base-100">
          <div className="px-5 pb-3 pt-5">
            <div className="font-mono text-lg font-medium tracking-tight">
              quiet<span className="rounded-sm bg-base-content px-1 text-base-100">line</span>
            </div>
            <p className="mt-1 text-xs text-base-content/60">Bank call transcripts, released per clearance.</p>
          </div>
          <ul className="menu w-full">
            {ROUTES.map(({ path, label, Icon }) => (
              <li key={path}>
                <a href={`#/${path}`} className={current.path === path ? 'menu-active' : undefined}>
                  <Icon size={16} aria-hidden="true" />
                  {label}
                </a>
              </li>
            ))}
          </ul>
          <p className="mt-auto px-5 pb-5 text-xs text-base-content/50">
            CS442 prototype. All transcripts are synthetic sample data.
          </p>
        </aside>
      </div>
    </div>
  )
}
