import type { ReactNode } from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, api } from '../lib/api.ts'
import {
  AuthContext,
  clearStoredToken,
  readStoredToken,
  storeToken,
  type AuthStatus,
  type AuthValue,
} from '../lib/auth.ts'
import type { UserProfile } from '../lib/types.ts'

/**
 * Holds the session and keeps the profile fresh.
 *
 * On mount a stored token is validated against `/api/auth/me`; if the server
 * refuses it (expired, disabled account) the token is discarded and the sign-in
 * page explains that the session ended.
 */
export default function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>(() =>
    readStoredToken() ? 'loading' : 'anonymous',
  )
  const [token, setToken] = useState<string | null>(() => readStoredToken())
  const [user, setUser] = useState<UserProfile | null>(null)
  const [claims, setClaims] = useState<Record<string, unknown> | null>(null)
  const [cryptoBackend, setCryptoBackend] = useState('stub')
  const [sessionExpired, setSessionExpired] = useState(false)

  useEffect(() => {
    if (!token) return
    let cancelled = false
    api
      .me(token)
      .then((me) => {
        if (cancelled) return
        setUser(me.user)
        setClaims(me.claims)
        setCryptoBackend(me.crypto_backend)
        setStatus('authenticated')
      })
      .catch((error: unknown) => {
        if (cancelled) return
        clearStoredToken()
        setToken(null)
        setUser(null)
        setClaims(null)
        setStatus('anonymous')
        setSessionExpired(error instanceof ApiError)
      })
    return () => {
      cancelled = true
    }
  }, [token])

  const signIn = useCallback(async (email: string, password: string): Promise<UserProfile> => {
    const result = await api.signIn(email, password)
    storeToken(result.access_token)
    setSessionExpired(false)
    setCryptoBackend(result.crypto_backend)
    setUser(result.user)
    // Setting the token re-runs the effect above, which also loads the claims view.
    setToken(result.access_token)
    setStatus('authenticated')
    return result.user
  }, [])

  const signOut = useCallback(async () => {
    const current = token
    clearStoredToken()
    setToken(null)
    setUser(null)
    setClaims(null)
    setStatus('anonymous')
    if (current) {
      try {
        // Best effort: the audit trail records the sign-out when it succeeds.
        await api.signOut(current)
      } catch {
        /* the session is already gone locally */
      }
    }
  }, [token])

  const refresh = useCallback(async () => {
    if (!token) return
    const me = await api.me(token)
    setUser(me.user)
    setClaims(me.claims)
    setCryptoBackend(me.crypto_backend)
  }, [token])

  const hasRole = useCallback(
    (...roles: string[]) => Boolean(user && roles.some((role) => user.roles.includes(role))),
    [user],
  )

  const value = useMemo<AuthValue>(
    () => ({
      status,
      token,
      user,
      claims,
      cryptoBackend,
      sessionExpired,
      signIn,
      signOut,
      refresh,
      hasRole,
      setCryptoBackend,
    }),
    [status, token, user, claims, cryptoBackend, sessionExpired, signIn, signOut, refresh, hasRole],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
