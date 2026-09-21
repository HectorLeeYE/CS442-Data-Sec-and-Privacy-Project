import {
  ChevronDown,
  KeyRound,
  LogOut,
  Menu as MenuIcon,
  RefreshCw,
  ScrollText,
  Search,
  ShieldCheck,
  Users,
} from 'lucide-react'
import type { CSSProperties, ReactNode } from 'react'
import { useAuth } from '../lib/auth.ts'
import AttributeChips from './AttributeChips.tsx'

export type DashboardView = 'query' | 'key' | 'audit' | 'users'

interface NavItem {
  view: DashboardView
  label: string
  description: string
  icon: ReactNode
  adminOnly: boolean
}

const NAV_ITEMS: NavItem[] = [
  {
    view: 'query',
    label: 'Query console',
    description: 'Decrypt and filter records',
    icon: <Search size={16} aria-hidden="true" />,
    adminOnly: false,
  },
  {
    view: 'key',
    label: 'My key material',
    description: 'Attribute set and session claims',
    icon: <KeyRound size={16} aria-hidden="true" />,
    adminOnly: false,
  },
  {
    view: 'audit',
    label: 'Audit trail',
    description: 'Every access decision',
    icon: <ScrollText size={16} aria-hidden="true" />,
    adminOnly: true,
  },
  {
    view: 'users',
    label: 'Accounts',
    description: 'Approve and re-issue attributes',
    icon: <Users size={16} aria-hidden="true" />,
    adminOnly: true,
  },
]

interface AppShellProps {
  activeView: DashboardView
  onViewChange: (view: DashboardView) => void
  children: ReactNode
}

/**
 * Application shell: a persistent sidebar on large screens, a drawer on small
 * ones. Administrator destinations are hidden without the role, and the API
 * refuses them regardless.
 */
export default function AppShell({ activeView, onViewChange, children }: AppShellProps) {
  const { user, cryptoBackend, signOut, refresh } = useAuth()
  const isAdmin = Boolean(user?.roles.includes('admin'))
  const visibleItems = NAV_ITEMS.filter((item) => !item.adminOnly || isAdmin)

  return (
    <div className="drawer lg:drawer-open">
      <input id="app-drawer" type="checkbox" className="drawer-toggle" />

      <div className="drawer-content flex min-h-screen flex-col bg-base-100">
        <div className="navbar sticky top-0 z-20 border-b border-base-300 bg-base-200 px-2">
          <div className="flex-none lg:hidden">
            <label
              htmlFor="app-drawer"
              aria-label="Open navigation"
              className="btn btn-square btn-sm btn-ghost drawer-button tooltip tooltip-right"
              data-tip="Open navigation"
            >
              <MenuIcon size={18} aria-hidden="true" />
            </label>
          </div>

          <div className="mx-2 flex min-w-0 flex-1 items-center gap-2">
            <ShieldCheck size={18} aria-hidden="true" className="text-primary" />
            <span className="truncate text-sm font-semibold">CP-ABE query console</span>
            <span className="badge badge-sm badge-outline hidden font-mono sm:inline-flex">
              {cryptoBackend}
            </span>
          </div>

          <div className="flex flex-none items-center gap-2">
            <div className="hidden text-right sm:block">
              <p className="text-xs font-medium">{user?.full_name}</p>
              <p className="font-mono text-[0.6875rem] text-base-content/60">{user?.email}</p>
            </div>

            <button
              type="button"
              className="btn btn-ghost btn-sm"
              popoverTarget="account-menu"
              style={{ anchorName: '--account-menu' } as CSSProperties}
            >
              <KeyRound size={15} aria-hidden="true" />
              <span className="hidden sm:inline">Account</span>
              <ChevronDown size={14} aria-hidden="true" />
            </button>

            <ul
              popover="auto"
              id="account-menu"
              className="dropdown menu w-72 rounded-box border border-base-300 bg-base-100 p-2"
              style={{ positionAnchor: '--account-menu' } as CSSProperties}
            >
              <li className="menu-title">
                <span className="font-mono text-[0.6875rem]">
                  {user?.roles.join(', ') || 'no roles'}
                </span>
              </li>
              <li>
                <button type="button" onClick={() => void refresh()}>
                  <RefreshCw size={14} aria-hidden="true" />
                  Reload my profile
                </button>
              </li>
              <li>
                <button type="button" onClick={() => void signOut()}>
                  <LogOut size={14} aria-hidden="true" />
                  Sign out
                </button>
              </li>
            </ul>
          </div>
        </div>

        <main className="flex min-w-0 flex-1 flex-col gap-4 p-4 lg:p-6">{children}</main>
      </div>

      <div className="drawer-side z-30">
        <label
          htmlFor="app-drawer"
          aria-label="Close navigation"
          className="drawer-overlay"
        ></label>
        <aside className="flex min-h-full w-72 flex-col gap-4 border-r border-base-300 bg-base-200 p-4">
          <div className="flex items-center gap-2">
            <ShieldCheck size={18} aria-hidden="true" className="text-primary" />
            <span className="text-sm font-semibold">CP-ABE query console</span>
          </div>

          <nav aria-label="Dashboard sections">
            <ul className="menu w-full gap-1">
              {visibleItems.map((item) => (
                <li key={item.view}>
                  <button
                    type="button"
                    className={item.view === activeView ? 'menu-active' : undefined}
                    aria-current={item.view === activeView ? 'page' : undefined}
                    onClick={() => onViewChange(item.view)}
                  >
                    {item.icon}
                    <span className="flex flex-col items-start">
                      <span>{item.label}</span>
                      <span className="font-mono text-[0.6875rem] text-base-content/60">
                        {item.description}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </nav>

          <div className="divider text-xs">your attribute set</div>
          <AttributeChips
            attributes={user?.attributes ?? []}
            emptyLabel="No attributes: nothing will decrypt."
            small
          />
          <p className="text-xs text-base-content/60">
            Attributes are re-read from the server on every request, so an administrator can
            change what you can read while this session stays open.
          </p>
        </aside>
      </div>
    </div>
  )
}
