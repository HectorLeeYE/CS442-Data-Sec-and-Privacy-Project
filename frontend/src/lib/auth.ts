/**
 * Authentication context.
 *
 * The session is a bearer token plus the profile the server returns for it. The
 * *effective* attribute set always comes from the server (`/api/auth/me`), because
 * an administrator can re-issue an attribute set while a session is open.
 */

import { createContext, useContext } from 'react'
import type { UserProfile } from './types'

export const TOKEN_STORAGE_KEY = 'cpabe.access-token'

export type AuthStatus = 'loading' | 'authenticated' | 'anonymous'

export interface AuthValue {
  status: AuthStatus
  token: string | null
  user: UserProfile | null
  /** Claims as the server read them from the token (session view). */
  claims: Record<string, unknown> | null
  cryptoBackend: string
  /** True when a stored token was rejected, so the sign-in page can explain why. */
  sessionExpired: boolean
  signIn: (email: string, password: string) => Promise<UserProfile>
  signOut: () => Promise<void>
  refresh: () => Promise<void>
  hasRole: (...roles: string[]) => boolean
  setCryptoBackend: (value: string) => void
}

export const AuthContext = createContext<AuthValue | null>(null)

export function useAuth(): AuthValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside <AuthProvider>.')
  return value
}

export function readStoredToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_STORAGE_KEY)
  } catch {
    return null
  }
}

export function storeToken(token: string): void {
  try {
    window.localStorage.setItem(TOKEN_STORAGE_KEY, token)
  } catch {
    /* Storage can be unavailable in private modes; the session still works. */
  }
}

export function clearStoredToken(): void {
  try {
    window.localStorage.removeItem(TOKEN_STORAGE_KEY)
  } catch {
    /* ignore */
  }
}
