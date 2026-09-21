import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../lib/auth.ts'

/**
 * Route guard. Anonymous visitors are sent to the sign-in page with the intended
 * destination preserved, so a deep link survives the round trip.
 */
export default function RequireAuth({ children }: { children: ReactNode }) {
  const { status } = useAuth()
  const location = useLocation()

  if (status === 'loading') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-base-100 p-6">
        <div className="card bg-base-200 border border-base-300 w-full max-w-sm">
          <div className="card-body items-center gap-3 text-center">
            <span className="loading loading-spinner loading-md text-primary"></span>
            <p className="text-sm text-base-content/70">Checking your session…</p>
          </div>
        </div>
      </div>
    )
  }

  if (status === 'anonymous') {
    const next = `${location.pathname}${location.search}`
    return <Navigate to={`/login?next=${encodeURIComponent(next)}`} replace />
  }

  return <>{children}</>
}
